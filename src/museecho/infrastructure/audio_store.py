from __future__ import annotations

import base64
import binascii
import hashlib
import os
import secrets
import uuid
from contextlib import suppress
from pathlib import Path
from threading import RLock
from typing import BinaryIO, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from museecho.domain.models import EncryptedAudio
from museecho.infrastructure.crypto import (
    GCM_TAG_SIZE,
    HEADER_SIZE,
    NONCE_PREFIX_SIZE,
    build_header,
    chunk_aad,
    derive_nonce,
    parse_header,
    unwrap_data_key,
    wipe,
    wrap_data_key,
)
from museecho.infrastructure.secrets import SecretStore, SecretStoreError

MAX_CHUNK_SIZE = 8 * 1024 * 1024
PROCESS_LOCK_STRIPES = 256
_PROCESS_LOCKS = tuple(RLock() for _ in range(PROCESS_LOCK_STRIPES))


class EncryptedAudioIntegrityError(RuntimeError):
    pass


class DestroyedAudioKeyError(RuntimeError):
    pass


class KeyEncryptionKeyError(RuntimeError):
    pass


class AudioMetadataRepository(Protocol):
    def save_encrypted_audio(self, audio: EncryptedAudio) -> None: ...

    def get_encrypted_audio(self, analysis_id: uuid.UUID) -> EncryptedAudio | None: ...

    def destroy_encrypted_audio_key(self, analysis_id: uuid.UUID) -> None: ...


