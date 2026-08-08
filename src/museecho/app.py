from collections.abc import Mapping

from fastapi import FastAPI

from museecho.api.analyses import create_analyses_router
from museecho.application.uploads import UploadSubmissionService


def create_app(*, upload_service: UploadSubmissionService | None = None) -> FastAPI:
    app = FastAPI(title="MuseEcho")
    if upload_service is not None:
        app.include_router(create_analyses_router(upload_service))

    @app.get("/api/health")
    def health() -> Mapping[str, str]:
        return {"status": "ready"}

    return app
