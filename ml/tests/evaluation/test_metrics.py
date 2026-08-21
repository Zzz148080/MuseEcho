from __future__ import annotations

import json
from pathlib import Path

import pytest

from museecho_ml.evaluation.metrics import (
    ScoredChordInterval,
    boundary_f1,
    expected_calibration_error,
    precision_coverage,
    quality_f1_report,
    weighted_chord_scores,
)
from museecho_ml.evaluation.report import (
    EvaluationConfig,
    evaluate_corpus,
    evaluate_track,
)
from museecho_ml.labels import parse_annotation

ML_ROOT = Path(__file__).resolve().parents[2]


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


def test_metrics_reject_prediction_gaps_instead_of_inflating_scores() -> None:
    reference = (_interval(0, 2, "C:maj"),)
    prediction = (_interval(0, 1, "C:maj"), _interval(1.5, 2, "C:maj"))

    with pytest.raises(ValueError, match="continuous"):
        weighted_chord_scores(reference, prediction)


def test_track_report_combines_versioned_metrics_deterministically() -> None:
    reference = (_interval(0, 1, "C:maj"), _interval(1, 2, "G:7"))
    prediction = (
        _interval(0, 1, "C:maj", 0.9),
        _interval(1, 2, "D:7", 0.8),
    )
    config = EvaluationConfig(
        boundary_tolerance_seconds=0.05,
        ece_bin_count=10,
        publication_threshold=0.85,
    )

    first = evaluate_track("fixture-track", reference, prediction, config)
    second = evaluate_track("fixture-track", reference, prediction, config)

    assert first == second
    assert first["track_id"] == "fixture-track"
    assert first["weighted_scores"]["exact_quality"] == 0.5
    assert first["boundary"]["f1"] == 1.0
    assert first["segmentation"] == {"reference_events": 2, "predicted_events": 2}
    assert first["published"] == {"precision": 1.0, "coverage": 0.5}


def test_corpus_report_pools_duration_without_scoring_track_seams() -> None:
    config = EvaluationConfig(
        boundary_tolerance_seconds=0.05,
        ece_bin_count=10,
        publication_threshold=0.85,
    )
    tracks = {
        "short-correct": (
            (_interval(0, 1, "C:maj"),),
            (_interval(0, 1, "C:maj", 0.9),),
        ),
        "long-wrong": (
            (_interval(0, 1, "C:maj"), _interval(1, 3, "G:maj")),
            (_interval(0, 3, "D:maj", 0.9),),
        ),
    }

    report = evaluate_corpus(tracks, config)

    assert report["track_count"] == 2
    assert report["duration_seconds"] == 4.0
    assert report["aggregate"]["weighted_scores"]["exact_quality"] == 0.25
    assert report["aggregate"]["boundary"] == {
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
    }
    assert sorted(report["tracks"]) == ["long-wrong", "short-correct"]


def test_evaluation_config_matches_versioned_file() -> None:
    payload = json.loads(
        (ML_ROOT / "configs" / "evaluation-v1.json").read_text(encoding="utf-8")
    )

    assert payload == {
        "schema_version": 1,
        "evaluation_version": "1.0.0",
        "boundary_tolerance_seconds": 0.05,
        "ece_bin_count": 15,
        "publication_threshold": 0.85,
        "exact_match_includes_bass": False,
    }


def test_evaluation_config_validates_plan_c_public_quality_labels() -> None:
    config = EvaluationConfig(public_quality_labels=("maj", "min", "7"))

    assert config.public_quality_labels == ("maj", "min", "7")
    with pytest.raises(ValueError, match="public quality labels"):
        EvaluationConfig(public_quality_labels=("maj", "maj"))
    with pytest.raises(ValueError, match="public quality labels"):
        EvaluationConfig(public_quality_labels=("maj", "N"))
