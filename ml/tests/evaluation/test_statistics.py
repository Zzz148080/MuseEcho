from __future__ import annotations

from copy import deepcopy

import pytest

from museecho_ml.artifacts import canonical_json_bytes
from museecho_ml.evaluation.metrics import ScoredChordInterval
from museecho_ml.evaluation.report import EvaluationConfig
from museecho_ml.evaluation.statistics import (
    dataset_macro,
    evaluate_dataset_strata,
    group_bootstrap_ci,
)
from museecho_ml.labels import parse_annotation


def _metrics(exact: float) -> dict[str, float]:
    return {
        "exact_vocabulary_wcsr": exact,
        "public_quality_macro_f1": exact,
        "published_known_precision": exact,
        "coverage": exact,
        "ece": 1.0 - exact,
        "majmin_wcsr": exact,
        "seventh_quality_macro_f1": exact,
    }


def _group_reports() -> dict[str, list[dict]]:
    return {
        "group-a": [
            {
                "track_id": "track-a1",
                "dataset_id": "guitarset",
                "split": "validation",
                "duration_seconds": 1.0,
                **_metrics(0.9),
            },
            {
                "track_id": "track-a2",
                "dataset_id": "guitarset",
                "split": "validation",
                "duration_seconds": 3.0,
                **_metrics(0.3),
            },
        ],
        "group-b": [
            {
                "track_id": "track-b1",
                "dataset_id": "rwc-popular",
                "split": "validation",
                "duration_seconds": 2.0,
                **_metrics(0.6),
            }
        ],
    }


def _interval(
    start: float, end: float, chord: str, confidence: float = 0.9
) -> ScoredChordInterval:
    return ScoredChordInterval(start, end, parse_annotation(chord), confidence)


def test_dataset_macro_weights_three_sources_equally() -> None:
    report = dataset_macro(
        {
            "guitarset": _metrics(0.9),
            "rwc-popular": _metrics(0.6),
            "schubert-winterreise": _metrics(0.3),
        }
    )

    assert report["exact_vocabulary_wcsr"] == pytest.approx(0.6)
    assert report["coverage"] == pytest.approx(0.6)
    assert report["ece"] == pytest.approx(0.4)


def test_bootstrap_resamples_whole_groups_and_is_byte_reproducible() -> None:
    first = group_bootstrap_ci(_group_reports(), resamples=10_000, seed=20260821)
    second = group_bootstrap_ci(
        dict(reversed(list(_group_reports().items()))),
        resamples=10_000,
        seed=20260821,
    )

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert first["unit"] == "cover_group_id"
    assert first["group_count"] == 2
    assert first["resamples"] == 10_000
    assert first["metrics"]["exact_vocabulary_wcsr"]["point_estimate"] == (
        pytest.approx(0.5)
    )
    assert first["metrics"]["exact_vocabulary_wcsr"]["lower"] == pytest.approx(
        0.45
    )
    assert first["metrics"]["exact_vocabulary_wcsr"]["upper"] == pytest.approx(
        0.6
    )


def test_dataset_strata_keeps_datasets_separate_and_adds_schema_v2_wrapper() -> None:
    tracks = {
        "guitarset:a": (
            (_interval(0, 1, "C:maj"),),
            (_interval(0, 1, "C:maj"),),
        ),
        "rwc-popular:b": (
            (_interval(0, 1, "D:min"),),
            (_interval(0, 1, "D:min"),),
        ),
        "schubert-winterreise:c": (
            (_interval(0, 1, "C:maj"),),
            (_interval(0, 1, "D:min"),),
        ),
    }
    metadata = {
        track_id: {
            "dataset_id": track_id.split(":", 1)[0],
            "cover_group_id": f"group-{index}",
            "split": "validation",
        }
        for index, track_id in enumerate(tracks)
    }
    config = EvaluationConfig(public_quality_labels=("maj", "min"))

    report = evaluate_dataset_strata(tracks, metadata, config)

    assert report["schema_version"] == 2
    assert set(report["datasets"]) == {
        "guitarset",
        "rwc-popular",
        "schubert-winterreise",
    }
    assert report["aggregate"]["weighted_scores"]["exact_quality"] == pytest.approx(
        2 / 3
    )
    assert set(report["tracks"]) == set(tracks)
    assert report["dataset_macro"]["exact_vocabulary_wcsr"] == pytest.approx(2 / 3)
    assert report["bootstrap"]["group_count"] == 3


