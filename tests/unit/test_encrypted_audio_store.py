from __future__ import annotations

import base64
import uuid
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest

from museecho.domain.models import EncryptedAudio
from museecho.infrastructure.audio_store import (
    HEADER_SIZE,
    ChunkedEncryptedAudioStore,
    DestroyedAudioKeyError,
    EncryptedAudioIntegrityError,
    KeyEncryptionKeyError,
)


class MemorySecretStore:
    source = "test-memory"

    def __init__(self, value: str | None) -> None:
        self.value = value

    @classmethod
    def for_key(cls, key: bytes) -> MemorySecretStore:
        return cls(base64.urlsafe_b64encode(key).decode("ascii"))

    def get(self) -> str | None:
        return self.value

    def set(self, value: str) -> None:
        self.value = value

    def clear(self) -> bool:
        existed = self.value is not None
        self.value = None
        return existed


class MemoryAudioRepository:
    def __init__(self) -> None:
        self.audio: dict[uuid.UUID, EncryptedAudio] = {}
        self.key_destroyed = False

    def save_encrypted_audio(self, audio: EncryptedAudio) -> None:
        self.audio[audio.analysis_id] = replace(audio)

    def get_encrypted_audio(self, analysis_id: uuid.UUID) -> EncryptedAudio | None:
        audio = self.audio.get(analysis_id)
        return None if audio is None else replace(audio)

    def destroy_encrypted_audio_key(self, analysis_id: uuid.UUID) -> None:
        self.key_destroyed = True
        self.audio.pop(analysis_id, None)


def _store(tmp_path: Path, repository: MemoryAudioRepository | None = None):
    repository = repository or MemoryAudioRepository()
    return (
        ChunkedEncryptedAudioStore(
            tmp_path / "ciphertext",
            key_store=MemorySecretStore.for_key(b"k" * 32),
            repository=repository,
            chunk_size=64,
        ),
        repository,
    )


def test_ciphertext_does_not_contain_plaintext_and_full_read_round_trips(tmp_path: Path):
    store, repository = _store(tmp_path)
    analysis_id = uuid.uuid4()
    plaintext = b"RIFF" + b"music" * 100

    metadata = store.write(analysis_id, BytesIO(plaintext), "audio/wav")

    ciphertext = Path(metadata.cipher_path).read_bytes()
    assert b"music" not in ciphertext
    assert metadata.wrapped_data_key not in ciphertext
    assert repository.audio[analysis_id] == metadata
    assert store.read_range(metadata, 0, len(plaintext)) == plaintext


def test_cross_chunk_and_empty_ranges_match_python_slice(tmp_path: Path):
    store, _ = _store(tmp_path)
    plaintext = bytes(range(256))
    metadata = store.write(uuid.uuid4(), BytesIO(plaintext), "audio/wav")

    assert store.read_range(metadata, 50, 150) == plaintext[50:150]
    assert store.read_range(metadata, 64, 128) == plaintext[64:128]
    assert store.read_range(metadata, 20, 20) == b""


def test_write_aggregates_legal_short_reads(tmp_path: Path):
    class ShortReadStream:
        def __init__(self, value: bytes) -> None:
            self._value = value
            self._offset = 0

        def read(self, size: int = -1) -> bytes:
            if self._offset >= len(self._value):
                return b""
            length = min(10, size, len(self._value) - self._offset)
            result = self._value[self._offset : self._offset + length]
            self._offset += length
            return result

    store, _ = _store(tmp_path)
    plaintext = bytes(range(200))

    metadata = store.write(uuid.uuid4(), ShortReadStream(plaintext), "audio/wav")

    assert store.read_range(metadata, 0, len(plaintext)) == plaintext


@pytest.mark.parametrize("start,end", [(-1, 1), (2, 1), (0, 257)])
def test_invalid_range_is_rejected(tmp_path: Path, start: int, end: int):
    store, _ = _store(tmp_path)
    metadata = store.write(uuid.uuid4(), BytesIO(bytes(range(256))), "audio/wav")

    with pytest.raises(ValueError, match="range"):
        store.read_range(metadata, start, end)


def test_tampered_ciphertext_fails_authentication(tmp_path: Path):
    store, _ = _store(tmp_path)
    metadata = store.write(uuid.uuid4(), BytesIO(b"a" * 160), "audio/wav")
    path = Path(metadata.cipher_path)
    ciphertext = bytearray(path.read_bytes())
    ciphertext[HEADER_SIZE + 10] ^= 1
    path.write_bytes(ciphertext)

    with pytest.raises(EncryptedAudioIntegrityError):
        store.read_range(metadata, 0, metadata.plaintext_size)


def test_swapped_chunks_fail_authentication(tmp_path: Path):
    store, _ = _store(tmp_path)
    metadata = store.write(uuid.uuid4(), BytesIO(b"a" * 64 + b"b" * 64), "audio/wav")
    path = Path(metadata.cipher_path)
    ciphertext = bytearray(path.read_bytes())
    record_size = metadata.chunk_size + 16
    first = ciphertext[HEADER_SIZE : HEADER_SIZE + record_size]
    second = ciphertext[HEADER_SIZE + record_size : HEADER_SIZE + 2 * record_size]
    ciphertext[HEADER_SIZE : HEADER_SIZE + record_size] = second
    ciphertext[HEADER_SIZE + record_size : HEADER_SIZE + 2 * record_size] = first
    path.write_bytes(ciphertext)

    with pytest.raises(EncryptedAudioIntegrityError):
        store.read_range(metadata, 0, metadata.plaintext_size)


