from collections.abc import Mapping

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="MuseEcho")

    @app.get("/api/health")
    def health() -> Mapping[str, str]:
        return {"status": "ready"}

    return app
