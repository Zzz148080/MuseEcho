from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TypeVar, cast

import click

from museecho.infrastructure.secrets import (
    ProviderSettings,
    SecretStore,
    SecretStoreError,
    resolve_secret_store,
)

SecretStoreFactory = Callable[[], SecretStore]
T = TypeVar("T")


def _safe_secret_operation(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except (SecretStoreError, ValueError) as exc:
        raise click.ClickException(str(exc)) from None


def _read_hidden_secret() -> str:
    value = cast(str, click.prompt("Provider API key", hide_input=True, type=str))
    if not value:
        raise click.ClickException("Secret cannot be empty.")
    return value


def create_app(store_factory: SecretStoreFactory) -> click.Group:
    @click.group()
    def app() -> None:
        """MuseEcho administrative commands."""

    @app.group()
    def secret() -> None:
        """Manage the provider API key without printing it."""

    @secret.command("status")
    def secret_status() -> None:
        store = _safe_secret_operation(store_factory)
        state = "configured" if _safe_secret_operation(store.get) is not None else "not configured"
        click.echo(f"Provider secret ({store.source}): {state}.")

    @secret.command("set")
    def secret_set() -> None:
        store = _safe_secret_operation(store_factory)
        if _safe_secret_operation(store.get) is not None:
            raise click.ClickException("Provider secret is already configured; use update.")
        value = _read_hidden_secret()
        _safe_secret_operation(lambda: store.set(value))
        click.echo("Provider secret configured.")

    @secret.command("update")
    def secret_update() -> None:
        store = _safe_secret_operation(store_factory)
        if _safe_secret_operation(store.get) is None:
            raise click.ClickException("Provider secret is not configured; use set.")
        value = _read_hidden_secret()
        _safe_secret_operation(lambda: store.set(value))
        click.echo("Provider secret updated.")

    @secret.command("clear")
    def secret_clear() -> None:
        store = _safe_secret_operation(store_factory)
        if _safe_secret_operation(store.clear):
            click.echo("Provider secret cleared.")
        else:
            click.echo("Provider secret was already not configured.")

    return app


def create_default_secret_store(
    *,
    environ: Mapping[str, str] | None = None,
    repository_root: Path | None = None,
) -> SecretStore:
    settings = ProviderSettings.from_environment(environ)
    root = repository_root or Path(__file__).resolve().parents[2]
    return resolve_secret_store(settings, repository_root=root)


app = create_app(create_default_secret_store)