def test_truncated_ciphertext_is_rejected_before_decryption(tmp_path: Path):
    store, _ = _store(tmp_path)
    metadata = store.write(uuid.uuid4(), BytesIO(b"audio" * 40), "audio/wav")
    path = Path(metadata.cipher_path)
    path.write_bytes(path.read_bytes()[:-1])

    with pytest.raises(EncryptedAudioIntegrityError):
        store.read_range(metadata, 0, metadata.plaintext_size)


def test_tampered_wrapped_key_is_rejected(tmp_path: Path):
    store, repository = _store(tmp_path)
    metadata = store.write(uuid.uuid4(), BytesIO(b"audio" * 40), "audio/wav")
    persisted = repository.audio[metadata.analysis_id]
    wrapped = bytearray(persisted.wrapped_data_key)
    wrapped[-1] ^= 1
    persisted.wrapped_data_key = bytes(wrapped)

    with pytest.raises(EncryptedAudioIntegrityError):
        store.read_range(metadata, 0, 1)


def test_delete_destroys_wrapped_key_before_removing_ciphertext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store, repository = _store(tmp_path)
    metadata = store.write(uuid.uuid4(), BytesIO(b"audio" * 40), "audio/wav")
    path = Path(metadata.cipher_path)
    original_unlink = Path.unlink

    def guarded_unlink(target: Path, *args, **kwargs):
        assert repository.key_destroyed
        return original_unlink(target, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", guarded_unlink)
    store.delete(metadata)

    assert metadata.wrapped_data_key == b""
    assert not path.exists()
    with pytest.raises(DestroyedAudioKeyError):
        store.read_range(metadata, 0, 1)


def test_key_destruction_failure_preserves_ciphertext_and_metadata_key(tmp_path: Path):
    class FailingDestroyRepository(MemoryAudioRepository):
        def destroy_encrypted_audio_key(self, analysis_id: uuid.UUID) -> None:
            raise RuntimeError("database unavailable")

    store, _ = _store(tmp_path, FailingDestroyRepository())
    metadata = store.write(uuid.uuid4(), BytesIO(b"audio" * 40), "audio/wav")
    original_key = metadata.wrapped_data_key
    path = Path(metadata.cipher_path)

    with pytest.raises(RuntimeError, match="database unavailable"):
        store.delete(metadata)

    assert path.exists()
    assert metadata.wrapped_data_key == original_key


def test_ciphertext_delete_failure_still_leaves_key_destroyed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store, repository = _store(tmp_path)
    metadata = store.write(uuid.uuid4(), BytesIO(b"audio" * 40), "audio/wav")
    stale_metadata = replace(metadata)
    path = Path(metadata.cipher_path)

    def fail_unlink(target: Path, *args, **kwargs):
        raise OSError("filesystem unavailable")

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    with pytest.raises(OSError, match="filesystem unavailable"):
        store.delete(metadata)

    assert repository.key_destroyed
    assert metadata.wrapped_data_key == b""
    assert path.exists()
    with pytest.raises(DestroyedAudioKeyError):
        store.read_range(stale_metadata, 0, stale_metadata.plaintext_size)


def test_write_failure_does_not_leave_ciphertext(tmp_path: Path):
    class FailingRepository(MemoryAudioRepository):
        def save_encrypted_audio(self, audio: EncryptedAudio) -> None:
            raise RuntimeError("database unavailable")

    store, _ = _store(tmp_path, FailingRepository())

    with pytest.raises(RuntimeError, match="database unavailable"):
        store.write(uuid.uuid4(), BytesIO(b"audio"), "audio/wav")

    assert list((tmp_path / "ciphertext").glob("*")) == []


def test_empty_audio_is_rejected_without_leaving_ciphertext(tmp_path: Path):
    store, repository = _store(tmp_path)

    with pytest.raises(ValueError, match="empty"):
        store.write(uuid.uuid4(), BytesIO(b""), "audio/wav")

    assert repository.audio == {}
    assert list((tmp_path / "ciphertext").glob("*")) == []


def test_retry_recovers_orphan_final_file_when_repository_has_no_metadata(tmp_path: Path):
    store, _ = _store(tmp_path)
    analysis_id = uuid.uuid4()
    root = tmp_path / "ciphertext"
    orphan = root / f"{analysis_id.hex}.meaf"
    orphan.write_bytes(b"partial-crash-file")
    plaintext = b"replacement-audio"

    metadata = store.write(analysis_id, BytesIO(plaintext), "audio/wav")

    assert store.read_range(metadata, 0, len(plaintext)) == plaintext


@pytest.mark.parametrize("secret", [None, "not-base64!", "c2hvcnQ="])
def test_missing_or_invalid_key_encryption_secret_is_rejected(tmp_path: Path, secret: str | None):
    repository = MemoryAudioRepository()
    store = ChunkedEncryptedAudioStore(
        tmp_path / "ciphertext",
        key_store=MemorySecretStore(secret),
        repository=repository,
        chunk_size=64,
    )

    with pytest.raises(KeyEncryptionKeyError, match="key encryption key"):
        store.write(uuid.uuid4(), BytesIO(b"audio"), "audio/wav")

    assert repository.audio == {}
    assert list((tmp_path / "ciphertext").glob("*")) == []
