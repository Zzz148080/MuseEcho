from __future__ import annotations

import base64
import binascii
import math
import os
import threading
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI

from museecho.app import create_app
from museecho.application.access import AccessService
from museecho.application.cleanup import AnalysisDeletionService, ExpiryCleanup
from museecho.application.coordinator import AnalysisCoordinator
from museecho.application.explanations import ExplanationService
from museecho.application.queue import SingleWorkerQueue
from museecho.application.uploads import UploadSubmissionService
from museecho.infrastructure.audio_store import ChunkedEncryptedAudioStore
from museecho.infrastructure.crypto import wipe
from museecho.infrastructure.db import create_session_factory
from museecho.infrastructure.llm import OpenAICompatibleProvider, ProviderConfig
from museecho.infrastructure.repositories import SqliteAnalysisRepository, init_db
from museecho.infrastructure.secrets import FileSecretStore

DEFAULT_CLEANUP_INTERVAL_SECONDS = 60.0


@dataclass(frozen=True)
class RuntimeSettings:
    data_root: Path
    audio_kek_file: Path
    trusted_origins: frozenset[str]
    repository_root: Path
    provider_config: ProviderConfig | None = None
    provider_secret_file: Path | None = None
    cleanup_interval_seconds: float = DEFAULT_CLEANUP_INTERVAL_SECONDS

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        repository_root: Path | None = None,
    ) -> RuntimeSettings:
        values = os.environ if environ is None else environ
        resolved_repository = (
            Path(__file__).resolve().parents[2]
            if repository_root is None
            else repository_root.resolve()
        )
        data_root = _absolute_path(values.get("MUSEECHO_DATA_ROOT", ""), "data root")
        audio_kek_file = _absolute_path(
            values.get("MUSEECHO_AUDIO_KEK_FILE", ""),
            "audio key encryption key file",
        )
        _require_outside_repository(data_root, resolved_repository, "data root")

        origins = frozenset(
            item.strip()
            for item in values.get("MUSEECHO_TRUSTED_ORIGINS", "").split(",")
            if item.strip()
        )
        if not origins:
            raise ValueError("configure at least one trusted HTTPS origin")
        for origin in origins:
            _validate_https_origin(origin)

        provider_base_url = values.get("MUSEECHO_PROVIDER_BASE_URL", "").strip()
        provider_model = values.get("MUSEECHO_PROVIDER_MODEL", "").strip()
        provider_secret_value = values.get("MUSEECHO_PROVIDER_SECRET_FILE", "").strip()
        provider_fields = (provider_base_url, provider_model, provider_secret_value)
        if any(provider_fields) and not all(provider_fields):
            raise ValueError(
                "provider base URL, model, and secret file must be configured together"
            )
        provider_config: ProviderConfig | None = None
        provider_secret_file: Path | None = None
        if all(provider_fields):
            provider_secret_file = _absolute_path(provider_secret_value, "provider secret file")
            if provider_secret_file.resolve() == audio_kek_file.resolve():
                raise ValueError("provider credential and audio encryption key must be separate")
            provider_config = ProviderConfig(provider_base_url, provider_model)

        interval_value = values.get(
            "MUSEECHO_CLEANUP_INTERVAL_SECONDS",
            str(DEFAULT_CLEANUP_INTERVAL_SECONDS),
        )
        try:
            cleanup_interval = float(interval_value)
        except ValueError:
            raise ValueError("cleanup interval must be a finite positive number") from None
        if (
            not math.isfinite(cleanup_interval)
            or cleanup_interval < 0.01
            or cleanup_interval > 3600
        ):
            raise ValueError("cleanup interval must be between 0.01 and 3600 seconds")

        return cls(
            data_root=data_root,
            audio_kek_file=audio_kek_file,
            trusted_origins=origins,
            repository_root=resolved_repository,
            provider_config=provider_config,
            provider_secret_file=provider_secret_file,
            cleanup_interval_seconds=cleanup_interval,
        )


@dataclass
class RuntimeResources:
    repository: SqliteAnalysisRepository
    queue: SingleWorkerQueue
    cleanup: ExpiryCleanup
    cleanup_stop: threading.Event
    cleanup_thread: threading.Thread | None = None


