from __future__ import annotations

import base64
import io
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from museecho.app import create_app
from museecho.application import coordinator as coordinator_module
from museecho.application.access import AccessService
from museecho.application.coordinator import AnalysisCoordinator, AnalysisInputUnavailableError
from museecho.application.explanations import ExplanationService
from museecho.application.queue import SingleWorkerQueue
from museecho.application.uploads import UploadSubmissionService
from museecho.audio_formats import AUDIO_FORMATS, AudioFormat
from museecho.domain.status import AnalysisJob, AnalysisStage, SourceKind
from museecho.infrastructure.audio_store import ChunkedEncryptedAudioStore
from museecho.infrastructure.db import create_session_factory
from museecho.infrastructure.repositories import SqliteAnalysisRepository, init_db
from tests.fixtures.audio_factory import write_chord_progression_wav


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


class _StopAfterMaterialization(Exception):
    pass


def _encrypted_pipeline_dependencies(tmp_path: Path):
    database_url = f"sqlite:///{(tmp_path / 'museecho.db').as_posix()}"
    init_db(database_url)
    repository = SqliteAnalysisRepository(create_session_factory(database_url))
    store = ChunkedEncryptedAudioStore(
        tmp_path / "ciphertext",
        key_store=MemorySecretStore(b"m" * 32),
        repository=repository,
        chunk_size=16,
    )
    return repository, store


def _add_real_job(repository: SqliteAnalysisRepository) -> uuid.UUID:
    now = datetime.now(timezone.utc)
    analysis_id = uuid.uuid4()
    repository.add(
        AnalysisJob(
            id=analysis_id,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(hours=24),
            source_kind=SourceKind.REAL,
        )
    )
    return analysis_id


@pytest.mark.parametrize("audio_format", AUDIO_FORMATS, ids=lambda item: item.suffix[1:])
def test_coordinator_materializes_encrypted_audio_with_registered_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    audio_format: AudioFormat,
):
    repository, store = _encrypted_pipeline_dependencies(tmp_path)
    analysis_id = _add_real_job(repository)
    plaintext = f"encrypted source for {audio_format.canonical_media_type}".encode()
    store.write(analysis_id, io.BytesIO(plaintext), audio_format.canonical_media_type)
    observed: list[tuple[str, bytes]] = []

    def inspect_decoder_input(path: Path, **_: object) -> None:
        observed.append((path.suffix, path.read_bytes()))
        raise _StopAfterMaterialization

    monkeypatch.setattr(coordinator_module, "decode_audio", inspect_decoder_input)

    with pytest.raises(_StopAfterMaterialization):
        AnalysisCoordinator(
            repository=repository,
            audio_store=store,
            temp_root=tmp_path / "analysis",
        )(analysis_id)

    assert observed == [(audio_format.suffix, plaintext)]


def test_coordinator_rejects_unknown_persisted_media_type_before_decoder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repository, store = _encrypted_pipeline_dependencies(tmp_path)
    analysis_id = _add_real_job(repository)
    store.write(analysis_id, io.BytesIO(b"encrypted source"), "audio/x-unknown")

    def fail_if_decoder_runs(*_: object, **__: object) -> None:
        pytest.fail("unknown persisted media type reached the decoder")

    monkeypatch.setattr(coordinator_module, "decode_audio", fail_if_decoder_runs)

    with pytest.raises(AnalysisInputUnavailableError, match="unsupported"):
        AnalysisCoordinator(
            repository=repository,
            audio_store=store,
            temp_root=tmp_path / "analysis",
        )(analysis_id)


def test_coordinator_startup_removes_only_owned_abandoned_plaintext(tmp_path: Path):
    temp_root = tmp_path / "analysis"
    stale = temp_root / ("museecho-analysis-" + "a" * 32 + "-deadbeef")
    stale.mkdir(parents=True)
    (stale / ".owner").write_bytes(b"MuseEcho analysis plaintext v1\n")
    (stale / "source.wav").write_bytes(b"private audio")
    unrelated = temp_root / "keep"
    unrelated.mkdir()
    (unrelated / "notes.txt").write_text("keep", encoding="utf-8")

    AnalysisCoordinator(
        repository=object(),  # type: ignore[arg-type]
        audio_store=object(),  # type: ignore[arg-type]
        temp_root=temp_root,
    )

    assert not stale.exists()
    assert (unrelated / "notes.txt").read_text(encoding="utf-8") == "keep"


