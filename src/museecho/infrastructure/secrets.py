from __future__ import annotations

import os
import stat
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


class SecretStoreError(RuntimeError):
    pass


class ReadOnlySecretStoreError(SecretStoreError):
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
        try:
            value = self._backend.get_password(self._service, self._username)
        except Exception:
            raise SecretStoreError("Credential store operation failed.") from None
        if value is None:
            return None
        try:
            return _validate_secret(value)
        except ValueError:
            raise SecretStoreError("Stored provider secret is invalid.") from None

    def set(self, value: str) -> None:
        try:
            validated = _validate_secret(value)
        except ValueError as exc:
            raise SecretStoreError(str(exc)) from None
        try:
            self._backend.set_password(self._service, self._username, validated)
        except Exception:
            raise SecretStoreError("Credential store operation failed.") from None

    def clear(self) -> bool:
        if self.get() is None:
            return False
        try:
            self._backend.delete_password(self._service, self._username)
        except Exception:
            raise SecretStoreError("Credential store operation failed.") from None
        return True

    def __repr__(self) -> str:
        return f"KeyringSecretStore(service={self._service!r}, username={self._username!r})"


class FileSecretStore:
    def __init__(self, path: Path, *, repository_root: Path) -> None:
        if not path.is_absolute():
            raise ValueError("secret file path must be absolute")
        if path.is_symlink():
            raise ValueError("secret file cannot be a symbolic link")
        try:
            resolved_path = path.resolve(strict=True)
        except (OSError, UnicodeError):
            raise SecretStoreError("Secret file is unavailable.") from None
        resolved_repository = repository_root.resolve()
        self._assert_outside_repository(resolved_path, resolved_repository)
        self._path = resolved_path
        self._repository_root = resolved_repository

    @property
    def source(self) -> str:
        return "read-only-file"

    def get(self) -> str | None:
        descriptor: int | None = None
        try:
            current_path = self._path.resolve(strict=True)
            self._assert_outside_repository(current_path, self._repository_root)
            if current_path != self._path or self._path.is_symlink():
                raise ValueError("secret file cannot be a symbolic link")
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(self._path, flags)
            opened = os.fstat(descriptor)
            current = self._path.stat(follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError("secret file changed while opening")
            if not stat.S_ISREG(opened.st_mode):
                raise ValueError("secret file must be a regular file")
            writable_bits = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
            if opened.st_mode & writable_bits:
                raise ValueError("secret file must be read-only")
            if os.name == "posix" and opened.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
                raise ValueError("secret file permissions must be limited to its owner")
            with os.fdopen(descriptor, encoding="utf-8", closefd=True) as handle:
                descriptor = None
                value = handle.read(MAX_SECRET_LENGTH + 3)
        except (OSError, UnicodeError):
            raise SecretStoreError("Secret file is unavailable.") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)

        if value.endswith("\r\n"):
            value = value[:-2]
        elif value.endswith(("\n", "\r")):
            value = value[:-1]
        return _validate_secret(value)

    def set(self, value: str) -> None:
        raise ReadOnlySecretStoreError("file secret store is read-only")

    def clear(self) -> bool:
        raise ReadOnlySecretStoreError("file secret store is read-only")

    def __repr__(self) -> str:
        return f"FileSecretStore(path={self._path!s})"

    @staticmethod
    def _assert_outside_repository(path: Path, repository_root: Path) -> None:
        if path == repository_root or repository_root in path.parents:
            raise ValueError("secret file must be outside the repository")


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