def create_runtime_app(
    *,
    settings: RuntimeSettings | None = None,
    environ: Mapping[str, str] | None = None,
) -> FastAPI:
    selected = settings or RuntimeSettings.from_environment(environ)
    _prepare_data_root(selected.data_root)
    database_url = f"sqlite:///{(selected.data_root / 'museecho.db').as_posix()}"
    init_db(database_url)
    session_factory = create_session_factory(database_url)
    repository = SqliteAnalysisRepository(session_factory)

    audio_key_store = FileSecretStore(
        selected.audio_kek_file,
        repository_root=selected.repository_root,
    )
    _validate_audio_kek(audio_key_store)
    audio_store = ChunkedEncryptedAudioStore(
        selected.data_root / "audio",
        key_store=audio_key_store,
        repository=repository,
    )
    access_service = AccessService(repository)
    coordinator = AnalysisCoordinator(
        repository=repository,
        audio_store=audio_store,
        temp_root=selected.data_root / "tmp" / "analysis",
    )
    queue = SingleWorkerQueue(repository, coordinator)
    upload_service = UploadSubmissionService(
        repository=repository,
        audio_store=audio_store,
        access_service=access_service,
        queue=queue,
        temp_root=selected.data_root / "tmp" / "uploads",
    )

    provider = None
    if selected.provider_config is not None:
        assert selected.provider_secret_file is not None
        provider_secret_store = FileSecretStore(
            selected.provider_secret_file,
            repository_root=selected.repository_root,
        )
        provider_secret_store.get()
        provider = OpenAICompatibleProvider(selected.provider_config, provider_secret_store)
    explanation_service = ExplanationService(provider)
    deletion_service = AnalysisDeletionService(repository, audio_store)
    cleanup = ExpiryCleanup(repository, deletion_service)
    resources = RuntimeResources(repository, queue, cleanup, threading.Event())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        cleanup.run_once()
        queue.start(recover=True)
        resources.cleanup_stop.clear()
        resources.cleanup_thread = threading.Thread(
            target=_run_cleanup,
            args=(resources, selected.cleanup_interval_seconds),
            name="museecho-expiry-cleanup",
            daemon=True,
        )
        resources.cleanup_thread.start()
        try:
            yield
        finally:
            resources.cleanup_stop.set()
            if resources.cleanup_thread is not None:
                resources.cleanup_thread.join(timeout=5.0)
            if not queue.stop(timeout=5.0):
                raise RuntimeError("analysis worker did not stop cleanly")
            bind = session_factory.kw.get("bind")
            if bind is not None:
                bind.dispose()

    app = create_app(
        upload_service=upload_service,
        repository=repository,
        access_service=access_service,
        audio_store=audio_store,
        explanation_service=explanation_service,
        trusted_origins=selected.trusted_origins,
        lifespan=lifespan,
    )
    app.state.museecho_runtime = resources
    return app


def app() -> FastAPI:
    """Uvicorn factory entry point for the production container."""

    return create_runtime_app()


def _run_cleanup(resources: RuntimeResources, interval_seconds: float) -> None:
    while not resources.cleanup_stop.wait(interval_seconds):
        try:
            resources.cleanup.run_once()
        except Exception:
            continue


def _validate_audio_kek(secret_store: FileSecretStore) -> None:
    encoded = secret_store.get()
    if encoded is None:
        raise ValueError("audio key encryption key cannot be empty")
    decoded = bytearray()
    try:
        decoded.extend(base64.b64decode(encoded, altchars=b"-_", validate=True))
        if len(decoded) != 32:
            raise ValueError("audio key encryption key must decode to exactly 32 bytes")
    except (binascii.Error, UnicodeEncodeError):
        raise ValueError("audio key encryption key must be valid Base64") from None
    finally:
        wipe(decoded)


def _prepare_data_root(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("data root cannot be a symbolic link")
    path.mkdir(parents=True, exist_ok=True)
    resolved = path.resolve(strict=True)
    if not resolved.is_dir() or path.is_symlink():
        raise ValueError("data root must be a directory")
    if os.name == "posix":
        resolved.chmod(0o700)


def _absolute_path(value: str, label: str) -> Path:
    candidate = Path(value.strip()) if value.strip() else Path()
    if not value.strip() or not candidate.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    return candidate


def _require_outside_repository(path: Path, repository_root: Path, label: str) -> None:
    resolved = path.resolve()
    if resolved == repository_root or repository_root in resolved.parents:
        raise ValueError(f"{label} must be outside the repository")


def _validate_https_origin(origin: str) -> None:
    parsed = urlsplit(origin)
    try:
        parsed.port
    except ValueError:
        raise ValueError("trusted origin contains an invalid port") from None
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("trusted origins must be HTTPS origins without paths or credentials")


__all__ = ["RuntimeResources", "RuntimeSettings", "app", "create_runtime_app"]
