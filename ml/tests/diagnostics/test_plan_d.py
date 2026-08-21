from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from museecho_ml.artifacts import canonical_sha256
from museecho_ml.diagnostics.plan_d import (
    PlanDAuditTrack,
    audit_frame_alignment,
    build_plan_d_failure_audit,
)
from museecho_ml.evaluation.metrics import ScoredChordInterval
from museecho_ml.labels import CanonicalChord, parse_annotation


def _interval(start: float, end: float, symbol: str, confidence: float = 1.0):
    return ScoredChordInterval(start, end, parse_annotation(symbol), confidence)


def _audit_track(
    *,
    track_id: str = "fixture",
    dataset_id: str = "dataset-a",
    group: str = "g1",
    seed: int | None = 20260821,
    split: str = "validation",
    frame_times: np.ndarray | None = None,
    reference: tuple[ScoredChordInterval, ...] | None = None,
    prediction: tuple[ScoredChordInterval, ...] | None = None,
) -> PlanDAuditTrack:
    return PlanDAuditTrack(
        track_id=track_id,
        dataset_id=dataset_id,
        cover_group_id=group,
        split=split,
        duration_seconds=2.0,
        frame_times=(
            np.asarray(frame_times, dtype=np.float64)
            if frame_times is not None
            else np.array([0.0, 0.5, 1.0, 1.5], dtype=np.float64)
        ),
        reference=reference
        or (_interval(0.0, 1.0, "C:maj"), _interval(1.0, 2.0, "D:min")),
        prediction=prediction
        or (_interval(0.0, 1.0, "C:maj"), _interval(1.0, 2.0, "D:min")),
        seed=seed,
    )


def test_audit_finds_boundary_offset_and_duration_weighted_quality_confusion() -> None:
    track = _audit_track(
        prediction=(
            _interval(0.0, 1.5, "C:maj", 0.8),
            _interval(1.5, 2.0, "D:maj", 0.6),
        )
    )

    report = build_plan_d_failure_audit(
        (track,), supported_qualities=("maj", "min")
    )

    assert report["alignment"]["maximum_boundary_frame_error_seconds"] == 0.0
    assert report["quality_confusion_seconds"]["min"]["maj"] == 0.5
    assert report["event_counts"] == {
        "prediction": 2,
        "reference": 2,
        "ratio": 1.0,
    }
    assert report["confidence_curve"]["duration_seconds"] == 2.0
    body = dict(report)
    embedded = body.pop("audit_sha256")
    assert canonical_sha256(body) == embedded


def test_alignment_infers_terminal_frame_edge_and_reports_real_offset() -> None:
    aligned = audit_frame_alignment(
        np.array([0.0, 0.5, 1.0, 1.5]),
        (_interval(0.0, 1.0, "C:maj"), _interval(1.0, 2.0, "D:min")),
    )
    shifted = audit_frame_alignment(
        np.array([0.1, 0.6, 1.1, 1.6]),
        (_interval(0.0, 1.0, "C:maj"), _interval(1.0, 2.0, "D:min")),
    )

    assert aligned == {
        "maximum_boundary_frame_error_seconds": 0.0,
        "mean_boundary_frame_error_seconds": 0.0,
    }
    assert shifted["maximum_boundary_frame_error_seconds"] == pytest.approx(0.1)


def test_audit_counts_independent_groups_and_stratifies_dataset_and_seed() -> None:
    first = _audit_track(group="g1", seed=20260821)
    second = _audit_track(
        track_id="fixture-2", dataset_id="dataset-b", group="g2", seed=20260822
    )

    report = build_plan_d_failure_audit(
        (second, first), supported_qualities=("maj", "min")
    )

    assert report["quality_support"]["min"]["cover_groups"] == 2
    assert list(report["datasets"]) == ["dataset-a", "dataset-b"]
    assert list(report["seeds"]) == ["20260821", "20260822"]
    assert report["cover_group_count"] == 2


def test_audit_rejects_test_overlap_missing_group_and_illegal_chord_state() -> None:
    base = _audit_track()
    with pytest.raises(ValueError, match="forbids test split"):
        build_plan_d_failure_audit(
            (replace(base, split="test"),), supported_qualities=("maj", "min")
        )
    with pytest.raises(ValueError, match="cover group"):
        build_plan_d_failure_audit(
            (replace(base, cover_group_id=""),), supported_qualities=("maj", "min")
        )

    overlap = (
        _interval(0.0, 1.5, "C:maj"),
        _interval(1.0, 2.0, "D:min"),
    )
    with pytest.raises(ValueError, match="overlap"):
        build_plan_d_failure_audit(
            (replace(base, prediction=overlap),), supported_qualities=("maj", "min")
        )

    illegal = ScoredChordInterval(
        0.0,
        2.0,
        CanonicalChord("C", "N", "1"),
    )
    with pytest.raises(ValueError, match="illegal chord state"):
        build_plan_d_failure_audit(
            (replace(base, prediction=(illegal,)),), supported_qualities=("maj", "min")
        )
