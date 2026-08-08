from __future__ import annotations

import hashlib
import math
import os
import uuid
from pathlib import Path
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

MAX_CHUNK_SIZE = 8 * 1024 * 1024


class EncryptedAudioIntegrityError(RuntimeError):
    pass


class DestroyedAudioKeyError(RuntimeError):
    pass


class AudioMetadataRepository(Protocol):
    def save_encrypted_audio(self, audio: EncryptedAudio) -> None: ...

    def destroy_encrypted_audio_key(self, analysis_id: uuid.UUID) -> None: ...


class ChunkedEncryptedAudioStore:
    def __init__(
        self,
        root: Path,
        *,
        kek: bytes,
        repository: AudioMetadataRepository,
        chunk_size: int = 1024 * 1024,
    ) -> None:
        if len(kek) != 32:
            raise ValueError("KEK must be 32 bytes")
        if not 0 < chunk_size <= MAX_CHUNK_SIZE:
            raise ValueError("chunk_size is outside the supported range")
        root.mkdir(parents=True, exist_ok=True)
        self._root = root.resolve()
        self._kek = kek
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
        target = self._path_for(analysis_id)
        data_key = bytearray(os.urandom(32))
        nonce_prefix = os.urandom(NONCE_PREFIX_SIZE)
        plaintext_hash = hashlib.sha256()
        plaintext_size = 0
        chunk_count = 0
        wrapped_data_key = wrap_data_key(self._kek, analysis_id, bytes(data_key))
        try:
            with target.open("xb") as handle:
                os.chmod(target, 0o600)
                handle.write(build_header(analysis_id, self._chunk_size, nonce_prefix))
                cipher = AESGCM(bytes(data_key))
                while True:
                    raw_chunk = source.read(self._chunk_size)
                    if not raw_chunk:
                        break
                    if len(raw_chunk) > self._chunk_size:
                        raise ValueError("source returned an oversized chunk")
                    if chunk_count >= 2**32:
                        raise ValueError("audio contains too many chunks")
                    chunk = bytearray(raw_chunk)
                    try:
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
            target.unlink(missing_ok=True)
            raise
        finally:
            wipe(data_key)

    def read_range(self, metadata: EncryptedAudio, start: int, end: int) -> bytes:
        if not 0 <= start <= end <= metadata.plaintext_size:
            raise ValueError("range must satisfy 0 <= start <= end <= plaintext_size")
        if not metadata.wrapped_data_key:
            raise DestroyedAudioKeyError("encrypted audio key has been destroyed")
        self._validate_metadata(metadata)
        if start == end:
            return b""

        path = self._validated_path(metadata)
        expected_size = HEADER_SIZE + metadata.plaintext_size + metadata.chunk_count * GCM_TAG_SIZE
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
                    unwrap_data_key(self._kek, metadata.analysis_id, metadata.wrapped_data_key)
                )
                try:
                    cipher = AESGCM(bytes(data_key))
                    first_chunk = start // metadata.chunk_size
                    last_chunk = (end - 1) // metadata.chunk_size
                    result = bytearray()
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
                    value = bytes(result)
                    if start == 0 and end == metadata.plaintext_size:
                        if hashlib.sha256(value).hexdigest() != metadata.sha256:
                            raise EncryptedAudioIntegrityError("encrypted audio digest mismatch")
                    return value
                finally:
                    wipe(data_key)
        except DestroyedAudioKeyError:
            raise
        except EncryptedAudioIntegrityError:
            raise
        except (InvalidTag, OSError, ValueError):
            raise EncryptedAudioIntegrityError("encrypted audio authentication failed") from None

    def delete(self, metadata: EncryptedAudio) -> None:
        path = self._validated_path(metadata, require_exists=False)
        self._repository.destroy_encrypted_audio_key(metadata.analysis_id)
        wrapped_key = bytearray(metadata.wrapped_data_key)
        wipe(wrapped_key)
        metadata.wrapped_data_key = b""
        path.unlink(missing_ok=True)

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
        expected_chunks = math.ceil(metadata.plaintext_size / metadata.chunk_size)
        if expected_chunks != metadata.chunk_count or metadata.chunk_count <= 0:
            raise EncryptedAudioIntegrityError("encrypted audio metadata is inconsistent")


__all__ = [
    "HEADER_SIZE",
    "ChunkedEncryptedAudioStore",
    "DestroyedAudioKeyError",
    "EncryptedAudioIntegrityError",
]