def test_pipeline_persists_real_result_for_encrypted_wav(tmp_path: Path):
    database_url = f"sqlite:///{(tmp_path / 'museecho.db').as_posix()}"
    init_db(database_url)
    repository = SqliteAnalysisRepository(create_session_factory(database_url))
    store = ChunkedEncryptedAudioStore(
        tmp_path / "ciphertext",
        key_store=MemorySecretStore(b"m" * 32),
        repository=repository,
        chunk_size=1024,
    )
    now = datetime.now(timezone.utc)
    analysis_id = uuid.uuid4()
    repository.add(
        AnalysisJob(
            id=analysis_id,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(hours=24),
            source_kind=SourceKind.REAL,
        )
    )
    source_path = write_chord_progression_wav(tmp_path / "source.wav")
    with source_path.open("rb") as source:
        store.write(analysis_id, source, "audio/wav")

    observed: list[tuple[AnalysisStage, float]] = []
    ticks = iter(value for index in range(7) for value in (float(index), index + 0.25))
    AnalysisCoordinator(
        repository=repository,
        audio_store=store,
        temp_root=tmp_path / "analysis",
        stage_observer=lambda _analysis_id, stage, elapsed: observed.append((stage, elapsed)),
        timer=lambda: next(ticks),
    )(analysis_id)

    job = repository.get(analysis_id)
    track = repository.get_result(analysis_id)
    assert job is not None
    assert job.status is AnalysisStage.COMPLETE
    assert job.source_kind is SourceKind.REAL
    assert job.pipeline_version == "museecho-analysis-v1"
    assert track is not None
    assert track.duration_seconds == 4.0
    assert track.summary_json is not None
    assert track.summary_json["source_kind"] == "real"
    assert repository.get_evidence(analysis_id)
    assert [stage for stage, _elapsed in observed] == [
        AnalysisStage.VALIDATING,
        AnalysisStage.DECODING,
        AnalysisStage.RHYTHM,
        AnalysisStage.TONALITY,
        AnalysisStage.STRUCTURE,
        AnalysisStage.CHORDS,
        AnalysisStage.EVIDENCE,
    ]
    assert [elapsed for _stage, elapsed in observed] == [0.25] * 7

    AnalysisCoordinator(
        repository=repository,
        audio_store=store,
        temp_root=tmp_path / "analysis",
    )(analysis_id)
    assert repository.get_result(analysis_id) == track


def test_upload_worker_and_result_api_form_a_real_refreshable_loop(tmp_path: Path):
    database_url = f"sqlite:///{(tmp_path / 'museecho.db').as_posix()}"
    init_db(database_url)
    repository = SqliteAnalysisRepository(create_session_factory(database_url))
    store = ChunkedEncryptedAudioStore(
        tmp_path / "ciphertext",
        key_store=MemorySecretStore(b"m" * 32),
        repository=repository,
        chunk_size=1024,
    )
    access_service = AccessService(repository)
    coordinator = AnalysisCoordinator(
        repository=repository,
        audio_store=store,
        temp_root=tmp_path / "analysis",
    )
    queue = SingleWorkerQueue(repository, coordinator)
    upload_service = UploadSubmissionService(
        repository=repository,
        audio_store=store,
        access_service=access_service,
        queue=queue,
        temp_root=tmp_path / "uploads",
    )
    app = create_app(
        upload_service=upload_service,
        repository=repository,
        access_service=access_service,
        audio_store=store,
        explanation_service=ExplanationService(None),
        trusted_origins={"https://museecho.test"},
    )
    fixture = write_chord_progression_wav(tmp_path / "fixture.wav")

    with TestClient(app, base_url="https://museecho.test") as client:
        created = client.post(
            "/api/analyses",
            files={"file": ("fixture.wav", fixture.read_bytes(), "audio/wav")},
        )
        assert created.status_code == 202
        assert queue.wait_for_idle(timeout=30.0)
        analysis_id = created.json()["analysis_id"]

        status = client.get(f"/api/analyses/{analysis_id}/status")
        result = client.get(f"/api/analyses/{analysis_id}")

    assert queue.stop()
    assert status.status_code == 200
    assert status.json()["stage"] == "complete"
    assert result.status_code == 200
    assert result.json()["source_kind"] == "real"
    assert result.json()["pipeline_version"] == "museecho-analysis-v1"
    assert result.json()["evidence"]
