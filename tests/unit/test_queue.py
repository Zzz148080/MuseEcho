from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable

from museecho.application.queue import SingleWorkerQueue, StagePipeline
from museecho.domain.status import AnalysisJob, AnalysisStage


class MemoryQueueRepository:
    def __init__(self, jobs: list[AnalysisJob] | None = None) -> None:
        self.jobs = {job.id: job for job in jobs or []}
        self._lock = threading.Lock()

    def add(self, job: AnalysisJob) -> None:
        with self._lock:
            self.jobs[job.id] = job

    def get(self, analysis_id: uuid.UUID) -> AnalysisJob | None:
        with self._lock:
            return self.jobs.get(analysis_id)

    def update(self, job: AnalysisJob) -> None:
        with self._lock:
            self.jobs[job.id] = job

    def list_active(self) -> list[AnalysisJob]:
        with self._lock:
            return [job for job in self.jobs.values() if not job.status.is_terminal]


def _wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached before timeout")


def test_two_jobs_never_run_in_parallel():
    first = AnalysisJob()
    second = AnalysisJob()
    repository = MemoryQueueRepository([first, second])
    release_first = threading.Event()
    first_started = threading.Event()
    second_started = threading.Event()
    active = 0
    peak_active = 0
    lock = threading.Lock()

    def handler(analysis_id: uuid.UUID) -> None:
        nonlocal active, peak_active
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        try:
            if analysis_id == first.id:
                first_started.set()
                assert release_first.wait(timeout=2)
            else:
                second_started.set()
        finally:
            with lock:
                active -= 1

    queue = SingleWorkerQueue(repository, handler)
    queue.start(recover=False)
    try:
        queue.submit(first.id)
        queue.submit(second.id)
        assert first_started.wait(timeout=2)
        assert not second_started.wait(timeout=0.1)
        release_first.set()
        assert queue.wait_for_idle(timeout=2)
    finally:
        queue.stop()

    assert second_started.is_set()
    assert peak_active == 1


def test_start_recovers_nonterminal_jobs_without_marking_complete():
    interrupted = AnalysisJob()
    interrupted.advance_to(AnalysisStage.VALIDATING)
    repository = MemoryQueueRepository([interrupted])
    started = threading.Event()
    release = threading.Event()

    def handler(analysis_id: uuid.UUID) -> None:
        assert analysis_id == interrupted.id
        started.set()
        assert release.wait(timeout=2)

    queue = SingleWorkerQueue(repository, handler)
    queue.start()
    try:
        assert started.wait(timeout=2)
        recovered = repository.get(interrupted.id)
        assert recovered is not None
        assert recovered.status is AnalysisStage.VALIDATING
        release.set()
        assert queue.wait_for_idle(timeout=2)
    finally:
        queue.stop()

    recovered = repository.get(interrupted.id)
    assert recovered is not None
    assert recovered.status is AnalysisStage.VALIDATING

    assert recovered.retry_count == 1


def test_duplicate_submission_is_coalesced():
    job = AnalysisJob()
    repository = MemoryQueueRepository([job])
    release = threading.Event()
    calls = 0

    def handler(_: uuid.UUID) -> None:
        nonlocal calls
        calls += 1
        assert release.wait(timeout=2)

    queue = SingleWorkerQueue(repository, handler)
    queue.start(recover=False)
    try:
        queue.submit(job.id)
        queue.submit(job.id)
        _wait_until(lambda: calls == 1)
        queue.submit(job.id)
        release.set()
        assert queue.wait_for_idle(timeout=2)
    finally:
        queue.stop()

    assert calls == 1


def test_handler_failure_marks_job_failed_with_safe_code():
    job = AnalysisJob()
    repository = MemoryQueueRepository([job])

    class CodedFailure(RuntimeError):
        code = "decode_failed"

    def handler(_: uuid.UUID) -> None:
        raise CodedFailure("private path must not escape")

    queue = SingleWorkerQueue(repository, handler)
    queue.start(recover=False)
    try:
        queue.submit(job.id)
        assert queue.wait_for_idle(timeout=2)
    finally:
        queue.stop()

    failed = repository.get(job.id)
    assert failed is not None
    assert failed.status is AnalysisStage.FAILED
    assert failed.error_code == "decode_failed"


def test_stage_pipeline_advances_only_after_real_work_finishes():
    job = AnalysisJob()
    repository = MemoryQueueRepository([job])
    validating_started = threading.Event()
    release_validation = threading.Event()

    def run_stage(analysis_id: uuid.UUID, stage: AnalysisStage) -> None:
        assert analysis_id == job.id
        if stage is AnalysisStage.VALIDATING:
            validating_started.set()
            assert release_validation.wait(timeout=2)

    pipeline = StagePipeline(repository, run_stage, stages=(AnalysisStage.VALIDATING,))
    thread = threading.Thread(target=pipeline, args=(job.id,))
    thread.start()
    try:
        assert validating_started.wait(timeout=2)
        current = repository.get(job.id)
        assert current is not None
        assert current.status is AnalysisStage.QUEUED
        release_validation.set()
        thread.join(timeout=2)
    finally:
        release_validation.set()
        thread.join(timeout=2)

    assert not thread.is_alive()
    current = repository.get(job.id)
    assert current is not None
    assert current.status is AnalysisStage.VALIDATING


def test_stage_pipeline_resumes_after_last_completed_stage():
    job = AnalysisJob()
    job.advance_to(AnalysisStage.VALIDATING)
    repository = MemoryQueueRepository([job])
    observed: list[AnalysisStage] = []
    pipeline = StagePipeline(
        repository,
        lambda _analysis_id, stage: observed.append(stage),
        stages=(AnalysisStage.VALIDATING, AnalysisStage.DECODING),
    )

    pipeline(job.id)

    assert observed == [AnalysisStage.DECODING]
    current = repository.get(job.id)
    assert current is not None
    assert current.status is AnalysisStage.DECODING


def test_expired_job_is_not_recovered_or_counted_as_retry():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    job = AnalysisJob(
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
    )
    repository = MemoryQueueRepository([job])
    observed: list[uuid.UUID] = []
    queue = SingleWorkerQueue(repository, observed.append, clock=lambda: now)

    queue.start()
    try:
        assert queue.wait_for_idle(timeout=2)
    finally:
        queue.stop()

    current = repository.get(job.id)
    assert current is not None
    assert current.status is AnalysisStage.EXPIRED
    assert current.retry_count == 0
    assert observed == []


def test_job_that_expires_while_queued_is_not_executed():
    from datetime import datetime, timedelta, timezone

    current_time = [datetime.now(timezone.utc)]
    expires_at = current_time[0] + timedelta(minutes=1)
    first = AnalysisJob(expires_at=expires_at)
    second = AnalysisJob(expires_at=expires_at)
    repository = MemoryQueueRepository([first, second])
    first_started = threading.Event()
    release_first = threading.Event()
    observed: list[uuid.UUID] = []

    def handler(analysis_id: uuid.UUID) -> None:
        observed.append(analysis_id)
        if analysis_id == first.id:
            first_started.set()
            assert release_first.wait(timeout=2)

    queue = SingleWorkerQueue(repository, handler, clock=lambda: current_time[0])
    queue.start(recover=False)
    try:
        queue.submit(first.id)
        queue.submit(second.id)
        assert first_started.wait(timeout=2)
        current_time[0] = expires_at + timedelta(seconds=1)
        release_first.set()
        assert queue.wait_for_idle(timeout=2)
    finally:
        queue.stop()

    expired = repository.get(second.id)
    assert expired is not None
    assert expired.status is AnalysisStage.EXPIRED
    assert observed == [first.id]
