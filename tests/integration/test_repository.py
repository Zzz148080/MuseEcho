from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from museecho.application.access import AccessService
from museecho.domain.models import (
    AccessGrant,
    AnalysisResult,
    ChordEvent,
    EncryptedAudio,
    Evidence,
    Explanation,
    SectionEvent,
    TimeSeries,
    TrackAnalysis,
)
from museecho.domain.status import AnalysisJob, AnalysisStage, SourceKind
from museecho.infrastructure.db import create_session_factory
from museecho.infrastructure.repositories import (
    AccessGrantModel,
    AnalysisJobModel,
    ChordEventModel,
    EncryptedAudioModel,
    EvidenceModel,
    ExplanationModel,
    SectionEventModel,
    SqliteAnalysisRepository,
    TimeSeriesModel,
    TrackAnalysisModel,
    init_db,
)


def _database(tmp_path):
    database_path = tmp_path / "nested" / "museecho.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    init_db(database_url)
    factory = create_session_factory(database_url)
    return database_path, factory, SqliteAnalysisRepository(factory)


def _job() -> AnalysisJob:
    now = datetime.now(timezone.utc)
    return AnalysisJob(
        id=uuid.uuid4(),
        stage=AnalysisStage.QUEUED,
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(hours=24),
        pipeline_version="cold-start-review",
        source_kind=SourceKind.SYNTHETIC_TEST,
    )


def _track(analysis_id: uuid.UUID, duration: float = 12.0) -> TrackAnalysis:
    return TrackAnalysis(
        analysis_id=analysis_id,
        duration_seconds=duration,
        sample_rate=44_100,
        channels=2,
        bpm=120.0,
        bpm_confidence=0.9,
        key_tonic="C",
        mode="major",
        key_confidence=0.8,
        time_signature="4/4",
        time_signature_confidence=0.95,
        summary_json={"source": "synthetic_test"},
    )


def _result(analysis_id: uuid.UUID) -> AnalysisResult:
    return AnalysisResult(
        track=_track(analysis_id),
        sections=(SectionEvent(uuid.uuid4(), analysis_id, 0.0, 6.0, "A", 0.8, "test"),),
        chords=(
            ChordEvent(
                uuid.uuid4(),
                analysis_id,
                0.0,
                2.0,
                "C",
                0.9,
                "test",
                {"pitch_classes": ["C", "E", "G"]},
            ),
        ),
        time_series=(TimeSeries(analysis_id, "energy", 0.5, [0.1, 0.4], "rms"),),
        evidence=(
            Evidence(
                uuid.uuid4(),
                analysis_id,
                "chord",
                0.0,
                2.0,
                {"symbol": "C"},
                0.9,
                "test",
                True,
            ),
        ),
    )


def _advance_to_evidence(job: AnalysisJob) -> None:
    for stage in (
        AnalysisStage.VALIDATING,
        AnalysisStage.DECODING,
        AnalysisStage.RHYTHM,
        AnalysisStage.TONALITY,
        AnalysisStage.STRUCTURE,
        AnalysisStage.CHORDS,
        AnalysisStage.EVIDENCE,
    ):
        job.advance_to(stage)


def test_repository_creates_parent_directory_and_round_trips_utc_job(tmp_path):
    database_path, _, repository = _database(tmp_path)
    job = _job()

    repository.add(job)
    loaded = repository.get(job.id)

    assert database_path.is_file()
    assert loaded == job
    assert loaded is not None
    assert loaded.created_at.tzinfo == timezone.utc
    assert loaded.expires_at is not None
    assert loaded.expires_at.tzinfo == timezone.utc


def test_repository_updates_a_job_after_a_legal_transition(tmp_path):
    _, _, repository = _database(tmp_path)
    job = _job()
    repository.add(job)
    job.advance_to(AnalysisStage.VALIDATING)

    repository.update(job)

    assert repository.get(job.id) == job


def test_every_file_sqlite_connection_enables_foreign_keys_and_wal(tmp_path):
    _, factory, _ = _database(tmp_path)

    with factory() as session:
        foreign_keys = session.execute(text("PRAGMA foreign_keys")).scalar_one()
        journal_mode = session.execute(text("PRAGMA journal_mode")).scalar_one()

    assert foreign_keys == 1
    assert journal_mode == "wal"


