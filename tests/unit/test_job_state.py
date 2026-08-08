from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from museecho.domain.status import AnalysisJob, AnalysisStage, InvalidStageTransition, SourceKind


@pytest.fixture
def job() -> AnalysisJob:
    return AnalysisJob()


def test_initial_state(job: AnalysisJob):
    assert job.status == AnalysisStage.QUEUED


def test_cannot_skip_from_queued_to_chords(job: AnalysisJob):
    with pytest.raises(InvalidStageTransition):
        job.advance_to(AnalysisStage.CHORDS)


def test_sequential_advance_all_stages(job: AnalysisJob):
    stages = [
        AnalysisStage.QUEUED,
        AnalysisStage.VALIDATING,
        AnalysisStage.DECODING,
        AnalysisStage.RHYTHM,
        AnalysisStage.TONALITY,
        AnalysisStage.STRUCTURE,
        AnalysisStage.CHORDS,
        AnalysisStage.EVIDENCE,
        AnalysisStage.COMPLETE,
    ]
    for s in stages:
        assert job.status == s
        if s != AnalysisStage.COMPLETE:
            job.advance_to(AnalysisStage(stages[stages.index(s) + 1].value))

    assert job.status == AnalysisStage.COMPLETE
    assert job.status.is_terminal


def test_cannot_advance_from_complete(job: AnalysisJob):
    while job.status != AnalysisStage.COMPLETE:
        next_idx = list(AnalysisStage).index(job.status) + 1
        job.advance_to(list(AnalysisStage)[next_idx])

    with pytest.raises(InvalidStageTransition, match="terminal"):
        job.advance_to(AnalysisStage.FAILED)


def test_cannot_skip_multiple_stages(job: AnalysisJob):
    job.advance_to(AnalysisStage.VALIDATING)
    with pytest.raises(InvalidStageTransition):
        job.advance_to(AnalysisStage.STRUCTURE)


def test_cannot_go_backwards(job: AnalysisJob):
    job.advance_to(AnalysisStage.VALIDATING)
    job.advance_to(AnalysisStage.DECODING)
    with pytest.raises(InvalidStageTransition):
        job.advance_to(AnalysisStage.VALIDATING)


def test_terminal_states_are_terminal():
    terminal = [
        AnalysisStage.COMPLETE,
        AnalysisStage.FAILED,
        AnalysisStage.DELETED,
        AnalysisStage.EXPIRED,
    ]
    for stage in terminal:
        assert stage.is_terminal


def test_non_terminal_states():
    for stage in [AnalysisStage.QUEUED, AnalysisStage.RHYTHM, AnalysisStage.CHORDS]:
        assert not stage.is_terminal


def test_progress_increases_with_each_pipeline_stage(job: AnalysisJob):
    observed = [job.progress]
    for stage in [
        AnalysisStage.VALIDATING,
        AnalysisStage.DECODING,
        AnalysisStage.RHYTHM,
        AnalysisStage.TONALITY,
        AnalysisStage.STRUCTURE,
        AnalysisStage.CHORDS,
        AnalysisStage.EVIDENCE,
        AnalysisStage.COMPLETE,
    ]:
        job.advance_to(stage)
        observed.append(job.progress)

    assert observed == sorted(observed)
    assert observed[0] == 0.0
    assert observed[-1] == 1.0


def test_failure_is_an_explicit_transition_from_processing(job: AnalysisJob):
    job.advance_to(AnalysisStage.VALIDATING)
    progress_before_failure = job.progress

    job.fail("decode_failed")

    assert job.status == AnalysisStage.FAILED
    assert job.error_code == "decode_failed"
    assert job.progress == progress_before_failure


def test_completed_job_can_be_deleted(job: AnalysisJob):
    for stage in [
        AnalysisStage.VALIDATING,
        AnalysisStage.DECODING,
        AnalysisStage.RHYTHM,
        AnalysisStage.TONALITY,
        AnalysisStage.STRUCTURE,
        AnalysisStage.CHORDS,
        AnalysisStage.EVIDENCE,
        AnalysisStage.COMPLETE,
    ]:
        job.advance_to(stage)

    job.delete()

    assert job.status == AnalysisStage.DELETED


def test_job_rejects_naive_timestamps_and_unknown_source_kind():
    with pytest.raises(ValueError, match="UTC"):
        AnalysisJob(created_at=datetime.now())

    with pytest.raises(ValueError, match="source_kind"):
        AnalysisJob(source_kind="uploaded")

    job = AnalysisJob(source_kind=SourceKind.SYNTHETIC_TEST)
    assert job.source_kind is SourceKind.SYNTHETIC_TEST
    assert job.created_at.tzinfo == timezone.utc


def test_job_rejects_inconsistent_persisted_state():
    with pytest.raises(ValueError, match="progress"):
        AnalysisJob(stage=AnalysisStage.VALIDATING, progress=0.9)

    with pytest.raises(ValueError, match="error_code"):
        AnalysisJob(stage=AnalysisStage.FAILED, progress=0.25)

    with pytest.raises(ValueError, match="status"):
        AnalysisJob(
            status=AnalysisStage.FAILED,
            stage=AnalysisStage.COMPLETE,
            progress=1.0,
        )


def test_pipeline_state_is_only_mutated_through_transitions(job: AnalysisJob):
    with pytest.raises(AttributeError):
        job.stage = AnalysisStage.COMPLETE

    with pytest.raises(AttributeError):
        job.progress = 1.0


def test_job_rejects_impossible_timestamp_ordering():
    created_at = datetime.now(timezone.utc)

    with pytest.raises(ValueError, match="updated_at"):
        AnalysisJob(created_at=created_at, updated_at=created_at - timedelta(seconds=1))

    with pytest.raises(ValueError, match="expires_at"):
        AnalysisJob(created_at=created_at, expires_at=created_at)


def test_transition_never_moves_updated_at_backwards():
    created_at = datetime.now(timezone.utc)
    future_update = created_at + timedelta(minutes=5)
    job = AnalysisJob(created_at=created_at, updated_at=future_update)

    job.advance_to(AnalysisStage.VALIDATING)

    assert job.updated_at >= future_update
