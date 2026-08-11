from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from museecho.cli import create_default_secret_store
from museecho.infrastructure import secrets as secrets_module
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
    secret_path.chmod(stat.S_IREAD)
    try:
        store = FileSecretStore(secret_path, repository_root=repository_root)
        assert store.get() == "container-secret"
        with pytest.raises(ReadOnlySecretStoreError):
            store.set("replacement")
        with pytest.raises(ReadOnlySecretStoreError):
            store.clear()
    finally:
        secret_path.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.skipif(os.name != "posix", reason="POSIX mount permissions only")
def test_file_store_accepts_owner_readable_secret_on_read_only_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    secret_path = tmp_path / "mounted-secrets" / "provider-key"
    secret_path.parent.mkdir()
    secret_path.write_text("container-secret", encoding="utf-8")
    secret_path.chmod(0o444)
    monkeypatch.setattr(secrets_module, "_is_path_on_read_only_mount", lambda _path: True)

    assert FileSecretStore(secret_path, repository_root=repository_root).get() == "container-secret"


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
    secret_path.chmod(stat.S_IREAD)
    try:
        store = FileSecretStore(secret_path, repository_root=repository_root)
        with pytest.raises(ValueError, match="single line"):
            store.get()
    finally:
        secret_path.chmod(stat.S_IREAD | stat.S_IWRITE)

    secret_path.write_text("x" * 4097, encoding="utf-8")
    secret_path.chmod(stat.S_IREAD)
    try:
        store = FileSecretStore(secret_path, repository_root=repository_root)
        with pytest.raises(ValueError, match="too large"):
            store.get()
    finally:
        secret_path.chmod(stat.S_IREAD | stat.S_IWRITE)


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
    secret_path.chmod(stat.S_IREAD)

    try:
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
    finally:
        secret_path.chmod(stat.S_IREAD | stat.S_IWRITE)


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


def test_default_production_factory_reaches_external_file_backend(tmp_path: Path):
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    secret_path = tmp_path / "provider-key"
    secret_path.write_text("container-secret\n", encoding="utf-8")
    secret_path.chmod(stat.S_IREAD)
    try:
        store = create_default_secret_store(
            environ={"MUSEECHO_PROVIDER_SECRET_FILE": str(secret_path)},
            repository_root=repository_root,
        )
        assert isinstance(store, FileSecretStore)
        assert store.get() == "container-secret"
    finally:
        secret_path.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_file_store_rejects_writable_secret_file(tmp_path: Path):
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    secret_path = tmp_path / "provider-key"
    secret_path.write_text("writable-secret", encoding="utf-8")
    store = FileSecretStore(secret_path, repository_root=repository_root)

    with pytest.raises(ValueError, match="read-only"):
        store.get()


def test_file_store_rejects_symlink(tmp_path: Path):
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    target = tmp_path / "provider-key"
    target.write_text("secret", encoding="utf-8")
    link = tmp_path / "provider-key-link"
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("symlink creation is unavailable on this host")

    with pytest.raises(ValueError, match="symbolic link"):
        FileSecretStore(link, repository_root=repository_root)


def test_file_store_allows_one_trailing_newline_at_size_limit(tmp_path: Path):
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    secret_path = tmp_path / "provider-key"
    secret_path.write_text("x" * 4096 + "\n", encoding="utf-8")
    secret_path.chmod(stat.S_IREAD)
    try:
        store = FileSecretStore(secret_path, repository_root=repository_root)
        assert store.get() == "x" * 4096
    finally:
        secret_path.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_file_store_rejects_multiple_trailing_newlines(tmp_path: Path):
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    secret_path = tmp_path / "provider-key"
    secret_path.write_text("secret\n\n", encoding="utf-8")
    secret_path.chmod(stat.S_IREAD)
    try:
        store = FileSecretStore(secret_path, repository_root=repository_root)
        with pytest.raises(ValueError, match="single line"):
            store.get()
    finally:
        secret_path.chmod(stat.S_IREAD | stat.S_IWRITE)