def test_missing_public_quality_support_is_explicit() -> None:
    tracks = {
        "guitarset:a": (
            (_interval(0, 1, "C:maj"),),
            (_interval(0, 1, "C:maj"),),
        ),
        "guitarset:b": (
            (_interval(0, 1, "C:maj"),),
            (_interval(0, 1, "C:maj"),),
        ),
    }
    metadata = {
        track_id: {
            "dataset_id": "guitarset",
            "cover_group_id": track_id,
            "split": "validation",
        }
        for track_id in tracks
    }

    report = evaluate_dataset_strata(
        tracks,
        metadata,
        EvaluationConfig(public_quality_labels=("maj", "min")),
    )

    assert report["datasets"]["guitarset"]["scalars"][
        "public_quality_macro_f1"
    ] is None
    assert report["datasets"]["guitarset"]["missing_public_quality_support"] == [
        "min"
    ]
    assert report["dataset_macro"]["status"] == "unavailable"
    assert report["bootstrap"]["quality_support_status"] == "incomplete"


def test_bootstrap_rejects_invalid_groups_and_track_assignments() -> None:
    with pytest.raises(ValueError, match="at least two"):
        group_bootstrap_ci({"only": _group_reports()["group-a"]})
    with pytest.raises(ValueError, match="non-empty"):
        group_bootstrap_ci({"a": [], "b": _group_reports()["group-b"]})
    duplicate = _group_reports()
    duplicate["group-b"][0]["track_id"] = "track-a1"
    with pytest.raises(ValueError, match="duplicate track"):
        group_bootstrap_ci(duplicate)
    non_finite = deepcopy(_group_reports())
    non_finite["group-a"][0]["coverage"] = float("inf")
    with pytest.raises(ValueError, match="finite"):
        group_bootstrap_ci(non_finite)
    with pytest.raises(ValueError, match="resamples"):
        group_bootstrap_ci(_group_reports(), resamples=0)


def test_metadata_rejects_cover_group_crossing_frozen_splits() -> None:
    tracks = {
        "a": ((_interval(0, 1, "C:maj"),), (_interval(0, 1, "C:maj"),)),
        "b": ((_interval(0, 1, "C:maj"),), (_interval(0, 1, "C:maj"),)),
    }
    metadata = {
        "a": {
            "dataset_id": "guitarset",
            "cover_group_id": "same-group",
            "split": "validation",
        },
        "b": {
            "dataset_id": "guitarset",
            "cover_group_id": "same-group",
            "split": "test",
        },
    }

    with pytest.raises(ValueError, match="multiple frozen splits"):
        evaluate_dataset_strata(tracks, metadata, EvaluationConfig())


def test_metadata_rejects_dataset_outside_frozen_plan_c_sources() -> None:
    tracks = {
        "a": ((_interval(0, 1, "C:maj"),), (_interval(0, 1, "C:maj"),)),
        "b": ((_interval(0, 1, "C:maj"),), (_interval(0, 1, "C:maj"),)),
    }
    metadata = {
        track_id: {
            "dataset_id": "unknown-corpus",
            "cover_group_id": track_id,
            "split": "validation",
        }
        for track_id in tracks
    }

    with pytest.raises(ValueError, match="unknown dataset"):
        evaluate_dataset_strata(tracks, metadata, EvaluationConfig())
