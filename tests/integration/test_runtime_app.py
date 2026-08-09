from __future__ import annotations

import base64
import os
import stat
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from museecho.domain.status import AnalysisJob
from museecho.runtime import RuntimeSettings, create_runtime_app


def _write_read_only_secret(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    path.chmod(stat.S_IREAD)
    return path


def _base_environment(tmp_path: Path) -> tuple[dict[str, str], Path]:
    repository_root = tmp_path / "checkout"
    repository_root.mkdir()
    key = base64.urlsafe_b64encode(b"k" * 32).decode("ascii")
    secret = _write_read_only_secret(tmp_path / "external" / "audio-kek", key)
    return (
        {
            "MUSEECHO_DATA_ROOT": str((tmp_path / "data").resolve()),
            "MUSEECHO_AUDIO_KEK_FILE": str(secret.resolve()),
            "MUSEECHO_TRUSTED_ORIGINS": "https://museecho.test",
        },
        repository_root,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"MUSEECHO_AUDIO_KEK_FILE": ""},
        {"MUSEECHO_TRUSTED_ORIGINS": "https://:8443"},
        {"MUSEECHO_TRUSTED_ORIGINS": "https://museecho.test:not-a-port"},
        {"MUSEECHO_PROVIDER_BASE_URL": "https://provider.example/v1"},
        {"MUSEECHO_PROVIDER_MODEL": "deepseek-v4-flash"},
        {"MUSEECHO_PROVIDER_SECRET_FILE": "C:/run/secrets/provider-key"},
    ],
)
def test_runtime_settings_reject_missing_or_partial_secret_configuration(
    tmp_path: Path,
    overrides: dict[str, str],
):
    environ, repository_root = _base_environment(tmp_path)
    environ.update(overrides)

    with pytest.raises(ValueError):
        RuntimeSettings.from_environment(environ, repository_root=repository_root)


def test_runtime_settings_reject_reusing_audio_key_as_provider_credential(tmp_path: Path):
    environ, repository_root = _base_environment(tmp_path)
    environ.update(
        {
            "MUSEECHO_PROVIDER_BASE_URL": "https://provider.example/v1",
            "MUSEECHO_PROVIDER_MODEL": "deepseek-v4-flash",
            "MUSEECHO_PROVIDER_SECRET_FILE": environ["MUSEECHO_AUDIO_KEK_FILE"],
        }
    )

    with pytest.raises(ValueError):
        RuntimeSettings.from_environment(environ, repository_root=repository_root)


def test_runtime_rejects_invalid_audio_key_before_reporting_ready(tmp_path: Path):
    environ, repository_root = _base_environment(tmp_path)
    secret = Path(environ["MUSEECHO_AUDIO_KEK_FILE"])
    secret.chmod(stat.S_IWRITE | stat.S_IREAD)
    secret.write_text("not-a-valid-key", encoding="utf-8")
    secret.chmod(stat.S_IREAD)
    settings = RuntimeSettings.from_environment(environ, repository_root=repository_root)

    with pytest.raises(ValueError):
        create_runtime_app(settings=settings)


def test_runtime_starts_upload_api_without_provider_and_deletes_expired_jobs(tmp_path: Path):
    environ, repository_root = _base_environment(tmp_path)
    environ["MUSEECHO_CLEANUP_INTERVAL_SECONDS"] = "0.05"
    settings = RuntimeSettings.from_environment(environ, repository_root=repository_root)
    app = create_runtime_app(settings=settings)
    runtime = app.state.museecho_runtime
    now = datetime.now(timezone.utc)
    expired = AnalysisJob(
        created_at=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
    )
    runtime.repository.add(expired)

    with TestClient(app, base_url="https://museecho.test") as client:
        assert client.get("/api/health").json() == {"status": "ready"}
        invalid = client.post(
            "/api/analyses",
            files={"file": ("notes.txt", b"not audio", "text/plain")},
        )
        assert invalid.status_code == 422
        deadline = time.monotonic() + 2.0
        while runtime.repository.get(expired.id) is not None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert runtime.repository.get(expired.id) is None

    assert (settings.data_root / "museecho.db").is_file()
    assert not any(
        thread.name.startswith("museecho-") and thread.is_alive()
        for thread in __import__("threading").enumerate()
    )
    assert os.access(settings.audio_kek_file, os.R_OK)
