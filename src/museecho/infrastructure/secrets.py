from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

MAX_SECRET_LENGTH = 4096
KEYRING_SERVICE = "MuseEcho"
KEYRING_USERNAME = "provider-api-key"


class SecretStore(Protocol):
    @property
    def source(self) -> str: ...

    def get(self) -> str | None: ...

    def set(self, value: str) -> None: ...

    def clear(self) -> bool: ...


class KeyringBackend(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...

    def delete_password(self, service: str, username: str) -> None: ...


class ReadOnlySecretStoreError(RuntimeError):
    pass


def _validate_secret(value: str) -> str:
    if not value:
        raise ValueError("secret cannot be empty")
    if len(value) > MAX_SECRET_LENGTH:
        raise ValueError("secret is too large")
    if "\n" in value or "\r" in value:
        raise ValueError("secret must be a single line")
    return value


class KeyringSecretStore:
    def __init__(
        self,
        *,
        backend: KeyringBackend | None = None,
        service: str = KEYRING_SERVICE,
        username: str = KEYRING_USERNAME,
    ) -> None:
        if backend is None:
            import keyring

            backend = keyring
        self._backend = backend
        self._service = service
        self._username = username

    @property
    def source(self) -> str:
        return "os-keyring"

    def get(self) -> str | None:
        value = self._backend.get_password(self._service, self._username)
        return None if value is None else _validate_secret(value)

    def set(self, value: str) -> None:
        self._backend.set_password(self._service, self._username, _validate_secret(value))

    def clear(self) -> bool:
        if self.get() is None:
            return False
        self._backend.delete_password(self._service, self._username)
        return True

    def __repr__(self) -> str:
        return f"KeyringSecretStore(service={self._service!r}, username={self._username!r})"


class FileSecretStore:
    def __init__(self, path: Path, *, repository_root: Path) -> None:
        if not path.is_absolute():
            raise ValueError("secret file path must be absolute")
        resolved_path = path.resolve()
        resolved_repository = repository_root.resolve()
        if resolved_path == resolved_repository or resolved_repository in resolved_path.parents:
            raise ValueError("secret file must be outside the repository")
        self._path = resolved_path

    @property
    def source(self) -> str:
        return "read-only-file"

    def get(self) -> str | None:
        with self._path.open(encoding="utf-8") as handle:
            value = handle.read(MAX_SECRET_LENGTH + 1)
        if len(value) > MAX_SECRET_LENGTH:
            raise ValueError("secret is too large")
        value = value.rstrip("\r\n")
        return _validate_secret(value)

    def set(self, value: str) -> None:
        raise ReadOnlySecretStoreError("file secret store is read-only")

    def clear(self) -> bool:
        raise ReadOnlySecretStoreError("file secret store is read-only")

    def __repr__(self) -> str:
        return f"FileSecretStore(path={self._path!s})"


@dataclass(frozen=True)
class ProviderSettings:
    base_url: str | None = None
    model: str | None = None
    use_keyring: bool = True
    secret_file: Path | None = None

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> ProviderSettings:
        values = os.environ if environ is None else environ
        secret_file_value = values.get("MUSEECHO_PROVIDER_SECRET_FILE", "").strip()
        return cls(
            base_url=values.get("MUSEECHO_PROVIDER_BASE_URL") or None,
            model=values.get("MUSEECHO_PROVIDER_MODEL") or None,
            use_keyring=not secret_file_value,
            secret_file=Path(secret_file_value) if secret_file_value else None,
        )


def resolve_secret_store(
    settings: ProviderSettings,
    *,
    repository_root: Path,
    keyring_backend: KeyringBackend | None = None,
) -> SecretStore:
    selected_backends = int(settings.use_keyring) + int(settings.secret_file is not None)
    if selected_backends != 1:
        raise ValueError("configure exactly one secret backend")
    if settings.use_keyring:
        return KeyringSecretStore(backend=keyring_backend)
    assert settings.secret_file is not None
    return FileSecretStore(settings.secret_file, repository_root=repository_root)
