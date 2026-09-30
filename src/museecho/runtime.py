from __future__ import annotations

import base64
import binascii
import logging
import math
import os
import threading
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from ipaddress import IPv4Network, IPv6Network, ip_network
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI

from museecho.app import create_app
from museecho.application.access import AccessService
from museecho.application.accounts import AccountService, Mailer, SMTPMailer
from museecho.application.cleanup import AnalysisDeletionService, ExpiryCleanup
from museecho.application.coordinator import AnalysisCoordinator
from museecho.application.explanations import ExplanationService
from museecho.application.library import LibraryService
from museecho.application.lifecycle import AnalysisLifecycleService
from museecho.application.queue import SingleWorkerQueue
from museecho.application.uploads import UploadSubmissionService
from museecho.infrastructure.audio_store import ChunkedEncryptedAudioStore
from museecho.infrastructure.crypto import wipe
from museecho.infrastructure.db import create_session_factory
from museecho.infrastructure.llm import OpenAICompatibleProvider, ProviderConfig
from museecho.infrastructure.repositories import SqliteAnalysisRepository, init_db
from museecho.infrastructure.secrets import FileSecretStore
from museecho.infrastructure.tencent_ses import TencentSESConfig, TencentSESMailer
from museecho.observability import RuntimeMetrics

