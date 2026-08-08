from __future__ import annotations

import stat
from pathlib import Path

import pytest
from click.testing import CliRunner

from museecho.cli import create_app
from museecho.infrastructure.secrets import FileSecretStore, KeyringSecretStore


class MemorySecretStore:
    def __init__(self) -> None:
        self.value: str | None = None

    @property
    def source(self) -> str:
        return "test-memory"

    def get(self) -> str | None:
        return self.value

    def set(self, value: str) -> None:
        self.value = value

    def clear(self) -> bool:
        existed = self.value is not None
        self.value = None
        return existed


def test_status_never_prints_secret():
    store = MemorySecretStore()
    store.set("sk-test-value")
    app = create_app(lambda: store)

    result = CliRunner().invoke(app, ["secret", "status"])

    assert result.exit_code == 0
    assert "configured" in result.output
    assert "test-memory" in result.output
    assert "sk-test-value" not in result.output


def test_set_reads_hidden_prompt_and_never_echoes_secret(caplog: pytest.LogCaptureFixture):
    store = MemorySecretStore()
    app = create_app(lambda: store)

    result = CliRunner().invoke(app, ["secret", "set"], input="sk-new-value\n")

    assert result.exit_code == 0
    assert store.get() == "sk-new-value"
    assert "configured" in result.output
    assert "sk-new-value" not in result.output
    assert "sk-new-value" not in caplog.text


def test_set_refuses_to_overwrite_and_update_replaces_without_leaking():
    store = MemorySecretStore()
    store.set("old-secret")
    app = create_app(lambda: store)
    runner = CliRunner()

    refused = runner.invoke(app, ["secret", "set"], input="ignored-secret\n")
    updated = runner.invoke(app, ["secret", "update"], input="new-secret\n")

    assert refused.exit_code != 0
    assert store.get() == "new-secret"
    assert updated.exit_code == 0
    combined = refused.output + updated.output
    for value in ("old-secret", "ignored-secret", "new-secret"):
        assert value not in combined


def test_update_requires_existing_secret():
    store = MemorySecretStore()
    app = create_app(lambda: store)

    result = CliRunner().invoke(app, ["secret", "update"], input="unused-secret\n")

    assert result.exit_code != 0
    assert store.get() is None
    assert "unused-secret" not in result.output


def test_clear_removes_secret_and_status_reports_fallback():
    store = MemorySecretStore()
    store.set("secret-to-clear")
    app = create_app(lambda: store)
    runner = CliRunner()

    cleared = runner.invoke(app, ["secret", "clear"])
    status = runner.invoke(app, ["secret", "status"])

    assert cleared.exit_code == 0
    assert status.exit_code == 0
    assert "cleared" in cleared.output
    assert "not configured" in status.output
    assert "secret-to-clear" not in cleared.output + status.output


def test_keyring_backend_error_is_stable_and_never_leaks_prompted_secret():
    class LeakyKeyringBackend:
        def get_password(self, service: str, username: str) -> str | None:
            return None

        def set_password(self, service: str, username: str, password: str) -> None:
            raise RuntimeError(f"backend rejected {password}")

        def delete_password(self, service: str, username: str) -> None:
            raise RuntimeError("delete failed")

    store = KeyringSecretStore(backend=LeakyKeyringBackend())
    app = create_app(lambda: store)

    result = CliRunner().invoke(app, ["secret", "set"], input="sk-must-not-leak\n")

    assert result.exit_code != 0
    assert "credential store operation failed" in result.output.lower()
    assert "sk-must-not-leak" not in result.output
    assert "sk-must-not-leak" not in repr(result.exception)


def test_missing_file_backend_error_is_stable_and_hides_path(tmp_path: Path):
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    missing_path = tmp_path / "sensitive-path-name"
    app = create_app(lambda: FileSecretStore(missing_path, repository_root=repository_root))

    result = CliRunner().invoke(app, ["secret", "status"])

    assert result.exit_code != 0
    assert "secret file is unavailable" in result.output.lower()
    assert str(missing_path) not in result.output
    assert str(missing_path) not in repr(result.exception)


def test_invalid_utf8_file_error_never_leaks_raw_secret_bytes(tmp_path: Path):
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    secret_path = tmp_path / "provider-key"
    secret_path.write_bytes(b"sk-byte-leak\xff")
    secret_path.chmod(stat.S_IREAD)
    try:
        app = create_app(lambda: FileSecretStore(secret_path, repository_root=repository_root))
        result = CliRunner().invoke(app, ["secret", "status"])

        assert result.exit_code != 0
        assert "secret file is unavailable" in result.output.lower()
        assert "sk-byte-leak" not in result.output
        assert "sk-byte-leak" not in repr(result.exception)
    finally:
        secret_path.chmod(stat.S_IREAD | stat.S_IWRITE)
