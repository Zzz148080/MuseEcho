from __future__ import annotations

import pytest

from museecho_ml.evaluation.metrics import (
    ScoredChordInterval,
    boundary_f1,
    expected_calibration_error,
    precision_coverage,
    quality_f1_report,
    weighted_chord_scores,
)
from museecho_ml.labels import parse_annotation


def _interval(start: float, end: float, chord: str, confidence: float = 1.0) -> ScoredChordInterval:
    return ScoredChordInterval(start, end, parse_annotation(chord), confidence)


def test_weighted_scores_use_time_not_interval_count() -> None:
    reference = (_interval(0, 1, "C:maj"), _interval(1, 3, "G:7"))
    prediction = (_interval(0, 2, "C:maj"), _interval(2, 3, "G:7"))

    scores = weighted_chord_scores(reference, prediction)

    assert scores["root"] == pytest.approx(2 / 3)
    assert scores["exact_quality"] == pytest.approx(2 / 3)


def test_root_score_can_pass_when_quality_is_wrong() -> None:
    reference = (_interval(0, 2, "C:maj"),)
    prediction = (_interval(0, 2, "C:min"),)

    scores = weighted_chord_scores(reference, prediction)

    assert scores["root"] == 1.0
    assert scores["exact_quality"] == 0.0


def test_hierarchical_scores_credit_valid_quality_reductions() -> None:
    reference = (
        _interval(0, 1, "C:maj7"),
        _interval(1, 2, "D:min7"),
        _interval(2, 3, "B:hdim7"),
    )
    prediction = (
        _interval(0, 1, "C:maj"),
        _interval(1, 2, "D:min"),
        _interval(2, 3, "B:dim"),
    )

    scores = weighted_chord_scores(reference, prediction)

    assert scores["root"] == 1.0
    assert scores["majmin"] == 1.0
    assert scores["triads"] == 1.0
    assert scores["sevenths"] == 0.0
    assert scores["exact_quality"] == 0.0


def test_boundary_f1_uses_one_to_one_tolerance_matching() -> None:
    score = boundary_f1(
        reference_boundaries=(1.0, 2.0),
        predicted_boundaries=(1.03, 1.04, 2.2),
        tolerance_seconds=0.05,
    )

    assert score == {"precision": pytest.approx(1 / 3), "recall": 0.5, "f1": 0.4}


def test_expected_calibration_error_is_confidence_weighted_by_duration() -> None:
    samples = ((0.9, True, 1.0), (0.8, False, 1.0), (0.6, True, 2.0))

    assert expected_calibration_error(samples, bin_count=10) == pytest.approx(0.425)


def test_precision_coverage_rejects_low_confidence_predictions() -> None:
    reference = (
        _interval(0, 1, "C:maj"),
        _interval(1, 2, "G:maj"),
        _interval(2, 4, "A:min"),
    )
    prediction = (
        _interval(0, 1, "C:maj", 0.95),
        _interval(1, 2, "D:maj", 0.9),
        _interval(2, 4, "A:min", 0.4),
    )

    result = precision_coverage(reference, prediction, threshold=0.8)

    assert result == {"precision": 0.5, "coverage": 0.5}


def test_quality_f1_is_duration_weighted_and_macro_averaged() -> None:
    reference = (_interval(0, 1, "C:maj"), _interval(1, 3, "D:min"))
    prediction = (_interval(0, 2, "C:maj"), _interval(2, 3, "D:min"))

    report = quality_f1_report(reference, prediction)

    assert report["per_quality"]["maj"] == {
        "precision": 0.5,
        "recall": 1.0,
        "f1": pytest.approx(2 / 3),
        "support_seconds": 1.0,
    }
    assert report["per_quality"]["min"]["f1"] == pytest.approx(2 / 3)
    assert report["macro_f1"] == pytest.approx(2 / 3)