def test_alembic_creates_the_exact_fresh_schema_and_is_clean(tmp_path):
    database_path = tmp_path / "fresh" / "museecho.db"
    config = Config("alembic.ini")
    database_url = f"sqlite:///{database_path.as_posix()}"
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")
    command.check(config)

    factory = create_session_factory(database_url)
    actual = set(inspect(factory.kw["bind"]).get_table_names())
    assert actual == {
        "access_grants",
        "alembic_version",
        "analysis_jobs",
        "chord_events",
        "encrypted_audio",
        "evidence",
        "explanations",
        "section_events",
        "time_series",
        "track_analyses",
    }


def test_repository_saves_result_aggregate_and_completion_atomically(tmp_path):
    _, _, repository = _database(tmp_path)
    job = _job()
    repository.add(job)
    _advance_to_evidence(job)
    repository.update(job)
    result = _result(job.id)

    repository.save_result(result)

    assert repository.get_result(job.id) == result.track
    assert repository.get_sections(job.id) == list(result.sections)
    assert repository.get_chords(job.id) == list(result.chords)
    assert repository.get_timeseries(job.id, "energy") == list(result.time_series)
    assert repository.get_evidence(job.id) == list(result.evidence)
    completed = repository.get(job.id)
    assert completed is not None
    assert completed.status is AnalysisStage.COMPLETE
    assert completed.progress == 1.0


def test_result_failure_rolls_back_children_track_and_completion(tmp_path):
    _, _, repository = _database(tmp_path)
    job = _job()
    repository.add(job)
    _advance_to_evidence(job)
    repository.update(job)
    duplicate_id = uuid.uuid4()
    invalid = AnalysisResult(
        track=_track(job.id),
        sections=(
            SectionEvent(duplicate_id, job.id, 0.0, 1.0, "A", 0.8, "test"),
            SectionEvent(duplicate_id, job.id, 1.0, 2.0, "B", 0.8, "test"),
        ),
    )

    with pytest.raises(IntegrityError):
        repository.save_result(invalid)

    assert repository.get_result(job.id) is None
    assert repository.get_sections(job.id) == []
    unchanged = repository.get(job.id)
    assert unchanged is not None
    assert unchanged.status is AnalysisStage.EVIDENCE


def test_result_cannot_skip_pipeline_stages(tmp_path):
    _, _, repository = _database(tmp_path)
    job = _job()
    repository.add(job)

    with pytest.raises(ValueError, match="queued"):
        repository.save_result(_result(job.id))

    assert repository.get_result(job.id) is None
    assert repository.get(job.id) == job


def test_result_is_revalidated_at_transaction_boundary(tmp_path):
    _, _, repository = _database(tmp_path)
    job = _job()
    repository.add(job)
    _advance_to_evidence(job)
    repository.update(job)
    result = _result(job.id)
    result.chords[0].end_seconds = result.track.duration_seconds + 1.0

    with pytest.raises(ValueError, match="duration"):
        repository.save_result(result)

    assert repository.get_result(job.id) is None
    assert repository.get(job.id) is not None
    assert repository.get(job.id).status is AnalysisStage.EVIDENCE  # type: ignore[union-attr]


def test_mutated_nested_non_finite_json_is_rejected_and_rolled_back(tmp_path):
    _, _, repository = _database(tmp_path)
    job = _job()
    repository.add(job)
    _advance_to_evidence(job)
    repository.update(job)
    result = _result(job.id)
    assert result.track.summary_json is not None
    result.track.summary_json["nested"] = {"value": float("nan")}

    with pytest.raises(ValueError, match="JSON"):
        repository.save_result(result)

    assert repository.get_result(job.id) is None
    unchanged = repository.get(job.id)
    assert unchanged is not None
    assert unchanged.status is AnalysisStage.EVIDENCE


def test_repository_round_trips_access_and_encrypted_audio(tmp_path):
    _, _, repository = _database(tmp_path)
    job = _job()
    repository.add(job)
    grant = AccessGrant(
        job.id,
        "a" * 64,
        job.created_at,
        job.created_at + timedelta(hours=1),
        None,
    )
    audio = EncryptedAudio(job.id, "cipher.bin", b"wrapped", 1024, 2, 1500, "audio/wav", "b" * 64)

    repository.save_access_grant(grant)
    repository.save_encrypted_audio(audio)

    assert repository.get_access_grants(job.id) == [grant]
    assert repository.get_encrypted_audio(job.id) == audio


