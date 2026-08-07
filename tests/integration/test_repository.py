from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from museecho.infrastructure.repositories import (
    AnalysisJobModel,
    Base,
    ChordEventModel,
    TrackAnalysisModel,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)
    s = session_factory()
    yield s
    s.close()


def test_create_and_retrieve_job(session: Session):
    now = datetime.now(timezone.utc)
    job = AnalysisJobModel(
        id=str(uuid.uuid4()),
        status="queued",
        stage="queued",
        progress=0.0,
        created_at=now,
        updated_at=now,
        source_kind="real",
    )
    session.add(job)
    session.commit()

    retrieved = session.get(AnalysisJobModel, job.id)
    assert retrieved is not None
    assert retrieved.status == "queued"
    assert retrieved.source_kind == "real"


def test_cascade_delete_job_removes_children(session: Session):
    now = datetime.now(timezone.utc)
    analysis_id = str(uuid.uuid4())

    job = AnalysisJobModel(
        id=analysis_id,
        status="complete",
        stage="complete",
        progress=1.0,
        created_at=now,
        updated_at=now,
        source_kind="real",
    )
    session.add(job)

    track = TrackAnalysisModel(
        analysis_id=analysis_id,
        duration_seconds=120.0,
        sample_rate=44100,
        channels=2,
    )
    session.add(track)
    session.commit()

    session.delete(job)
    session.commit()

    assert session.get(TrackAnalysisModel, analysis_id) is None


def test_job_status_transition_persists(session: Session):
    now = datetime.now(timezone.utc)
    job = AnalysisJobModel(
        id=str(uuid.uuid4()),
        status="queued",
        stage="queued",
        progress=0.0,
        created_at=now,
        updated_at=now,
        source_kind="real",
    )
    session.add(job)
    session.commit()

    job.status = "validating"
    job.stage = "validating"
    job.progress = 0.125
    job.updated_at = datetime.now(timezone.utc)
    session.commit()

    retrieved = session.get(AnalysisJobModel, job.id)
    assert retrieved is not None
    assert retrieved.status == "validating"
    assert retrieved.progress == 0.125


def test_round_trip_chord_event(session: Session):
    now = datetime.now(timezone.utc)
    analysis_id = str(uuid.uuid4())

    job = AnalysisJobModel(
        id=analysis_id,
        status="queued",
        stage="queued",
        progress=0.0,
        created_at=now,
        updated_at=now,
        source_kind="real",
    )
    session.add(job)

    chord = ChordEventModel(
        id=str(uuid.uuid4()),
        analysis_id=analysis_id,
        start_seconds=0.0,
        end_seconds=4.0,
        symbol="C",
        confidence=0.95,
        algorithm="template_match",
        theory_json='{"pitch_classes": ["C", "E", "G"]}',
    )
    session.add(chord)
    session.commit()

    chords = session.query(ChordEventModel).filter_by(analysis_id=analysis_id).all()
    assert len(chords) == 1
    assert chords[0].symbol == "C"
