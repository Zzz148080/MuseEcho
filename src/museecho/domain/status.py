from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone


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
        return self in (
            AnalysisStage.COMPLETE,
            AnalysisStage.FAILED,
            AnalysisStage.DELETED,
            AnalysisStage.EXPIRED,
        )


_STAGE_ORDER: list[AnalysisStage] = [
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

_TERMINAL_STAGES = {AnalysisStage.FAILED, AnalysisStage.DELETED, AnalysisStage.EXPIRED}


def _stage_index(stage: AnalysisStage) -> int:
    if stage in _TERMINAL_STAGES:
        return len(_STAGE_ORDER)
    try:
        return _STAGE_ORDER.index(stage)
    except ValueError:
        raise InvalidStageTransition(f"Unknown stage: {stage}")


class AnalysisJob:
    def __init__(
        self,
        id: uuid.UUID | None = None,
        status: AnalysisStage = AnalysisStage.QUEUED,
        source_kind: str = "real",
        created_at: datetime | None = None,
        expires_at: datetime | None = None,
    ):
        self.id = id or uuid.uuid4()
        self._status = status
        self.source_kind = source_kind
        self.created_at = created_at or datetime.now(timezone.utc)
        self.expires_at = expires_at

    @property
    def status(self) -> AnalysisStage:
        return self._status

    def advance_to(self, stage: AnalysisStage) -> None:
        if self._status.is_terminal:
            raise InvalidStageTransition(f"Cannot advance from terminal state {self._status.value}")

        current_idx = _stage_index(self._status)
        target_idx = _stage_index(stage)

        if target_idx != current_idx + 1:
            raise InvalidStageTransition(
                f"Cannot skip from {self._status.value} to {stage.value}"
            )

        self._status = stage