DEFAULT_CLEANUP_INTERVAL_SECONDS = 60.0
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeSettings:
    data_root: Path
    audio_kek_file: Path
    trusted_origins: frozenset[str]
    repository_root: Path
    provider_config: ProviderConfig | None = None
    provider_secret_file: Path | None = None
    cleanup_interval_seconds: float = DEFAULT_CLEANUP_INTERVAL_SECONDS
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_password_file: Path | None = None
    smtp_sender: str | None = None
    tencent_ses_config: TencentSESConfig | None = None
    tencent_ses_secret_id_file: Path | None = None
    tencent_ses_secret_key_file: Path | None = None
    public_origin: str | None = None
    trusted_proxy_networks: tuple[IPv4Network | IPv6Network, ...] = ()

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

        public_origin = values.get("MUSEECHO_PUBLIC_ORIGIN", "").strip() or sorted(origins)[0]
        if public_origin not in origins:
            raise ValueError("public origin must be one of the trusted HTTPS origins")
        proxy_networks: list[IPv4Network | IPv6Network] = []
        for value in values.get("MUSEECHO_TRUSTED_PROXY_CIDRS", "").split(","):
            if value.strip():
                try:
                    proxy_networks.append(ip_network(value.strip(), strict=True))
                except ValueError:
                    raise ValueError(
                        "trusted proxy CIDRs must be valid network addresses"
                    ) from None
        smtp_host = values.get("MUSEECHO_SMTP_HOST", "").strip()
        smtp_user = values.get("MUSEECHO_SMTP_USER", "").strip()
        smtp_password = values.get("MUSEECHO_SMTP_PASSWORD", "")
        smtp_password_file_value = values.get("MUSEECHO_SMTP_PASSWORD_FILE", "").strip()
        smtp_sender = values.get("MUSEECHO_SMTP_SENDER", "").strip()
        if smtp_password and smtp_password_file_value:
            raise ValueError("configure only one SMTP password source")
        smtp_password_file = None
        if smtp_password_file_value:
            smtp_password_file = _absolute_path(
                smtp_password_file_value,
                "SMTP password file",
            )
            if smtp_password_file.resolve() == audio_kek_file.resolve():
                raise ValueError("SMTP password and audio encryption key must be separate")
        smtp_identity = (smtp_host, smtp_user, smtp_sender)
        smtp_has_credential = bool(smtp_password or smtp_password_file)
        if (any(smtp_identity) or smtp_has_credential) and not (
            all(smtp_identity) and smtp_has_credential
        ):
            raise ValueError("SMTP host, user, password and sender must be configured together")
        try:
            smtp_port = int(values.get("MUSEECHO_SMTP_PORT", "587"))
        except ValueError:
            raise ValueError("SMTP port must be an integer") from None
        if smtp_port < 1 or smtp_port > 65535:
            raise ValueError("SMTP port is outside the valid range")

        ses_region = values.get("MUSEECHO_TENCENT_SES_REGION", "").strip()
        ses_sender = values.get("MUSEECHO_TENCENT_SES_SENDER", "").strip()
        ses_secret_id_value = values.get(
            "MUSEECHO_TENCENT_SES_SECRET_ID_FILE", ""
        ).strip()
        ses_secret_key_value = values.get(
            "MUSEECHO_TENCENT_SES_SECRET_KEY_FILE", ""
        ).strip()
        ses_verify_template_value = values.get(
            "MUSEECHO_TENCENT_SES_VERIFY_TEMPLATE_ID", ""
        ).strip()
        ses_reset_template_value = values.get(
            "MUSEECHO_TENCENT_SES_RESET_TEMPLATE_ID", ""
        ).strip()
        ses_values = (
            ses_region,
            ses_sender,
            ses_secret_id_value,
            ses_secret_key_value,
            ses_verify_template_value,
            ses_reset_template_value,
        )
        if any(ses_values) and not all(ses_values):
            raise ValueError(
                "Tencent SES region, sender, templates and credential files must be configured"
            )
        if all(ses_values) and (any(smtp_identity) or smtp_has_credential):
            raise ValueError("configure either Tencent SES API or SMTP, not both")
        tencent_ses_config = None
        tencent_ses_secret_id_file = None
        tencent_ses_secret_key_file = None
        if all(ses_values):
            try:
                verify_template_id = int(ses_verify_template_value)
                reset_template_id = int(ses_reset_template_value)
            except ValueError:
                raise ValueError("Tencent SES template IDs must be integers") from None
            tencent_ses_config = TencentSESConfig(
                ses_region,
                ses_sender,
                verify_template_id,
                reset_template_id,
            )
            tencent_ses_secret_id_file = _absolute_path(
                ses_secret_id_value,
                "Tencent SES secret ID file",
            )
            tencent_ses_secret_key_file = _absolute_path(
                ses_secret_key_value,
                "Tencent SES secret key file",
            )
            ses_secret_paths = {
                tencent_ses_secret_id_file.resolve(),
                tencent_ses_secret_key_file.resolve(),
                audio_kek_file.resolve(),
            }
            if len(ses_secret_paths) != 3:
                raise ValueError(
                    "Tencent SES credentials and audio encryption key must be separate"
                )

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
            if (
                smtp_password_file is not None
                and provider_secret_file.resolve() == smtp_password_file.resolve()
            ):
                raise ValueError("provider credential and SMTP password must be separate")
            if provider_secret_file.resolve() in {
                path.resolve()
                for path in (
                    tencent_ses_secret_id_file,
                    tencent_ses_secret_key_file,
                )
                if path is not None
            }:
                raise ValueError("provider credential and Tencent SES credentials must be separate")
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
            smtp_host=smtp_host or None,
            smtp_port=smtp_port,
            smtp_user=smtp_user or None,
            smtp_password=smtp_password or None,
            smtp_password_file=smtp_password_file,
            smtp_sender=smtp_sender or None,
            tencent_ses_config=tencent_ses_config,
            tencent_ses_secret_id_file=tencent_ses_secret_id_file,
            tencent_ses_secret_key_file=tencent_ses_secret_key_file,
            public_origin=public_origin,
            trusted_proxy_networks=tuple(proxy_networks),
        )


