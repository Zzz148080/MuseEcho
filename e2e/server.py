from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from museecho.app import create_app
from museecho.application.access import AccessService
from museecho.application.coordinator import AnalysisCoordinator
from museecho.application.explanations import ExplanationService
from museecho.application.queue import SingleWorkerQueue
from museecho.application.uploads import UploadSubmissionService
from museecho.infrastructure.audio_store import ChunkedEncryptedAudioStore
from museecho.infrastructure.db import create_session_factory
from museecho.infrastructure.repositories import SqliteAnalysisRepository, init_db


class TestSecretStore:
    source = "synthetic-e2e"

    def __init__(self) -> None:
        self._value = base64.urlsafe_b64encode(b"e" * 32).decode("ascii")

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value

    def clear(self) -> bool:
        self._value = ""
        return True


def build_system_app(*, host: str, port: int):
    repository_root = Path(__file__).resolve().parent.parent
    runtime_parent = repository_root / "tmp" / "e2e-runtime"
    runtime_parent.mkdir(parents=True, exist_ok=True)
    runtime_root = runtime_parent / f"run-{uuid.uuid4().hex}"
    runtime_root.mkdir()
    database_url = f"sqlite:///{(runtime_root / 'museecho.db').as_posix()}"
    init_db(database_url)
    repository = SqliteAnalysisRepository(create_session_factory(database_url))
    audio_store = ChunkedEncryptedAudioStore(
        runtime_root / "storage",
        key_store=TestSecretStore(),
        repository=repository,
        chunk_size=1024,
    )
    access_service = AccessService(repository)
    coordinator = AnalysisCoordinator(
        repository=repository,
        audio_store=audio_store,
        temp_root=runtime_root / "analysis",
    )
    queue = SingleWorkerQueue(repository, coordinator)
    upload_service = UploadSubmissionService(
        repository=repository,
        audio_store=audio_store,
        access_service=access_service,
        queue=queue,
        temp_root=runtime_root / "uploads",
    )
    origin = f"https://{host}:{port}"
    app = create_app(
        upload_service=upload_service,
        repository=repository,
        access_service=access_service,
        audio_store=audio_store,
        explanation_service=ExplanationService(None),
        trusted_origins={origin},
    )
    audit_log = runtime_root / "server.log"
    logger = _audit_logger(audit_log)

    @app.middleware("http")
    async def record_safe_request(request: Request, call_next):
        response: Response = await call_next(request)
        logger.info("%s %s %s", request.method, request.url.path, response.status_code)
        return response

    def stop_queue() -> None:
        queue.stop()

    app.router.add_event_handler("shutdown", stop_queue)

    @app.get("/favicon.ico", include_in_schema=False)
    def empty_favicon() -> Response:
        return Response(status_code=204)

    frontend_dist = repository_root / "frontend" / "dist"
    if not (frontend_dist / "index.html").is_file():
        raise RuntimeError("frontend production build is required for E2E")
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    (runtime_parent / "current-run.json").write_text(
        json.dumps(
            {
                "runtime_root": str(runtime_root),
                "audit_log": str(audit_log),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return app, runtime_root


def _audit_logger(path: Path) -> logging.Logger:
    logger = logging.getLogger(f"museecho.e2e.{uuid.uuid4().hex}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


def _write_certificate(runtime_root: Path, host: str) -> tuple[Path, Path]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "MuseEcho E2E")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=2))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address(host)), x509.DNSName("localhost")]
            ),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )
    key_path = runtime_root / "localhost-key.pem"
    certificate_path = runtime_root / "localhost-cert.pem"
    key_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return certificate_path, key_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=4173, type=int)
    arguments = parser.parse_args()
    app, runtime_root = build_system_app(host=arguments.host, port=arguments.port)
    certificate, key = _write_certificate(runtime_root, arguments.host)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=arguments.host,
            port=arguments.port,
            ssl_certfile=str(certificate),
            ssl_keyfile=str(key),
            access_log=False,
        )
    )
    shutdown_file = os.environ.get("MUSEECHO_E2E_SHUTDOWN_FILE")
    if shutdown_file:
        shutdown_path = Path(shutdown_file)

        def watch_for_shutdown() -> None:
            while not server.should_exit:
                if shutdown_path.is_file():
                    server.should_exit = True
                    return
                time.sleep(0.1)

        threading.Thread(target=watch_for_shutdown, daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()
