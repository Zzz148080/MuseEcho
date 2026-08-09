from __future__ import annotations

import hashlib
import math
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from threading import Lock

from museecho.application.cleanup import AnalysisDeletionService
from museecho.application.evidence import select_for_segment
from museecho.application.explanations import ExplanationService
from museecho.domain.models import AnalysisResult, EncryptedAudioMetadata, Explanation
from museecho.domain.ports import AnalysisRepository, EncryptedAudioStore
from museecho.domain.status import AnalysisJob, AnalysisStage


class ResultNotReadyError(RuntimeError):
    code = "analysis_not_ready"


class ExplanationRateLimitedError(RuntimeError):
    code = "explanation_rate_limited"


class AnalysisLifecycleService:
    def __init__(
        self,
        repository: AnalysisRepository,
        audio_store: EncryptedAudioStore | None = None,
        explanation_service: ExplanationService | None = None,
        deletion_service: AnalysisDeletionService | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._audio_store = audio_store
        self._explanation_service = explanation_service
        self._deletion_service = deletion_service
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._explanation_attempts: dict[uuid.UUID, list[datetime]] = {}
        self._explanation_lock = Lock()

    def status(self, analysis_id: uuid.UUID) -> AnalysisJob:
        job = self._repository.get(analysis_id)
        if job is None:
            raise KeyError(str(analysis_id))
        return job

    def result(self, analysis_id: uuid.UUID) -> AnalysisResult:
        job = self.status(analysis_id)
        if job.status is not AnalysisStage.COMPLETE:
            raise ResultNotReadyError("analysis result is not ready")
        track = self._repository.get_result(analysis_id)
        if track is None:
            raise ResultNotReadyError("analysis result is not ready")
        return AnalysisResult(
            track=track,
            sections=tuple(self._repository.get_sections(analysis_id)),
            chords=tuple(self._repository.get_chords(analysis_id)),
            time_series=tuple(self._repository.get_all_timeseries(analysis_id)),
            evidence=tuple(self._repository.get_evidence(analysis_id)),
        )

    def audio_metadata(self, analysis_id: uuid.UUID) -> EncryptedAudioMetadata:
        metadata = self._repository.get_encrypted_audio(analysis_id)
        if metadata is None or not metadata.wrapped_data_key:
            raise KeyError(str(analysis_id))
        return metadata

    def read_audio(
        self,
        metadata: EncryptedAudioMetadata,
        start: int,
        end: int,
    ) -> bytes:
        if self._audio_store is None:
            raise RuntimeError("audio store is unavailable")
        return self._audio_store.read_range(metadata, start, end)

    def explain(
        self,
        analysis_id: uuid.UUID,
        *,
        question: str,
        start_seconds: float,
        end_seconds: float,
    ) -> Explanation:
        if self._explanation_service is None:
            raise RuntimeError("explanation service is unavailable")
        track = self.result(analysis_id).track
        if (
            not isinstance(question, str)
            or not question.strip()
            or len(question) > 500
            or not math.isfinite(start_seconds)
            or not math.isfinite(end_seconds)
            or start_seconds < 0.0
            or end_seconds <= start_seconds
            or end_seconds > track.duration_seconds
            or end_seconds - start_seconds > 120.0
        ):
            raise ValueError("explanation segment is invalid")
        created_at = self._claim_explanation_slot(analysis_id)
        selected = select_for_segment(
            self._repository.get_evidence(analysis_id),
            start_seconds,
            end_seconds,
        )
        draft = self._explanation_service.explain(question, selected)
        created = Explanation(
            id=uuid.uuid4(),
            analysis_id=analysis_id,
            segment_start=start_seconds,
            segment_end=end_seconds,
            question_digest=hashlib.sha256(question.strip().encode("utf-8")).hexdigest(),
            evidence_ids_json=[str(item) for item in draft.evidence_ids],
            mode=draft.mode,
            text=draft.text,
            created_at=created_at,
        )
        self._repository.add_explanation(created)
        return created

    def _claim_explanation_slot(self, analysis_id: uuid.UUID) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise ValueError("clock must return an aware UTC datetime")
        cutoff = now - timedelta(minutes=1)
        with self._explanation_lock:
            recent = [
                timestamp
                for timestamp in self._explanation_attempts.get(analysis_id, [])
                if timestamp > cutoff
            ]
            if len(recent) >= 10:
                raise ExplanationRateLimitedError("explanation rate limit exceeded")
            recent.append(now)
            self._explanation_attempts[analysis_id] = recent
        return now

    def delete(self, analysis_id: uuid.UUID) -> bool:
        if self._deletion_service is None:
            raise RuntimeError("deletion service is unavailable")
        return self._deletion_service.delete(analysis_id)


__all__ = [
    "AnalysisLifecycleService",
    "ExplanationRateLimitedError",
    "ResultNotReadyError",
]
