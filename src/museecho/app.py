from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable, Collection, Mapping

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.types import Lifespan

from museecho.api.analyses import install_analyses_api
from museecho.api.audio import create_audio_router
from museecho.api.explanations import create_explanations_router
from museecho.api.results import create_results_router
from museecho.application.cleanup import AnalysisDeletionService
from museecho.application.explanations import ExplanationService
from museecho.application.lifecycle import AnalysisLifecycleService
from museecho.application.uploads import UploadSubmissionService
from museecho.domain.ports import AccessService, AnalysisRepository, EncryptedAudioStore

REQUEST_LOGGER = logging.getLogger("museecho.requests")


def create_app(
    *,
    upload_service: UploadSubmissionService | None = None,
    repository: AnalysisRepository | None = None,
    access_service: AccessService | None = None,
    audio_store: EncryptedAudioStore | None = None,
    explanation_service: ExplanationService | None = None,
    trusted_origins: Collection[str] = (),
    lifespan: Lifespan[FastAPI] | None = None,
    readiness_check: Callable[[], bool] | None = None,
    metrics_snapshot: Callable[[], Mapping[str, object]] | None = None,
) -> FastAPI:
    app = FastAPI(title="MuseEcho", lifespan=lifespan)

    @app.middleware("http")
    async def record_request(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = uuid.uuid4().hex
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            raw_length = request.headers.get("content-length", "0")
            try:
                request_bytes = max(0, int(raw_length))
            except ValueError:
                request_bytes = 0
            task_id = _task_id(request.url.path)
            REQUEST_LOGGER.info(
                json.dumps(
                    {
                        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                        "error_code": None if status_code < 400 else f"http_{status_code}",
                        "event": "http_request",
                        "request_id": request_id,
                        "resource_summary": {
                            "request_bytes": request_bytes,
                            "status_code": status_code,
                        },
                        "stage": "http",
                        "task_id": task_id,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )

    if upload_service is not None:
        install_analyses_api(app, upload_service)
    if repository is not None and access_service is not None:
        deletion_service = (
            AnalysisDeletionService(repository, audio_store) if audio_store is not None else None
        )
        lifecycle = AnalysisLifecycleService(
            repository,
            audio_store,
            explanation_service,
            deletion_service,
        )
        app.include_router(create_results_router(lifecycle, access_service, trusted_origins))
        if audio_store is not None:
            app.include_router(create_audio_router(lifecycle, access_service))
        if explanation_service is not None:
            app.include_router(
                create_explanations_router(lifecycle, access_service, trusted_origins)
            )

    @app.get("/api/health")
    def health() -> JSONResponse:
        ready = readiness_check is None or readiness_check()
        status_value = "ready" if ready else "degraded"
        content: dict[str, object] = {
            "status": status_value,
            "liveness": "alive",
            "readiness": status_value,
        }
        if metrics_snapshot is not None:
            content["metrics"] = dict(metrics_snapshot())
        return JSONResponse(status_code=200 if ready else 503, content=content)

    return app


def _task_id(path: str) -> str | None:
    parts = path.strip("/").split("/")
    if len(parts) < 3 or parts[:2] != ["api", "analyses"]:
        return None
    try:
        return str(uuid.UUID(parts[2]))
    except ValueError:
        return None