def test_access_service_with_sqlite_persists_only_hash_and_authorizes(tmp_path):
    _, _, repository = _database(tmp_path)
    job = _job()
    repository.add(job)
    service = AccessService(repository, clock=lambda: job.created_at)

    issued = service.issue(job.id, job.created_at + timedelta(hours=1))

    stored = repository.get_access_grants(job.id)
    assert len(stored) == 1
    assert stored[0].token_hash.startswith("$argon2id$")
    assert stored[0].token_hash != issued.raw_token
    assert service.authorize(job.id, issued.raw_token)


def test_access_service_with_sqlite_replaces_previous_capability(tmp_path):
    _, _, repository = _database(tmp_path)
    job = _job()
    repository.add(job)
    service = AccessService(repository, clock=lambda: job.created_at)

    previous = service.issue(job.id, job.created_at + timedelta(hours=1))
    current = service.issue(job.id, job.created_at + timedelta(hours=1))

    stored = repository.get_access_grants(job.id)
    assert len(stored) == 1
    assert not service.authorize(job.id, previous.raw_token)
    assert service.authorize(job.id, current.raw_token)


def test_explanation_cannot_exceed_saved_track_duration(tmp_path):
    _, _, repository = _database(tmp_path)
    job = _job()
    repository.add(job)
    _advance_to_evidence(job)
    repository.update(job)
    repository.save_result(AnalysisResult(track=_track(job.id, duration=4.0)))
    explanation = Explanation(
        uuid.uuid4(),
        job.id,
        3.0,
        5.0,
        "0" * 64,
        [],
        "fallback",
        "outside track",
        datetime.now(timezone.utc),
    )

    with pytest.raises(ValueError, match="duration"):
        repository.add_explanation(explanation)
    assert repository.get_explanations(job.id) == []


def test_database_rejects_status_stage_divergence(tmp_path):
    _, factory, repository = _database(tmp_path)
    job = _job()
    repository.add(job)

    with pytest.raises(IntegrityError), factory() as session:
        session.execute(
            text("UPDATE analysis_jobs SET status='failed' WHERE id=:id"),
            {"id": str(job.id)},
        )
        session.commit()


def test_database_cascade_removes_every_child_table(tmp_path):
    _, factory, repository = _database(tmp_path)
    job = _job()
    repository.add(job)
    _advance_to_evidence(job)
    repository.update(job)
    result = _result(job.id)
    repository.save_result(result)
    repository.save_access_grant(
        AccessGrant(job.id, "a" * 64, job.created_at, job.created_at + timedelta(hours=1), None)
    )
    repository.save_encrypted_audio(
        EncryptedAudio(job.id, "cipher.bin", b"wrapped", 1024, 2, 1500, "audio/wav", "b" * 64)
    )
    repository.add_explanation(
        Explanation(
            uuid.uuid4(),
            job.id,
            0.0,
            1.0,
            "0" * 64,
            [str(result.evidence[0].id)],
            "fallback",
            "evidence",
            datetime.now(timezone.utc),
        )
    )

    repository.delete_cascade(job.id)

    models = (
        AnalysisJobModel,
        AccessGrantModel,
        EncryptedAudioModel,
        TrackAnalysisModel,
        SectionEventModel,
        ChordEventModel,
        TimeSeriesModel,
        EvidenceModel,
        ExplanationModel,
    )
    with factory() as session:
        counts = [session.scalar(select(func.count()).select_from(model)) for model in models]
    assert counts == [0] * len(models)


def test_repository_lists_only_active_jobs_in_creation_order(tmp_path):
    _, _, repository = _database(tmp_path)
    base = datetime.now(timezone.utc)

    def job_at(offset: int) -> AnalysisJob:
        created_at = base + timedelta(seconds=offset)
        return AnalysisJob(
            created_at=created_at,
            updated_at=created_at,
            expires_at=created_at + timedelta(hours=24),
        )

    queued = job_at(0)
    validating = job_at(1)
    failed = job_at(2)
    complete = job_at(3)
    for job in (queued, validating, failed, complete):
        repository.add(job)
    validating.advance_to(AnalysisStage.VALIDATING)
    repository.update(validating)
    failed.fail("decode_failed")
    repository.update(failed)
    for stage in list(AnalysisStage)[1:9]:
        complete.advance_to(stage)
    repository.update(complete)

    assert [job.id for job in repository.list_active()] == [queued.id, validating.id]
