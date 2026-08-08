from __future__ import annotations

from pathlib import Path

import pytest

from museecho.infrastructure.secrets import (
    FileSecretStore,
    KeyringSecretStore,
    ProviderSettings,
    ReadOnlySecretStoreError,
    resolve_secret_store,
)


class MemoryKeyringBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


def test_keyring_store_round_trips_updates_and_clears_without_exposing_value():
    backend = MemoryKeyringBackend()
    store = KeyringSecretStore(backend=backend)

    store.set("first-secret")
    assert store.get() == "first-secret"
    store.set("replacement-secret")
    assert store.get() == "replacement-secret"
    assert store.clear()
    assert store.get() is None
    assert not store.clear()
    assert "replacement-secret" not in repr(store)


def test_file_store_reads_external_secret_but_never_writes(tmp_path: Path):
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    secret_path = tmp_path / "mounted-secrets" / "provider-key"
    secret_path.parent.mkdir()
    secret_path.write_text("container-secret\n", encoding="utf-8")
    store = FileSecretStore(secret_path, repository_root=repository_root)

    assert store.get() == "container-secret"
    with pytest.raises(ReadOnlySecretStoreError):
        store.set("replacement")
    with pytest.raises(ReadOnlySecretStoreError):
        store.clear()


def test_file_store_rejects_repository_path(tmp_path: Path):
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    secret_path = repository_root / "secret"
    secret_path.write_text("must-not-load", encoding="utf-8")

    with pytest.raises(ValueError, match="outside"):
        FileSecretStore(secret_path, repository_root=repository_root)


def test_file_store_rejects_multiline_or_oversized_secret(tmp_path: Path):
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    secret_path = tmp_path / "provider-key"
    secret_path.write_text("first\nsecond", encoding="utf-8")
    store = FileSecretStore(secret_path, repository_root=repository_root)
    with pytest.raises(ValueError, match="single line"):
        store.get()

    secret_path.write_text("x" * 4097, encoding="utf-8")
    with pytest.raises(ValueError, match="too large"):
        store.get()


def test_resolver_rejects_ambiguous_or_missing_backend(tmp_path: Path):
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    secret_path = tmp_path / "provider-key"
    secret_path.write_text("secret", encoding="utf-8")

    with pytest.raises(ValueError, match="exactly one"):
        resolve_secret_store(
            ProviderSettings(use_keyring=True, secret_file=secret_path),
            repository_root=repository_root,
            keyring_backend=MemoryKeyringBackend(),
        )
    with pytest.raises(ValueError, match="exactly one"):
        resolve_secret_store(
            ProviderSettings(use_keyring=False, secret_file=None),
            repository_root=repository_root,
            keyring_backend=MemoryKeyringBackend(),
        )


def test_resolver_selects_explicit_backend(tmp_path: Path):
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    secret_path = tmp_path / "provider-key"
    secret_path.write_text("file-secret", encoding="utf-8")

    keyring_store = resolve_secret_store(
        ProviderSettings(use_keyring=True),
        repository_root=repository_root,
        keyring_backend=MemoryKeyringBackend(),
    )
    file_store = resolve_secret_store(
        ProviderSettings(use_keyring=False, secret_file=secret_path),
        repository_root=repository_root,
        keyring_backend=MemoryKeyringBackend(),
    )

    assert isinstance(keyring_store, KeyringSecretStore)
    assert isinstance(file_store, FileSecretStore)
    assert file_store.get() == "file-secret"


def test_provider_settings_reads_only_nonsecret_configuration():
    settings = ProviderSettings.from_environment(
        {
            "MUSEECHO_PROVIDER_BASE_URL": "https://provider.example/v1",
            "MUSEECHO_PROVIDER_MODEL": "deepseek-v4-flash",
            "MUSEECHO_PROVIDER_SECRET_FILE": "C:/run/secrets/provider-key",
        }
    )

    assert settings.base_url == "https://provider.example/v1"
    assert settings.model == "deepseek-v4-flash"
    assert settings.secret_file == Path("C:/run/secrets/provider-key")
    assert not settings.use_keyring
    assert "API_KEY" not in settings.__dataclass_fields__
