from __future__ import annotations

import pytest

from museecho.domain.status import AnalysisJob, AnalysisStage, InvalidStageTransition


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
