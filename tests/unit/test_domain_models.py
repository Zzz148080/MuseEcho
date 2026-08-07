from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from museecho.domain.models import (
    AccessGrant,
    AnalysisResult,
    ChordEvent,
    Evidence,
    SectionEvent,
    TimeSeries,
    TrackAnalysis,
)


def test_section_rejects_empty_or_backwards_interval():
    with pytest.raises(ValueError, match="interval"):
        SectionEvent(
            id=uuid.uuid4(),
            analysis_id=uuid.uuid4(),
            start_seconds=5.0,
            end_seconds=2.0,
            label="invalid",
            confidence=0.8,
            algorithm="test",
        )


def test_evidence_rejects_confidence_outside_unit_interval():
    with pytest.raises(ValueError, match="confidence"):
        Evidence(
            id=uuid.uuid4(),
            analysis_id=uuid.uuid4(),
            kind="key",
            start_seconds=0.0,
            end_seconds=1.0,
            value_json={"tonic": "C"},
            confidence=1.5,
            algorithm="test",
            eligible_for_llm=True,
        )


def test_track_rejects_invalid_duration_and_optional_confidence():
    with pytest.raises(ValueError, match="duration_seconds"):
        TrackAnalysis(
            analysis_id=uuid.uuid4(),
            duration_seconds=0.0,
            sample_rate=44_100,
            channels=2,
            bpm=None,
            bpm_confidence=None,
            key_tonic=None,
            mode=None,
            key_confidence=None,
            time_signature=None,
            time_signature_confidence=None,
            summary_json=None,
        )


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_models_reject_non_finite_numeric_values(invalid: float):
    analysis_id = uuid.uuid4()
    with pytest.raises(ValueError, match="finite"):
        TrackAnalysis(
            analysis_id=analysis_id,
            duration_seconds=invalid,
            sample_rate=44_100,
            channels=2,
            bpm=None,
            bpm_confidence=None,
            key_tonic=None,
            mode=None,
            key_confidence=None,
            time_signature=None,
            time_signature_confidence=None,
            summary_json=None,
        )

    with pytest.raises(ValueError, match="finite"):
        SectionEvent(uuid.uuid4(), analysis_id, invalid, 2.0, "A", 0.8, "test")

    with pytest.raises(ValueError, match="finite"):
        TimeSeries(analysis_id, "energy", 0.5, [0.1, invalid], "test")


def test_analysis_result_rejects_mismatched_or_out_of_bounds_children():
    analysis_id = uuid.uuid4()
    track = TrackAnalysis(
        analysis_id=analysis_id,
        duration_seconds=4.0,
        sample_rate=44_100,
        channels=1,
        bpm=None,
        bpm_confidence=None,
        key_tonic=None,
        mode=None,
        key_confidence=None,
        time_signature=None,
        time_signature_confidence=None,
        summary_json=None,
    )
    out_of_bounds = ChordEvent(uuid.uuid4(), analysis_id, 3.0, 5.0, "C", 0.8, "test", None)

    with pytest.raises(ValueError, match="duration"):
        AnalysisResult(track=track, chords=(out_of_bounds,))

    wrong_analysis = SectionEvent(uuid.uuid4(), uuid.uuid4(), 0.0, 1.0, "A", 0.8, "test")
    with pytest.raises(ValueError, match="analysis_id"):
        AnalysisResult(track=track, sections=(wrong_analysis,))

    with pytest.raises(ValueError, match="bpm_confidence"):
        TrackAnalysis(
            analysis_id=uuid.uuid4(),
            duration_seconds=10.0,
            sample_rate=44_100,
            channels=2,
            bpm=120.0,
            bpm_confidence=-0.1,
            key_tonic=None,
            mode=None,
            key_confidence=None,
            time_signature=None,
            time_signature_confidence=None,
            summary_json=None,
        )


def test_access_grant_rejects_revocation_before_creation():
    created_at = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="revoked_at"):
        AccessGrant(
            uuid.uuid4(),
            "hash",
            created_at,
            created_at + timedelta(hours=1),
            created_at - timedelta(seconds=1),
        )


def test_domain_json_rejects_nested_non_finite_values():
    with pytest.raises(ValueError, match="JSON"):
        TrackAnalysis(
            analysis_id=uuid.uuid4(),
            duration_seconds=10.0,
            sample_rate=44_100,
            channels=2,
            bpm=None,
            bpm_confidence=None,
            key_tonic=None,
            mode=None,
            key_confidence=None,
            time_signature=None,
            time_signature_confidence=None,
            summary_json={"nested": {"value": float("nan")}},
        )
