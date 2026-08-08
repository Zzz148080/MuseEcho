from __future__ import annotations

from collections.abc import Callable
from typing import cast

import click

from museecho.infrastructure.secrets import KeyringSecretStore, SecretStore

SecretStoreFactory = Callable[[], SecretStore]


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
        store = store_factory()
        state = "configured" if store.get() is not None else "not configured"
        click.echo(f"Provider secret ({store.source}): {state}.")

    @secret.command("set")
    def secret_set() -> None:
        store = store_factory()
        if store.get() is not None:
            raise click.ClickException("Provider secret is already configured; use update.")
        store.set(_read_hidden_secret())
        click.echo("Provider secret configured.")

    @secret.command("update")
    def secret_update() -> None:
        store = store_factory()
        if store.get() is None:
            raise click.ClickException("Provider secret is not configured; use set.")
        store.set(_read_hidden_secret())
        click.echo("Provider secret updated.")

    @secret.command("clear")
    def secret_clear() -> None:
        store = store_factory()
        if store.clear():
            click.echo("Provider secret cleared.")
        else:
            click.echo("Provider secret was already not configured.")

    return app


app = create_app(KeyringSecretStore)
