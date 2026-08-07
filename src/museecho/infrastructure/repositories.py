from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AnalysisJobModel(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pipeline_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="real")

    track_analysis: Mapped[TrackAnalysisModel | None] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False
    )


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

    job: Mapped[AnalysisJobModel] = relationship(back_populates="track_analysis")


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
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


def init_db(database_url: str = "sqlite:///data/museecho.db") -> None:
    engine = create_engine(database_url, echo=False)
    Base.metadata.create_all(engine)
