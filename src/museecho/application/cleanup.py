from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from museecho.domain.ports import AnalysisRepository, EncryptedAudioStore

_SAFE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class AnalysisDeletionService:
    """Revoke access before crypto-erasure, then remove the aggregate."""

    def __init__(
        self,
        repository: AnalysisRepository,
        audio_store: EncryptedAudioStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._audio_store = audio_store
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def delete(self, analysis_id: uuid.UUID) -> bool:
        job = self._repository.get(analysis_id)
        if job is None:
            return False
        metadata = self._repository.get_encrypted_audio(analysis_id)
        self._repository.prepare_deletion(analysis_id, self._utc_now())
        if metadata is not None:
            self._audio_store.delete(metadata)
        self._repository.delete_cascade(analysis_id)
        return True

    def _utc_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise ValueError("clock must return an aware UTC datetime")
        return now


class ExpiryCleanup:
    def __init__(
        self,
        repository: AnalysisRepository,
        deletion_service: AnalysisDeletionService,
        *,
        clock: Callable[[], datetime] | None = None,
        failure_observer: Callable[[uuid.UUID, str], None] | None = None,
    ) -> None:
        self._repository = repository
        self._deletion_service = deletion_service
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._failure_observer = failure_observer

    def run_once(self) -> int:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise ValueError("clock must return an aware UTC datetime")
        deleted = 0
        for job in self._repository.list_expired(now):
            try:
                if self._deletion_service.delete(job.id):
                    deleted += 1
            except Exception as exc:
                code = getattr(exc, "code", "cleanup_failed")
                if not isinstance(code, str) or _SAFE_ERROR_CODE.fullmatch(code) is None:
                    code = "cleanup_failed"
                if self._failure_observer is not None:
                    try:
                        self._failure_observer(job.id, code)
                    except Exception:
                        pass
        return deleted


__all__ = ["AnalysisDeletionService", "ExpiryCleanup"]
