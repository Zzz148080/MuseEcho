from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import logging
import os
import shutil
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
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from museecho.app import create_app
from museecho.application.access import AccessService
from museecho.application.accounts import AccountService
from museecho.application.coordinator import AnalysisCoordinator
from museecho.application.explanations import ExplanationService
from museecho.application.library import LibraryService
from museecho.application.lifecycle import AnalysisLifecycleService
from museecho.application.queue import SingleWorkerQueue
from museecho.application.uploads import FFmpegAudioValidator, UploadSubmissionService
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


class TestMailer:
    def __init__(self, root: Path) -> None:
        self.path = root / "last-mail.txt"
        self.address: str | None = None
        self.body: str | None = None

    def send(
        self,
        address: str,
        subject: str,
        body: str,
        *,
        template_key: str | None = None,
        template_data: dict[str, str] | None = None,
    ) -> None:
        del subject, template_key, template_data
        self.address = address
        self.body = body
        self.path.write_text(body, encoding="utf-8")


def _audio_tool(repository_root: Path, name: str) -> str:
    configured = os.environ.get(f"MUSEECHO_E2E_{name.upper()}")
    if configured:
        candidate = Path(configured).resolve()
        if candidate.is_file():
            return str(candidate)
        raise RuntimeError(f"configured {name} executable does not exist")
    discovered = shutil.which(name) or shutil.which(f"{name}.exe")
    if discovered:
        return discovered
    bundled = list(
        (repository_root / "tmp" / "frontend-tools" / "ffmpeg").glob(
            f"**/{name}.exe"
        )
    )
    if len(bundled) == 1:
        return str(bundled[0].resolve())
    raise RuntimeError(
        f"{name} is required for E2E audio analysis; set MUSEECHO_E2E_{name.upper()}"
    )


def build_system_app(
    *, host: str, port: int, scheme: str = "https", runtime_root: Path | None = None
):
    if scheme not in {"https", "http"}:
        raise ValueError("unsupported preview scheme")
    if scheme == "http" and not ipaddress.ip_address(host).is_loopback:
        raise ValueError("HTTP preview is restricted to loopback")
    repository_root = Path(__file__).resolve().parent.parent
    runtime_parent = repository_root / "tmp" / "e2e-runtime"
    runtime_parent.mkdir(parents=True, exist_ok=True)
    if runtime_root is None:
        runtime_root = runtime_parent / f"run-{uuid.uuid4().hex}"
        runtime_root.mkdir()
    else:
        runtime_root = runtime_root.resolve()
        if not runtime_root.is_relative_to(runtime_parent.resolve()) or not runtime_root.is_dir():
            raise ValueError("runtime root must be an existing E2E run")
    database_url = f"sqlite:///{(runtime_root / 'museecho.db').as_posix()}"
    init_db(database_url)
    session_factory = create_session_factory(database_url)
    repository = SqliteAnalysisRepository(session_factory)
    ffprobe_executable = _audio_tool(repository_root, "ffprobe")
    ffmpeg_executable = _audio_tool(repository_root, "ffmpeg")
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
        ffprobe_executable=ffprobe_executable,
        ffmpeg_executable=ffmpeg_executable,
    )
    queue = SingleWorkerQueue(repository, coordinator)
    upload_service = UploadSubmissionService(
        repository=repository,
        audio_store=audio_store,
        access_service=access_service,
        queue=queue,
        temp_root=runtime_root / "uploads",
        validator=FFmpegAudioValidator(
            ffprobe_executable=ffprobe_executable,
            ffmpeg_executable=ffmpeg_executable,
        ),
    )
    origin = f"{scheme}://{host}:{port}"
    test_mailer = TestMailer(runtime_root)
    account_service = AccountService(session_factory, mailer=test_mailer, public_origin=origin)
    library_service = LibraryService(session_factory, AnalysisLifecycleService(repository))
    app = create_app(
        upload_service=upload_service,
        repository=repository,
        access_service=access_service,
        audio_store=audio_store,
        explanation_service=ExplanationService(None),
        account_service=account_service,
        library_service=library_service,
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

    if ipaddress.ip_address(host).is_loopback:

        @app.get("/__test/mail-link", include_in_schema=False)
        def latest_test_mail(email: str, request: Request) -> Response:
            if not request.client or not ipaddress.ip_address(request.client.host).is_loopback:
                return Response(status_code=404)
            if test_mailer.address != email.strip().lower() or not test_mailer.body:
                return Response(status_code=404)
            link = next(
                (line for line in test_mailer.body.splitlines() if line.startswith(origin + "/#")),
                None,
            )
            return JSONResponse({"link": link}) if link else Response(status_code=404)

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
    parser.add_argument("--scheme", choices=["http", "https"], default="https")
    parser.add_argument("--runtime-root", type=Path)
    arguments = parser.parse_args()
    app, runtime_root = build_system_app(
        host=arguments.host,
        port=arguments.port,
        scheme=arguments.scheme,
        runtime_root=arguments.runtime_root,
    )
    certificate, key = (
        _write_certificate(runtime_root, arguments.host)
        if arguments.scheme == "https"
        else (None, None)
    )
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=arguments.host,
            port=arguments.port,
            ssl_certfile=str(certificate) if certificate else None,
            ssl_keyfile=str(key) if key else None,
            access_log=False,
            timeout_graceful_shutdown=3,
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
