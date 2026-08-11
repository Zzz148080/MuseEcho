from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
import uuid
from collections.abc import Mapping
from typing import Final

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from museecho.domain.status import AnalysisStage

LOGGER = logging.getLogger("museecho.analysis")
REQUEST_LOGGER = logging.getLogger("museecho.requests")
_SAFE_ERROR_CODE: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_INTERNAL_ERROR_BODY = b'{"error":{"code":"internal_error","message":"Internal server error"}}'


class RequestObservabilityMiddleware:
    """Attach an untrusted-input-independent request ID and stable safe 500 response."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex
        started = time.perf_counter()
        status_code = 500
        response_started = False
        error_code: str | None = None

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message["status"])
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self._app(scope, receive, send_with_request_id)
        except Exception:
            error_code = "internal_error"
            if response_started:
                raise
            await send_with_request_id(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(_INTERNAL_ERROR_BODY)).encode("ascii")),
                    ],
                }
            )
            await send_with_request_id({"type": "http.response.body", "body": _INTERNAL_ERROR_BODY})
        finally:
            if error_code is None and status_code >= 400:
                error_code = f"http_{status_code}"
            REQUEST_LOGGER.info(
                json.dumps(
                    {
                        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                        "error_code": error_code,
                        "event": "http_request",
                        "request_id": request_id,
                        "resource_summary": {
                            "request_bytes": _request_bytes(scope),
                            "status_code": status_code,
                        },
                        "stage": "http",
                        "task_id": _task_id(str(scope.get("path", ""))),
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )


class RuntimeMetrics:
    """Thread-safe, non-sensitive aggregate runtime observations."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._analysis_failure_count = 0
        self._cleanup_deleted_count = 0
        self._cleanup_failure_count = 0
        self._fallback_count = 0
        self._stage_duration_seconds: dict[str, float] = {}

    def observe_stage(
        self,
        analysis_id: uuid.UUID,
        stage: AnalysisStage,
        elapsed_seconds: float,
    ) -> None:
        if not math.isfinite(elapsed_seconds) or elapsed_seconds < 0:
            return
        with self._lock:
            self._stage_duration_seconds[stage.value] = (
                self._stage_duration_seconds.get(stage.value, 0.0) + elapsed_seconds
            )
        _log_event(
            event="analysis_stage",
            task_id=str(analysis_id),
            stage=stage.value,
            duration_ms=round(elapsed_seconds * 1000, 3),
            error_code=None,
            resource_summary={},
        )

    def observe_analysis_failure(
        self,
        analysis_id: uuid.UUID,
        stage: AnalysisStage,
        error_code: str,
    ) -> None:
        safe_error_code = (
            error_code if _SAFE_ERROR_CODE.fullmatch(error_code) else "analysis_failed"
        )
        with self._lock:
            self._analysis_failure_count += 1
        _log_event(
            event="analysis_failure",
            task_id=str(analysis_id),
            stage=stage.value,
            duration_ms=0.0,
            error_code=safe_error_code,
            resource_summary={},
        )

    def observe_cleanup(self, *, deleted: int) -> None:
        if deleted < 0:
            return
        with self._lock:
            self._cleanup_deleted_count += deleted

    def observe_cleanup_failure(self) -> None:
        with self._lock:
            self._cleanup_failure_count += 1

    def observe_explanation(self, *, mode: str) -> None:
        if mode != "fallback":
            return
        with self._lock:
            self._fallback_count += 1

    def snapshot(
        self,
        *,
        queue_length: int,
        active_analyses: int,
    ) -> dict[str, object]:
        if queue_length < 0 or active_analyses < 0:
            raise ValueError("queue metrics cannot be negative")
        with self._lock:
            return {
                "queue_length": queue_length,
                "active_analyses": active_analyses,
                "analysis_failure_count": self._analysis_failure_count,
                "cleanup_deleted_count": self._cleanup_deleted_count,
                "cleanup_failure_count": self._cleanup_failure_count,
                "fallback_count": self._fallback_count,
                "stage_duration_seconds": dict(sorted(self._stage_duration_seconds.items())),
            }


def _log_event(
    *,
    event: str,
    task_id: str | None,
    stage: str,
    duration_ms: float,
    error_code: str | None,
    resource_summary: Mapping[str, object],
) -> None:
    LOGGER.info(
        json.dumps(
            {
                "duration_ms": duration_ms,
                "error_code": error_code,
                "event": event,
                "request_id": None,
                "resource_summary": dict(resource_summary),
                "stage": stage,
                "task_id": task_id,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _request_bytes(scope: Scope) -> int:
    for name, raw_value in scope.get("headers", []):
        if name.lower() != b"content-length":
            continue
        try:
            return max(0, int(raw_value.decode("ascii")))
        except (UnicodeDecodeError, ValueError):
            return 0
    return 0


def _task_id(path: str) -> str | None:
    parts = path.strip("/").split("/")
    if len(parts) < 3 or parts[:2] != ["api", "analyses"]:
        return None
    try:
        return str(uuid.UUID(parts[2]))
    except ValueError:
        return None


__all__ = ["RequestObservabilityMiddleware", "RuntimeMetrics"]
