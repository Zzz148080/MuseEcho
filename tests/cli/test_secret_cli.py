from __future__ import annotations

import pytest
from click.testing import CliRunner

from museecho.cli import create_app


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