class ChunkedEncryptedAudioStore:
    def __init__(
        self,
        root: Path,
        *,
        key_store: SecretStore,
        repository: AudioMetadataRepository,
        chunk_size: int = 1024 * 1024,
    ) -> None:
        if not 0 < chunk_size <= MAX_CHUNK_SIZE:
            raise ValueError("chunk_size is outside the supported range")
        root.mkdir(parents=True, exist_ok=True)
        self._root = root.resolve()
        self._key_store = key_store
        self._repository = repository
        self._chunk_size = chunk_size

    def write(
        self,
        analysis_id: uuid.UUID,
        source: BinaryIO,
        media_type: str,
    ) -> EncryptedAudio:
        if not media_type:
            raise ValueError("media_type cannot be empty")

        with self._lock_for(analysis_id):
            return self._write_locked(analysis_id, source, media_type)

    def _write_locked(
        self,
        analysis_id: uuid.UUID,
        source: BinaryIO,
        media_type: str,
    ) -> EncryptedAudio:
        if self._repository.get_encrypted_audio(analysis_id) is not None:
            raise ValueError("encrypted audio already exists")

        target = self._path_for(analysis_id)
        self._remove_orphan_files(analysis_id, target)
        temporary = self._root / f".{analysis_id.hex}.{secrets.token_hex(8)}.tmp"
        data_key = bytearray(os.urandom(32))
        key_encryption_key = bytearray()
        nonce_prefix = os.urandom(NONCE_PREFIX_SIZE)
        plaintext_hash = hashlib.sha256()
        plaintext_size = 0
        chunk_count = 0
        installed_target = False
        try:
            key_encryption_key = self._load_key_encryption_key()
            wrapped_data_key = wrap_data_key(
                bytes(key_encryption_key), analysis_id, bytes(data_key)
            )
            with temporary.open("xb") as handle:
                os.chmod(temporary, 0o600)
                handle.write(build_header(analysis_id, self._chunk_size, nonce_prefix))
                cipher = AESGCM(bytes(data_key))
                while True:
                    chunk = self._read_plaintext_chunk(source)
                    if not chunk:
                        break
                    try:
                        if chunk_count >= 2**32:
                            raise ValueError("audio contains too many chunks")
                        plaintext_hash.update(chunk)
                        aad = chunk_aad(
                            analysis_id,
                            self._chunk_size,
                            chunk_count,
                            len(chunk),
                        )
                        encrypted = cipher.encrypt(
                            derive_nonce(nonce_prefix, chunk_count),
                            bytes(chunk),
                            aad,
                        )
                        handle.write(encrypted)
                        plaintext_size += len(chunk)
                        chunk_count += 1
                    finally:
                        wipe(chunk)
                if chunk_count == 0:
                    raise ValueError("audio source cannot be empty")
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(temporary, target)
            installed_target = True
            self._fsync_root()
            metadata = EncryptedAudio(
                analysis_id=analysis_id,
                cipher_path=str(target),
                wrapped_data_key=wrapped_data_key,
                chunk_size=self._chunk_size,
                chunk_count=chunk_count,
                plaintext_size=plaintext_size,
                media_type=media_type,
                sha256=plaintext_hash.hexdigest(),
            )
            self._repository.save_encrypted_audio(metadata)
            return metadata
        except Exception:
            self._unlink_without_masking(temporary)
            if installed_target:
                self._unlink_without_masking(target)
            raise
        finally:
            wipe(data_key)
            wipe(key_encryption_key)

    def read_range(self, metadata: EncryptedAudio, start: int, end: int) -> bytes:
        with self._lock_for(metadata.analysis_id):
            return self._read_range_locked(metadata.analysis_id, start, end)

    def _read_range_locked(self, analysis_id: uuid.UUID, start: int, end: int) -> bytes:
        metadata = self._authoritative_metadata(analysis_id)
        if not 0 <= start <= end <= metadata.plaintext_size:
            raise ValueError("range must satisfy 0 <= start <= end <= plaintext_size")
        self._validate_metadata(metadata)
        if start == end:
            self._assert_key_still_authoritative(metadata)
            return b""

        path = self._validated_path(metadata)
        expected_size = HEADER_SIZE + metadata.plaintext_size + metadata.chunk_count * GCM_TAG_SIZE
        key_encryption_key = self._load_key_encryption_key()
        result = bytearray()
        try:
            if path.stat().st_size != expected_size:
                raise EncryptedAudioIntegrityError("encrypted audio length mismatch")
            with path.open("rb") as handle:
                header_analysis_id, header_chunk_size, nonce_prefix = parse_header(
                    handle.read(HEADER_SIZE)
                )
                if (
                    header_analysis_id != metadata.analysis_id
                    or header_chunk_size != metadata.chunk_size
                ):
                    raise EncryptedAudioIntegrityError("encrypted audio header mismatch")
                data_key = bytearray(
                    unwrap_data_key(
                        bytes(key_encryption_key),
                        metadata.analysis_id,
                        metadata.wrapped_data_key,
                    )
                )
                try:
                    cipher = AESGCM(bytes(data_key))
                    first_chunk = start // metadata.chunk_size
                    last_chunk = (end - 1) // metadata.chunk_size
                    for chunk_index in range(first_chunk, last_chunk + 1):
                        plaintext_length = min(
                            metadata.chunk_size,
                            metadata.plaintext_size - chunk_index * metadata.chunk_size,
                        )
                        record_size = metadata.chunk_size + GCM_TAG_SIZE
                        handle.seek(HEADER_SIZE + chunk_index * record_size)
                        encrypted = handle.read(plaintext_length + GCM_TAG_SIZE)
                        if len(encrypted) != plaintext_length + GCM_TAG_SIZE:
                            raise EncryptedAudioIntegrityError("encrypted audio chunk is truncated")
                        plaintext = bytearray(
                            cipher.decrypt(
                                derive_nonce(nonce_prefix, chunk_index),
                                encrypted,
                                chunk_aad(
                                    metadata.analysis_id,
                                    metadata.chunk_size,
                                    chunk_index,
                                    plaintext_length,
                                ),
                            )
                        )
                        try:
                            chunk_start = chunk_index * metadata.chunk_size
                            slice_start = max(start - chunk_start, 0)
                            slice_end = min(end - chunk_start, plaintext_length)
                            result.extend(plaintext[slice_start:slice_end])
                        finally:
                            wipe(plaintext)
                finally:
                    wipe(data_key)

            if start == 0 and end == metadata.plaintext_size:
                if hashlib.sha256(result).hexdigest() != metadata.sha256:
                    raise EncryptedAudioIntegrityError("encrypted audio digest mismatch")
            self._assert_key_still_authoritative(metadata)
            return bytes(result)
        except DestroyedAudioKeyError:
            raise
        except EncryptedAudioIntegrityError:
            raise
        except (InvalidTag, OSError, ValueError):
            raise EncryptedAudioIntegrityError("encrypted audio authentication failed") from None
        finally:
            wipe(result)
            wipe(key_encryption_key)

    def delete(self, metadata: EncryptedAudio) -> None:
        with self._lock_for(metadata.analysis_id):
            authoritative = self._authoritative_metadata(metadata.analysis_id)
            path = self._validated_path(authoritative, require_exists=False)
            self._repository.destroy_encrypted_audio_key(metadata.analysis_id)
            wrapped_key = bytearray(metadata.wrapped_data_key)
            wipe(wrapped_key)
            metadata.wrapped_data_key = b""
            path.unlink(missing_ok=True)

    def _authoritative_metadata(self, analysis_id: uuid.UUID) -> EncryptedAudio:
        metadata = self._repository.get_encrypted_audio(analysis_id)
        if metadata is None or not metadata.wrapped_data_key:
            raise DestroyedAudioKeyError("encrypted audio key has been destroyed")
        return metadata

    def _assert_key_still_authoritative(self, metadata: EncryptedAudio) -> None:
        current = self._repository.get_encrypted_audio(metadata.analysis_id)
        if current is None or current.wrapped_data_key != metadata.wrapped_data_key:
            raise DestroyedAudioKeyError("encrypted audio key has been destroyed")

    def _load_key_encryption_key(self) -> bytearray:
        try:
            encoded = self._key_store.get()
        except SecretStoreError:
            raise KeyEncryptionKeyError("audio key encryption key is unavailable") from None
        if encoded is None:
            raise KeyEncryptionKeyError("audio key encryption key is unavailable")
        try:
            decoded = base64.b64decode(encoded, altchars=b"-_", validate=True)
        except (ValueError, binascii.Error, UnicodeEncodeError):
            raise KeyEncryptionKeyError("audio key encryption key is invalid") from None
        if len(decoded) != 32:
            raise KeyEncryptionKeyError("audio key encryption key is invalid")
        # Python strings and immutable bytes cannot be reliably zeroized. Keeping the
        # decoded key in a bytearray limits the lifetime of the mutable working copy.
        return bytearray(decoded)

    def _read_plaintext_chunk(self, source: BinaryIO) -> bytearray:
        chunk = bytearray()
        while len(chunk) < self._chunk_size:
            raw = source.read(self._chunk_size - len(chunk))
            if not raw:
                break
            if len(raw) > self._chunk_size - len(chunk):
                wipe(chunk)
                raise ValueError("source returned an oversized chunk")
            chunk.extend(raw)
        return chunk

    def _remove_orphan_files(self, analysis_id: uuid.UUID, target: Path) -> None:
        target.unlink(missing_ok=True)
        for temporary in self._root.glob(f".{analysis_id.hex}.*.tmp"):
            self._unlink_without_masking(temporary)

    @staticmethod
    def _unlink_without_masking(path: Path) -> None:
        with suppress(OSError):
            path.unlink(missing_ok=True)

    def _fsync_root(self) -> None:
        if os.name != "posix":
            return
        descriptor = os.open(self._root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _lock_for(self, analysis_id: uuid.UUID) -> RLock:
        # Locks are module-global so separate store instances in this process cannot
        # race plaintext delivery against crypto-erasure for the same storage root.
        identity = (os.path.normcase(str(self._root)), analysis_id.int)
        return _PROCESS_LOCKS[hash(identity) % len(_PROCESS_LOCKS)]

    def _path_for(self, analysis_id: uuid.UUID) -> Path:
        return self._root / f"{analysis_id.hex}.meaf"

    def _validated_path(self, metadata: EncryptedAudio, *, require_exists: bool = True) -> Path:
        expected = self._path_for(metadata.analysis_id)
        supplied = Path(metadata.cipher_path)
        try:
            resolved = supplied.resolve(strict=require_exists)
        except OSError:
            raise EncryptedAudioIntegrityError("encrypted audio path is unavailable") from None
        if resolved != expected:
            raise EncryptedAudioIntegrityError("encrypted audio path is invalid")
        return expected

    @staticmethod
    def _validate_metadata(metadata: EncryptedAudio) -> None:
        if metadata.chunk_size <= 0 or metadata.plaintext_size <= 0 or metadata.chunk_count <= 0:
            raise EncryptedAudioIntegrityError("encrypted audio metadata is inconsistent")
        expected_chunks = (metadata.plaintext_size + metadata.chunk_size - 1) // metadata.chunk_size
        if expected_chunks != metadata.chunk_count:
            raise EncryptedAudioIntegrityError("encrypted audio metadata is inconsistent")


__all__ = [
    "HEADER_SIZE",
    "ChunkedEncryptedAudioStore",
    "DestroyedAudioKeyError",
    "EncryptedAudioIntegrityError",
    "KeyEncryptionKeyError",
]
