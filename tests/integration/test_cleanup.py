from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

from museecho.application.access import AccessService
from museecho.application.cleanup import AnalysisDeletionService, ExpiryCleanup
from museecho.domain.models import EncryptedAudioMetadata
from museecho.domain.status import AnalysisJob
from museecho.infrastructure.audio_store import ChunkedEncryptedAudioStore
from museecho.infrastructure.db import create_session_factory
from museecho.infrastructure.repositories import SqliteAnalysisRepository, init_db


class MemorySecretStore:
    source = "test-memory"

    def __init__(self, key: bytes) -> None:
        self.value = base64.urlsafe_b64encode(key).decode("ascii")

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value

    def clear(self) -> bool:
        self.value = ""
        return True


def _expired_analysis(tmp_path: Path):
    database_url = f"sqlite:///{(tmp_path / 'museecho.db').as_posix()}"
    init_db(database_url)
    repository = SqliteAnalysisRepository(create_session_factory(database_url))
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    expires_at = created_at + timedelta(hours=24)
    job = AnalysisJob(
        id=uuid.uuid4(),
        created_at=created_at,
        updated_at=created_at,
        expires_at=expires_at,
    )
    repository.add(job)
    store = ChunkedEncryptedAudioStore(
        tmp_path / "ciphertext",
        key_store=MemorySecretStore(b"m" * 32),
        repository=repository,
        chunk_size=8,
    )
    metadata = store.write(job.id, BytesIO(b"private-audio"), "audio/wav")
    issued = AccessService(repository, clock=lambda: created_at).issue(job.id, expires_at)
    cleanup_time = expires_at + timedelta(seconds=1)
    return repository, store, metadata, issued.raw_token, cleanup_time


def test_expiry_cleanup_removes_access_ciphertext_and_rows_idempotently(tmp_path: Path):
    repository, store, metadata, _token, cleanup_time = _expired_analysis(tmp_path)
    deletion = AnalysisDeletionService(repository, store, clock=lambda: cleanup_time)
    cleanup = ExpiryCleanup(repository, deletion, clock=lambda: cleanup_time)

    assert cleanup.run_once() == 1
    assert cleanup.run_once() == 0
    assert repository.get(metadata.analysis_id) is None
    assert repository.get_encrypted_audio(metadata.analysis_id) is None
    assert not Path(metadata.cipher_path).exists()


def test_cleanup_retry_finishes_ciphertext_after_key_destruction_failure(tmp_path: Path):
    repository, store, metadata, token, cleanup_time = _expired_analysis(tmp_path)

    class FailAfterKeyDestruction:
        def read_range(self, metadata: EncryptedAudioMetadata, start: int, end: int) -> bytes:
            raise AssertionError("cleanup never reads audio")

        def write(self, *args, **kwargs):
            raise AssertionError("cleanup never writes audio")

        def delete(self, target: EncryptedAudioMetadata) -> None:
            prepared = repository.get_encrypted_audio(target.analysis_id)
            assert prepared is not None
            assert prepared.wrapped_data_key == b""
            raise OSError("simulated unlink failure")

    failing = AnalysisDeletionService(
        repository,
        FailAfterKeyDestruction(),  # type: ignore[arg-type]
        clock=lambda: cleanup_time,
    )
    failures: list[tuple[uuid.UUID, str]] = []
    assert (
        ExpiryCleanup(
            repository,
            failing,
            clock=lambda: cleanup_time,
            failure_observer=lambda analysis_id, code: failures.append((analysis_id, code)),
        ).run_once()
        == 0
    )
    assert failures == [(metadata.analysis_id, "cleanup_failed")]

    assert repository.get(metadata.analysis_id) is not None
    prepared = repository.get_encrypted_audio(metadata.analysis_id)
    assert prepared is not None
    assert prepared.wrapped_data_key == b""
    assert not AccessService(repository, clock=lambda: cleanup_time).authorize(
        metadata.analysis_id,
        token,
    )
    resumed = AnalysisDeletionService(repository, store, clock=lambda: cleanup_time)
    assert ExpiryCleanup(repository, resumed, clock=lambda: cleanup_time).run_once() == 1
    assert repository.get(metadata.analysis_id) is None
    assert not Path(metadata.cipher_path).exists()
