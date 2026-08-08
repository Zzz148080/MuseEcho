from collections.abc import Mapping

from fastapi import FastAPI

from museecho.api.analyses import install_analyses_api
from museecho.application.uploads import UploadSubmissionService


def create_app(*, upload_service: UploadSubmissionService | None = None) -> FastAPI:
    app = FastAPI(title="MuseEcho")
    if upload_service is not None:
        install_analyses_api(app, upload_service)

    @app.get("/api/health")
    def health() -> Mapping[str, str]:
        return {"status": "ready"}

    return app
