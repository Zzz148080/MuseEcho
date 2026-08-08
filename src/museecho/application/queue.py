from __future__ import annotations

import queue
import re
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Protocol

from museecho.domain.status import AnalysisJob, AnalysisStage, InvalidStageTransition

_STOP = object()
_SAFE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
DEFAULT_PIPELINE_STAGES = (
    AnalysisStage.VALIDATING,
    AnalysisStage.DECODING,
    AnalysisStage.RHYTHM,
    AnalysisStage.TONALITY,
    AnalysisStage.STRUCTURE,
    AnalysisStage.CHORDS,
    AnalysisStage.EVIDENCE,
    AnalysisStage.COMPLETE,
)


class QueueRepository(Protocol):
    def get(self, analysis_id: uuid.UUID) -> AnalysisJob | None: ...
    def update(self, job: AnalysisJob) -> None: ...
    def list_active(self) -> list[AnalysisJob]: ...


class SingleWorkerQueue:
    """A process-local FIFO that executes at most one analysis at a time."""

    def __init__(
        self,
        repository: QueueRepository,
        handler: Callable[[uuid.UUID], None],
        *,
        clock: Callable[[], datetime] | None = None,
        thread_name: str = "museecho-analysis-worker",
    ) -> None:
        self._repository = repository
        self._handler = handler
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._thread_name = thread_name
        self._items: queue.Queue[uuid.UUID | object] = queue.Queue()
        self._condition = threading.Condition()
        self._pending: set[uuid.UUID] = set()
        self._active = False
        self._thread: threading.Thread | None = None
        self._accepting = False

    def start(self, *, recover: bool = True) -> None:
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return
            self._accepting = True
            if recover:
                for job in self._repository.list_active():
                    if self._expire_if_needed(job):
                        continue
                    job.record_retry()
                    self._repository.update(job)
                    self._enqueue_locked(job.id)
            self._thread = threading.Thread(
                target=self._run,
                name=self._thread_name,
                daemon=True,
            )
            self._thread.start()

    def submit(self, analysis_id: uuid.UUID) -> None:
        self.start(recover=False)
        with self._condition:
            if not self._accepting:
                raise RuntimeError("analysis queue is stopping")
            job = self._repository.get(analysis_id)
            if job is None:
                raise KeyError(str(analysis_id))
            if self._expire_if_needed(job):
                return
            self._enqueue_locked(analysis_id)

    def _enqueue_locked(self, analysis_id: uuid.UUID) -> None:
        if analysis_id in self._pending:
            return
        self._pending.add(analysis_id)
        self._items.put(analysis_id)
        self._condition.notify_all()

    def wait_for_idle(self, *, timeout: float) -> bool:
        if timeout < 0:
            raise ValueError("timeout cannot be negative")
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._pending or self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
            return True

    def stop(self, *, timeout: float = 5.0) -> bool:
        if timeout < 0:
            raise ValueError("timeout cannot be negative")
        with self._condition:
            thread = self._thread
            if thread is None:
                self._accepting = False
                return True
            self._accepting = False
            self._items.put(_STOP)
        thread.join(timeout=timeout)
        stopped = not thread.is_alive()
        if stopped:
            with self._condition:
                self._thread = None
                self._condition.notify_all()
        return stopped

    def _run(self) -> None:
        while True:
            item = self._items.get()
            try:
                if item is _STOP:
                    return
                analysis_id = item
                if not isinstance(analysis_id, uuid.UUID):
                    continue
                job = self._repository.get(analysis_id)
                if job is None or self._expire_if_needed(job):
                    with self._condition:
                        self._pending.discard(analysis_id)
                        self._condition.notify_all()
                    continue
                with self._condition:
                    self._active = True
                    self._condition.notify_all()
                try:
                    self._handler(analysis_id)
                except Exception as exc:
                    self._mark_failed(analysis_id, exc)
                finally:
                    with self._condition:
                        self._active = False
                        self._pending.discard(analysis_id)
                        self._condition.notify_all()
            finally:
                self._items.task_done()

    def _mark_failed(self, analysis_id: uuid.UUID, exc: Exception) -> None:
        job = self._repository.get(analysis_id)
        if job is None or job.status.is_terminal:
            return
        candidate = getattr(exc, "code", "analysis_failed")
        error_code = candidate if isinstance(candidate, str) else "analysis_failed"
        if _SAFE_ERROR_CODE.fullmatch(error_code) is None:
            error_code = "analysis_failed"
        try:
            job.fail(error_code)
        except InvalidStageTransition:
            return
        self._repository.update(job)

    def _expire_if_needed(self, job: AnalysisJob) -> bool:
        if job.status.is_terminal:
            return True
        expires_at = job.expires_at
        if expires_at is None:
            return False
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise ValueError("clock must return an aware UTC datetime")
        if expires_at > now:
            return False
        job.expire()
        self._repository.update(job)
        return True


class StagePipeline:
    """Resumeable stage checkpoints advanced only after stage work succeeds."""

    def __init__(
        self,
        repository: QueueRepository,
        run_stage: Callable[[uuid.UUID, AnalysisStage], None],
        *,
        stages: Sequence[AnalysisStage] = DEFAULT_PIPELINE_STAGES,
    ) -> None:
        if not stages:
            raise ValueError("stages cannot be empty")
        normalized = tuple(stages)
        expected_prefix = DEFAULT_PIPELINE_STAGES[: len(normalized)]
        if normalized != expected_prefix:
            raise ValueError("stages must be a contiguous pipeline prefix")
        self._repository = repository
        self._run_stage = run_stage
        self._stages = normalized

    def __call__(self, analysis_id: uuid.UUID) -> None:
        job = self._repository.get(analysis_id)
        if job is None:
            raise KeyError(str(analysis_id))
        if job.status.is_terminal:
            return
        if job.status is AnalysisStage.QUEUED:
            next_index = 0
        else:
            try:
                next_index = self._stages.index(job.status) + 1
            except ValueError:
                raise InvalidStageTransition(
                    f"Cannot resume unsupported stage {job.status.value}"
                ) from None

        for stage in self._stages[next_index:]:
            self._run_stage(analysis_id, stage)
            current = self._repository.get(analysis_id)
            if current is None:
                raise KeyError(str(analysis_id))
            if current.status.is_terminal:
                return
            current.advance_to(stage)
            self._repository.update(current)


__all__ = ["DEFAULT_PIPELINE_STAGES", "SingleWorkerQueue", "StagePipeline"]
