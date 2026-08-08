from __future__ import annotations

import enum
import uuid
from datetime import datetime, timedelta, timezone


class InvalidStageTransition(ValueError):
    pass


class AnalysisStage(str, enum.Enum):
    QUEUED = "queued"
    VALIDATING = "validating"
    DECODING = "decoding"
    RHYTHM = "rhythm"
    TONALITY = "tonality"
    STRUCTURE = "structure"
    CHORDS = "chords"
    EVIDENCE = "evidence"
    COMPLETE = "complete"
    FAILED = "failed"
    DELETED = "deleted"
    EXPIRED = "expired"

    @property
    def is_terminal(self) -> bool:
        return self in {
            AnalysisStage.COMPLETE,
            AnalysisStage.FAILED,
            AnalysisStage.DELETED,
            AnalysisStage.EXPIRED,
        }


class SourceKind(str, enum.Enum):
    REAL = "real"
    DEMO = "demo"
    SYNTHETIC_TEST = "synthetic_test"


_PIPELINE: tuple[AnalysisStage, ...] = (
    AnalysisStage.QUEUED,
    AnalysisStage.VALIDATING,
    AnalysisStage.DECODING,
    AnalysisStage.RHYTHM,
    AnalysisStage.TONALITY,
    AnalysisStage.STRUCTURE,
    AnalysisStage.CHORDS,
    AnalysisStage.EVIDENCE,
    AnalysisStage.COMPLETE,
)


def _require_utc(value: datetime | None, name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() != timedelta(0)):
        raise ValueError(f"{name} must be an aware UTC datetime")


class AnalysisJob:
    """An analysis job whose persisted state cannot violate pipeline invariants."""

    def __init__(
        self,
        id: uuid.UUID | None = None,
        stage: AnalysisStage = AnalysisStage.QUEUED,
        progress: float | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        expires_at: datetime | None = None,
        error_code: str | None = None,
        retry_count: int = 0,
        pipeline_version: str | None = None,
        source_kind: SourceKind = SourceKind.REAL,
        *,
        status: AnalysisStage | None = None,
    ) -> None:
        if not isinstance(stage, AnalysisStage):
            raise ValueError("stage must be an AnalysisStage")
        if status is not None and not isinstance(status, AnalysisStage):
            raise ValueError("status must be an AnalysisStage")
        if status is not None and status is not stage:
            raise ValueError("status and stage must match")
        if not isinstance(source_kind, SourceKind):
            raise ValueError("source_kind must be a SourceKind")
        if retry_count < 0:
            raise ValueError("retry_count cannot be negative")

        expected_progress = self._expected_progress(stage)
        if progress is None:
            progress = expected_progress if expected_progress is not None else 0.0
        if not 0.0 <= progress <= 1.0:
            raise ValueError("progress must be between 0.0 and 1.0")
        if expected_progress is not None and progress != expected_progress:
            raise ValueError(f"progress must be {expected_progress} for stage {stage.value}")
        if stage is AnalysisStage.FAILED and (error_code is None or not error_code.strip()):
            raise ValueError("error_code is required for failed jobs")

        created_at = created_at or datetime.now(timezone.utc)
        updated_at = updated_at or created_at
        _require_utc(created_at, "created_at")
        _require_utc(updated_at, "updated_at")
        _require_utc(expires_at, "expires_at")
        if updated_at < created_at:
            raise ValueError("updated_at cannot be before created_at")
        if expires_at is not None and expires_at <= created_at:
            raise ValueError("expires_at must be after created_at")

        self.id = id or uuid.uuid4()
        self._stage = stage
        self._progress = progress
        self.created_at = created_at
        self.updated_at = updated_at
        self.expires_at = expires_at
        self.error_code = error_code
        self.retry_count = retry_count
        self.pipeline_version = pipeline_version
        self.source_kind = source_kind

    @staticmethod
    def _expected_progress(stage: AnalysisStage) -> float | None:
        if stage in _PIPELINE:
            return _PIPELINE.index(stage) / (len(_PIPELINE) - 1)
        return None

    @property
    def status(self) -> AnalysisStage:
        return self._stage

    @property
    def stage(self) -> AnalysisStage:
        return self._stage

    @property
    def progress(self) -> float:
        return self._progress

    def _touch(self) -> None:
        self.updated_at = max(datetime.now(timezone.utc), self.created_at, self.updated_at)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AnalysisJob):
            return NotImplemented
        fields = (
            "id",
            "status",
            "stage",
            "progress",
            "created_at",
            "updated_at",
            "expires_at",
            "error_code",
            "retry_count",
            "pipeline_version",
            "source_kind",
        )
        return all(getattr(self, name) == getattr(other, name) for name in fields)

    def advance_to(self, stage: AnalysisStage) -> None:
        if self.stage not in _PIPELINE or self.stage.is_terminal:
            raise InvalidStageTransition(f"Cannot advance from terminal state {self.stage.value}")
        current_index = _PIPELINE.index(self.stage)
        if current_index + 1 >= len(_PIPELINE) or _PIPELINE[current_index + 1] is not stage:
            raise InvalidStageTransition(f"Cannot skip from {self.stage.value} to {stage.value}")
        self._stage = stage
        self._progress = _PIPELINE.index(stage) / (len(_PIPELINE) - 1)
        self._touch()

    def fail(self, error_code: str) -> None:
        if self.stage.is_terminal or not error_code.strip():
            raise InvalidStageTransition(f"Cannot fail from {self.stage.value}")
        self._stage = AnalysisStage.FAILED
        self.error_code = error_code
        self._touch()

    def delete(self) -> None:
        if self.stage in {AnalysisStage.DELETED, AnalysisStage.EXPIRED}:
            raise InvalidStageTransition(f"Cannot delete from {self.stage.value}")
        self._stage = AnalysisStage.DELETED
        self._touch()

    def expire(self) -> None:
        if self.stage in {AnalysisStage.DELETED, AnalysisStage.EXPIRED}:
            raise InvalidStageTransition(f"Cannot expire from {self.stage.value}")
        self._stage = AnalysisStage.EXPIRED
        self._touch()
