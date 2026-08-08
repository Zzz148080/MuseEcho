from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pytest

from museecho.domain.status import AnalysisJob, AnalysisStage, SourceKind
from museecho.infrastructure.audio_store import ChunkedEncryptedAudioStore, DestroyedAudioKeyError
from museecho.infrastructure.db import create_session_factory
from museecho.infrastructure.repositories import SqliteAnalysisRepository, init_db


def test_sqlite_metadata_range_read_and_crypto_erasure(tmp_path: Path):
    database_url = f"sqlite:///{(tmp_path / 'museecho.db').as_posix()}"
    init_db(database_url)
    repository = SqliteAnalysisRepository(create_session_factory(database_url))
    now = datetime.now(timezone.utc)
    analysis_id = uuid.uuid4()
    repository.add(
        AnalysisJob(
            id=analysis_id,
            stage=AnalysisStage.QUEUED,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(hours=24),
            pipeline_version="task-5",
            source_kind=SourceKind.SYNTHETIC_TEST,
        )
    )
    plaintext = bytes(range(256)) * 4
    store = ChunkedEncryptedAudioStore(
        tmp_path / "ciphertext",
        kek=b"m" * 32,
        repository=repository,
        chunk_size=128,
    )

    metadata = store.write(analysis_id, BytesIO(plaintext), "audio/wav")
    persisted = repository.get_encrypted_audio(analysis_id)
    assert persisted is not None
    assert store.read_range(persisted, 100, 600) == plaintext[100:600]

    store.delete(persisted)

    assert repository.get_encrypted_audio(analysis_id) is None
    assert not Path(metadata.cipher_path).exists()
    with pytest.raises(DestroyedAudioKeyError):
        store.read_range(persisted, 0, 1)
