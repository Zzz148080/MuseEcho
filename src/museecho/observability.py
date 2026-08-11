from __future__ import annotations

import json
import logging
import math
import threading
import uuid
from collections.abc import Mapping

from museecho.domain.status import AnalysisStage

LOGGER = logging.getLogger("museecho.analysis")


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

    def observe_analysis_failure(self) -> None:
        with self._lock:
            self._analysis_failure_count += 1

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


__all__ = ["RuntimeMetrics"]