@dataclass
class RuntimeResources:
    repository: SqliteAnalysisRepository
    queue: SingleWorkerQueue
    cleanup: ExpiryCleanup
    cleanup_stop: threading.Event
    cleanup_failed: threading.Event
    metrics: RuntimeMetrics
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
    mailer: Mailer | None = None
    if selected.tencent_ses_config is not None:
        assert selected.tencent_ses_secret_id_file is not None
        assert selected.tencent_ses_secret_key_file is not None
        mailer = TencentSESMailer(
            selected.tencent_ses_config,
            FileSecretStore(
                selected.tencent_ses_secret_id_file,
                repository_root=selected.repository_root,
            ),
            FileSecretStore(
                selected.tencent_ses_secret_key_file,
                repository_root=selected.repository_root,
            ),
        )
    smtp_password = selected.smtp_password
    if mailer is None and selected.smtp_password_file is not None:
        smtp_password = FileSecretStore(
            selected.smtp_password_file,
            repository_root=selected.repository_root,
        ).get()
    if mailer is None and all(
        (selected.smtp_host, selected.smtp_user, smtp_password, selected.smtp_sender)
    ):
        mailer = SMTPMailer(
            selected.smtp_host or "",
            selected.smtp_port,
            selected.smtp_user or "",
            smtp_password or "",
            selected.smtp_sender or "",
        )
    account_service = AccountService(
        session_factory,
        mailer=mailer,
        public_origin=selected.public_origin or sorted(selected.trusted_origins)[0],
    )
    library_service = LibraryService(session_factory, AnalysisLifecycleService(repository))
    metrics = RuntimeMetrics()
    coordinator = AnalysisCoordinator(
        repository=repository,
        audio_store=audio_store,
        temp_root=selected.data_root / "tmp" / "analysis",
        stage_observer=metrics.observe_stage,
    )
    queue = SingleWorkerQueue(
        repository,
        coordinator,
        failure_observer=metrics.observe_analysis_failure,
    )
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
    explanation_service = ExplanationService(
        provider,
        mode_observer=lambda mode: metrics.observe_explanation(mode=mode),
    )
    deletion_service = AnalysisDeletionService(repository, audio_store)
    cleanup = ExpiryCleanup(repository, deletion_service)
    resources = RuntimeResources(
        repository,
        queue,
        cleanup,
        threading.Event(),
        threading.Event(),
        metrics,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        metrics.observe_cleanup(deleted=cleanup.run_once())
        account_service.cleanup_expired()
        queue.start(recover=True)
        resources.cleanup_stop.clear()
        resources.cleanup_thread = threading.Thread(
            target=_run_cleanup,
            args=(resources, selected.cleanup_interval_seconds, account_service),
            name="museecho-expiry-cleanup",
            daemon=True,
        )
        resources.cleanup_thread.start()
        try:
            yield
        finally:
            resources.cleanup_stop.set()
            cleanup_stopped = True
            if resources.cleanup_thread is not None:
                resources.cleanup_thread.join(timeout=5.0)
                cleanup_stopped = not resources.cleanup_thread.is_alive()
            queue_stopped = queue.stop(timeout=5.0)
            bind = session_factory.kw.get("bind")
            if bind is not None:
                bind.dispose()
            shutdown_failures = []
            if not cleanup_stopped:
                shutdown_failures.append("expiry cleanup thread did not stop cleanly")
            if not queue_stopped:
                shutdown_failures.append("analysis worker did not stop cleanly")
            if shutdown_failures:
                raise RuntimeError("; ".join(shutdown_failures))

    app = create_app(
        upload_service=upload_service,
        repository=repository,
        access_service=access_service,
        audio_store=audio_store,
        explanation_service=explanation_service,
        account_service=account_service,
        library_service=library_service,
        trusted_origins=selected.trusted_origins,
        trusted_proxy_networks=selected.trusted_proxy_networks,
        lifespan=lifespan,
        readiness_check=lambda: not resources.cleanup_failed.is_set(),
        metrics_snapshot=lambda: _metrics_snapshot(resources),
    )
    app.state.museecho_runtime = resources
    return app


def app() -> FastAPI:
    """Uvicorn factory entry point for the production container."""

    return create_runtime_app()


def _metrics_snapshot(resources: RuntimeResources) -> dict[str, object]:
    queue_length, active_analyses = resources.queue.metrics()
    return resources.metrics.snapshot(
        queue_length=queue_length,
        active_analyses=active_analyses,
    )


def _run_cleanup(
    resources: RuntimeResources,
    interval_seconds: float,
    account_service: AccountService | None = None,
) -> None:
    while not resources.cleanup_stop.wait(interval_seconds):
        try:
            resources.metrics.observe_cleanup(deleted=resources.cleanup.run_once())
            if account_service is not None:
                account_service.cleanup_expired()
            if resources.cleanup_failed.is_set():
                resources.cleanup_failed.clear()
                LOGGER.info("expiry cleanup recovered")
        except Exception:
            resources.metrics.observe_cleanup_failure()
            if not resources.cleanup_failed.is_set():
                LOGGER.error("expiry cleanup failed; readiness degraded")
                resources.cleanup_failed.set()


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
