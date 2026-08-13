from collections.abc import Callable, Collection, Mapping

from fastapi import FastAPI
from fastapi.responses import JSONResponse
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
from museecho.observability import RequestObservabilityMiddleware


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
    app.add_middleware(RequestObservabilityMiddleware)

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
