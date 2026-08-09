from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    delete,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

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
from museecho.infrastructure.db import UTCDateTime, create_museecho_engine, session_scope


class Base(DeclarativeBase):
    pass


class AnalysisJobModel(Base):
    __tablename__ = "analysis_jobs"
    __table_args__ = (CheckConstraint("status = stage", name="ck_analysis_jobs_status_stage"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pipeline_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="real")


class AccessGrantModel(Base):
    __tablename__ = "access_grants"

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class EncryptedAudioModel(Base):
    __tablename__ = "encrypted_audio"

    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    cipher_path: Mapped[str] = mapped_column(Text, nullable=False)
    wrapped_data_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    plaintext_size: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class TrackAnalysisModel(Base):
    __tablename__ = "track_analyses"

    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    sample_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    channels: Mapped[int] = mapped_column(Integer, nullable=False)
    bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    bpm_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    key_tonic: Mapped[str | None] = mapped_column(String(10), nullable=True)
    mode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    key_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_signature: Mapped[str | None] = mapped_column(String(10), nullable=True)
    time_signature_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class SectionEventModel(Base):
    __tablename__ = "section_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(50), nullable=False)


class ChordEventModel(Base):
    __tablename__ = "chord_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(50), nullable=False)
    theory_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class TimeSeriesModel(Base):
    __tablename__ = "time_series"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    resolution_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    points_json: Mapped[str] = mapped_column(Text, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(50), nullable=False)


class EvidenceModel(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(50), nullable=False)
    eligible_for_llm: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ExplanationModel(Base):
    __tablename__ = "explanations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    segment_start: Mapped[float] = mapped_column(Float, nullable=False)
    segment_end: Mapped[float] = mapped_column(Float, nullable=False)
    question_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


def _dump_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _load_json(value: str | None) -> Any:
    return None if value is None else json.loads(value)


def _job_from_model(model: AnalysisJobModel) -> AnalysisJob:
    return AnalysisJob(
        id=uuid.UUID(model.id),
        status=AnalysisStage(model.status),
        stage=AnalysisStage(model.stage),
        progress=model.progress,
        created_at=model.created_at,
        updated_at=model.updated_at,
        expires_at=model.expires_at,
        error_code=model.error_code,
        retry_count=model.retry_count,
        pipeline_version=model.pipeline_version,
        source_kind=SourceKind(model.source_kind),
    )


class SqliteAnalysisRepository:
    def __init__(self, session_factory: sessionmaker[Any]):
        self._session_factory = session_factory

    def add(self, job: AnalysisJob) -> None:
        with session_scope(self._session_factory) as session:
            session.add(
                AnalysisJobModel(
                    id=str(job.id),
                    status=job.status.value,
                    stage=job.stage.value,
                    progress=job.progress,
                    created_at=job.created_at,
                    updated_at=job.updated_at,
                    expires_at=job.expires_at,
                    error_code=job.error_code,
                    retry_count=job.retry_count,
                    pipeline_version=job.pipeline_version,
                    source_kind=job.source_kind.value,
                )
            )

    def get(self, analysis_id: uuid.UUID) -> AnalysisJob | None:
        with session_scope(self._session_factory) as session:
            model = session.get(AnalysisJobModel, str(analysis_id))
            return None if model is None else _job_from_model(model)

    def update(self, job: AnalysisJob) -> None:
        with session_scope(self._session_factory) as session:
            model = session.get(AnalysisJobModel, str(job.id))
            if model is None:
                raise KeyError(str(job.id))
            model.status = job.status.value
            model.stage = job.stage.value
            model.progress = job.progress
            model.updated_at = job.updated_at or job.created_at
            model.expires_at = job.expires_at
            model.error_code = job.error_code
            model.retry_count = job.retry_count
            model.pipeline_version = job.pipeline_version
            model.source_kind = job.source_kind.value

    def list_active(self) -> list[AnalysisJob]:
        terminal = tuple(stage.value for stage in AnalysisStage if stage.is_terminal)
        with session_scope(self._session_factory) as session:
            models = session.scalars(
                select(AnalysisJobModel)
                .where(AnalysisJobModel.status.not_in(terminal))
                .order_by(AnalysisJobModel.created_at, AnalysisJobModel.id)
            ).all()
            return [_job_from_model(model) for model in models]

    def list_expired(self, now: datetime) -> list[AnalysisJob]:
        with session_scope(self._session_factory) as session:
            models = session.scalars(
                select(AnalysisJobModel)
                .where(
                    AnalysisJobModel.expires_at.is_not(None),
                    AnalysisJobModel.expires_at <= now,
                )
                .order_by(AnalysisJobModel.expires_at, AnalysisJobModel.id)
            ).all()
            return [_job_from_model(model) for model in models]

    def save_result(self, result: AnalysisResult) -> None:
        with session_scope(self._session_factory) as session:
            result.validate()
            job = session.get(AnalysisJobModel, str(result.track.analysis_id))
            if job is None:
                raise KeyError(str(result.track.analysis_id))
            completed_job = _job_from_model(job)
            completed_job.advance_to(AnalysisStage.COMPLETE)

            session.add(
                TrackAnalysisModel(
                    analysis_id=str(result.track.analysis_id),
                    duration_seconds=result.track.duration_seconds,
                    sample_rate=result.track.sample_rate,
                    channels=result.track.channels,
                    bpm=result.track.bpm,
                    bpm_confidence=result.track.bpm_confidence,
                    key_tonic=result.track.key_tonic,
                    mode=result.track.mode,
                    key_confidence=result.track.key_confidence,
                    time_signature=result.track.time_signature,
                    time_signature_confidence=result.track.time_signature_confidence,
                    summary_json=_dump_json(result.track.summary_json),
                )
            )
            session.add_all(
                [
                    SectionEventModel(
                        id=str(section.id),
                        analysis_id=str(section.analysis_id),
                        start_seconds=section.start_seconds,
                        end_seconds=section.end_seconds,
                        label=section.label,
                        confidence=section.confidence,
                        algorithm=section.algorithm,
                    )
                    for section in result.sections
                ]
            )
            session.add_all(
                [
                    ChordEventModel(
                        id=str(chord.id),
                        analysis_id=str(chord.analysis_id),
                        start_seconds=chord.start_seconds,
                        end_seconds=chord.end_seconds,
                        symbol=chord.symbol,
                        confidence=chord.confidence,
                        algorithm=chord.algorithm,
                        theory_json=None
                        if chord.theory_json is None
                        else _dump_json(chord.theory_json),
                    )
                    for chord in result.chords
                ]
            )
            session.add_all(
                [
                    TimeSeriesModel(
                        id=str(uuid.uuid4()),
                        analysis_id=str(timeseries.analysis_id),
                        kind=timeseries.kind,
                        resolution_seconds=timeseries.resolution_seconds,
                        points_json=_dump_json(timeseries.points_json),
                        algorithm=timeseries.algorithm,
                    )
                    for timeseries in result.time_series
                ]
            )
            session.add_all(
                [
                    EvidenceModel(
                        id=str(evidence.id),
                        analysis_id=str(evidence.analysis_id),
                        kind=evidence.kind,
                        start_seconds=evidence.start_seconds,
                        end_seconds=evidence.end_seconds,
                        value_json=None
                        if evidence.value_json is None
                        else _dump_json(evidence.value_json),
                        confidence=evidence.confidence,
                        algorithm=evidence.algorithm,
                        eligible_for_llm=evidence.eligible_for_llm,
                    )
                    for evidence in result.evidence
                ]
            )
            job.status = completed_job.status.value
            job.stage = completed_job.stage.value
            job.progress = completed_job.progress
            job.updated_at = completed_job.updated_at

    def get_result(self, analysis_id: uuid.UUID) -> TrackAnalysis | None:
        with session_scope(self._session_factory) as session:
            model = session.get(TrackAnalysisModel, str(analysis_id))
            if model is None:
                return None
            return TrackAnalysis(
                analysis_id=uuid.UUID(model.analysis_id),
                duration_seconds=model.duration_seconds,
                sample_rate=model.sample_rate,
                channels=model.channels,
                bpm=model.bpm,
                bpm_confidence=model.bpm_confidence,
                key_tonic=model.key_tonic,
                mode=model.mode,
                key_confidence=model.key_confidence,
                time_signature=model.time_signature,
                time_signature_confidence=model.time_signature_confidence,
                summary_json=_load_json(model.summary_json),
            )

    def get_sections(self, analysis_id: uuid.UUID) -> list[SectionEvent]:
        with session_scope(self._session_factory) as session:
            models = session.scalars(
                select(SectionEventModel)
                .where(SectionEventModel.analysis_id == str(analysis_id))
                .order_by(SectionEventModel.start_seconds, SectionEventModel.id)
            ).all()
            return [
                SectionEvent(
                    uuid.UUID(model.id),
                    uuid.UUID(model.analysis_id),
                    model.start_seconds,
                    model.end_seconds,
                    model.label,
                    model.confidence,
                    model.algorithm,
                )
                for model in models
            ]

    def get_chords(self, analysis_id: uuid.UUID) -> list[ChordEvent]:
        with session_scope(self._session_factory) as session:
            models = session.scalars(
                select(ChordEventModel)
                .where(ChordEventModel.analysis_id == str(analysis_id))
                .order_by(ChordEventModel.start_seconds, ChordEventModel.id)
            ).all()
            return [
                ChordEvent(
                    uuid.UUID(model.id),
                    uuid.UUID(model.analysis_id),
                    model.start_seconds,
                    model.end_seconds,
                    model.symbol,
                    model.confidence,
                    model.algorithm,
                    _load_json(model.theory_json),
                )
                for model in models
            ]

    def get_timeseries(self, analysis_id: uuid.UUID, kind: str) -> list[TimeSeries]:
        with session_scope(self._session_factory) as session:
            models = session.scalars(
                select(TimeSeriesModel)
                .where(
                    TimeSeriesModel.analysis_id == str(analysis_id),
                    TimeSeriesModel.kind == kind,
                )
                .order_by(TimeSeriesModel.id)
            ).all()
            return [
                TimeSeries(
                    uuid.UUID(model.analysis_id),
                    model.kind,
                    model.resolution_seconds,
                    _load_json(model.points_json),
                    model.algorithm,
                )
                for model in models
            ]

    def get_all_timeseries(self, analysis_id: uuid.UUID) -> list[TimeSeries]:
        with session_scope(self._session_factory) as session:
            models = session.scalars(
                select(TimeSeriesModel)
                .where(TimeSeriesModel.analysis_id == str(analysis_id))
                .order_by(TimeSeriesModel.kind, TimeSeriesModel.id)
            ).all()
            return [
                TimeSeries(
                    uuid.UUID(model.analysis_id),
                    model.kind,
                    model.resolution_seconds,
                    _load_json(model.points_json),
                    model.algorithm,
                )
                for model in models
            ]

    def get_evidence(self, analysis_id: uuid.UUID) -> list[Evidence]:
        with session_scope(self._session_factory) as session:
            models = session.scalars(
                select(EvidenceModel)
                .where(EvidenceModel.analysis_id == str(analysis_id))
                .order_by(EvidenceModel.start_seconds, EvidenceModel.id)
            ).all()
            return [
                Evidence(
                    uuid.UUID(model.id),
                    uuid.UUID(model.analysis_id),
                    model.kind,
                    model.start_seconds,
                    model.end_seconds,
                    _load_json(model.value_json),
                    model.confidence,
                    model.algorithm,
                    model.eligible_for_llm,
                )
                for model in models
            ]

    def save_access_grant(self, grant: AccessGrant) -> None:
        with session_scope(self._session_factory) as session:
            session.add(
                AccessGrantModel(
                    token_hash=grant.token_hash,
                    analysis_id=str(grant.analysis_id),
                    created_at=grant.created_at,
                    expires_at=grant.expires_at,
                    revoked_at=grant.revoked_at,
                )
            )

    def replace_access_grant(self, grant: AccessGrant) -> None:
        with session_scope(self._session_factory) as session:
            session.execute(
                delete(AccessGrantModel).where(
                    AccessGrantModel.analysis_id == str(grant.analysis_id)
                )
            )
            session.add(
                AccessGrantModel(
                    token_hash=grant.token_hash,
                    analysis_id=str(grant.analysis_id),
                    created_at=grant.created_at,
                    expires_at=grant.expires_at,
                    revoked_at=grant.revoked_at,
                )
            )

    def get_access_grants(self, analysis_id: uuid.UUID) -> list[AccessGrant]:
        with session_scope(self._session_factory) as session:
            models = session.scalars(
                select(AccessGrantModel)
                .where(AccessGrantModel.analysis_id == str(analysis_id))
                .order_by(AccessGrantModel.created_at, AccessGrantModel.token_hash)
            ).all()
            return [
                AccessGrant(
                    uuid.UUID(model.analysis_id),
                    model.token_hash,
                    model.created_at,
                    model.expires_at,
                    model.revoked_at,
                )
                for model in models
            ]

    def prepare_deletion(self, analysis_id: uuid.UUID, revoked_at: datetime) -> None:
        with session_scope(self._session_factory) as session:
            grants = session.scalars(
                select(AccessGrantModel).where(
                    AccessGrantModel.analysis_id == str(analysis_id),
                    AccessGrantModel.revoked_at.is_(None),
                )
            ).all()
            for grant in grants:
                grant.revoked_at = revoked_at
            audio = session.get(EncryptedAudioModel, str(analysis_id))
            if audio is not None:
                audio.wrapped_data_key = b""

    def save_encrypted_audio(self, audio: EncryptedAudio) -> None:
        with session_scope(self._session_factory) as session:
            session.add(
                EncryptedAudioModel(
                    analysis_id=str(audio.analysis_id),
                    cipher_path=audio.cipher_path,
                    wrapped_data_key=audio.wrapped_data_key,
                    chunk_size=audio.chunk_size,
                    chunk_count=audio.chunk_count,
                    plaintext_size=audio.plaintext_size,
                    media_type=audio.media_type,
                    sha256=audio.sha256,
                )
            )

    def get_encrypted_audio(self, analysis_id: uuid.UUID) -> EncryptedAudio | None:
        with session_scope(self._session_factory) as session:
            model = session.get(EncryptedAudioModel, str(analysis_id))
            if model is None:
                return None
            return EncryptedAudio(
                uuid.UUID(model.analysis_id),
                model.cipher_path,
                model.wrapped_data_key,
                model.chunk_size,
                model.chunk_count,
                model.plaintext_size,
                model.media_type,
                model.sha256,
            )

    def destroy_encrypted_audio_key(self, analysis_id: uuid.UUID) -> None:
        with session_scope(self._session_factory) as session:
            model = session.get(EncryptedAudioModel, str(analysis_id))
            if model is not None:
                model.wrapped_data_key = b""

    def delete_encrypted_audio_metadata(self, analysis_id: uuid.UUID) -> None:
        with session_scope(self._session_factory) as session:
            session.execute(
                delete(EncryptedAudioModel).where(
                    EncryptedAudioModel.analysis_id == str(analysis_id)
                )
            )

    def add_explanation(self, explanation: Explanation) -> None:
        with session_scope(self._session_factory) as session:
            track = session.get(TrackAnalysisModel, str(explanation.analysis_id))
            if track is None:
                raise KeyError(str(explanation.analysis_id))
            if explanation.segment_end > track.duration_seconds:
                raise ValueError("explanation interval cannot exceed track duration")
            session.add(
                ExplanationModel(
                    id=str(explanation.id),
                    analysis_id=str(explanation.analysis_id),
                    segment_start=explanation.segment_start,
                    segment_end=explanation.segment_end,
                    question_digest=explanation.question_digest,
                    evidence_ids_json=_dump_json(explanation.evidence_ids_json),
                    mode=explanation.mode,
                    text=explanation.text,
                    created_at=explanation.created_at,
                )
            )

    def get_explanations(self, analysis_id: uuid.UUID) -> list[Explanation]:
        with session_scope(self._session_factory) as session:
            models = session.scalars(
                select(ExplanationModel)
                .where(ExplanationModel.analysis_id == str(analysis_id))
                .order_by(ExplanationModel.created_at, ExplanationModel.id)
            ).all()
            return [
                Explanation(
                    uuid.UUID(model.id),
                    uuid.UUID(model.analysis_id),
                    model.segment_start,
                    model.segment_end,
                    model.question_digest,
                    _load_json(model.evidence_ids_json),
                    model.mode,
                    model.text,
                    model.created_at,
                )
                for model in models
            ]

    def delete_cascade(self, analysis_id: uuid.UUID) -> None:
        with session_scope(self._session_factory) as session:
            session.execute(delete(AnalysisJobModel).where(AnalysisJobModel.id == str(analysis_id)))


def init_db(database_url: str = "sqlite:///data/museecho.db") -> None:
    engine = create_museecho_engine(database_url)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
