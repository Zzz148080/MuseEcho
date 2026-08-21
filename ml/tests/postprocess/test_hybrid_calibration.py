from __future__ import annotations

from dataclasses import replace

import pytest

from museecho_ml.artifacts import canonical_json_bytes
from museecho_ml.postprocess.hybrid_calibration import (
    HybridCalibrationParameters,
    HybridCalibrationSample,
    fit_hybrid_calibration,
)


def _sample(
    group: str,
    confidence: float,
    correct: bool,
    *,
    quality: str = "min7",
    split: str = "calibration",
    duration: float = 1.0,
) -> HybridCalibrationSample:
    return HybridCalibrationSample(
        cover_group_id=group,
        quality=quality,
        confidence=confidence,
        correct=correct,
        duration_seconds=duration,
        split=split,
    )


def test_quality_threshold_requires_independent_group_support() -> None:
    samples = (
        _sample("g1", 0.95, True),
        _sample("g1", 0.8, False),
        _sample("g2", 0.7, True),
    )

    result = fit_hybrid_calibration(
        samples,
        minimum_precision=0.6,
        minimum_coverage=0.2,
        minimum_quality_groups=3,
    )

    assert result.threshold_for("min7") == result.global_quality_threshold
    assert result.source_for("min7") == "global-insufficient-groups"


def test_quality_specific_threshold_is_precision_first_and_duration_weighted() -> None:
    samples = (
        _sample("g1", 0.95, True, duration=2.0),
        _sample("g2", 0.9, True, duration=2.0),
        _sample("g3", 0.7, False, duration=2.0),
        _sample("g4", 0.6, False, duration=2.0),
    )

    result = fit_hybrid_calibration(
        samples,
        minimum_precision=0.8,
        minimum_coverage=0.5,
        minimum_quality_groups=3,
    )

    assert result.threshold_for("min7") == 0.9
    assert result.source_for("min7") == "quality-specific"


def test_calibration_rejects_non_calibration_split_and_non_finite_values() -> None:
    with pytest.raises(ValueError, match="calibration split"):
        fit_hybrid_calibration(
            (_sample("g1", 0.9, True, split="validation"),),
            minimum_precision=0.6,
            minimum_coverage=0.2,
            minimum_quality_groups=1,
        )
    with pytest.raises(ValueError, match="sample"):
        fit_hybrid_calibration(
            (_sample("g1", float("nan"), True),),
            minimum_precision=0.6,
            minimum_coverage=0.2,
            minimum_quality_groups=1,
        )


def test_calibration_round_trip_rejects_hash_drift_and_is_order_independent() -> None:
    samples = (
        _sample("g1", 0.95, True),
        _sample("g2", 0.9, True),
        _sample("g3", 0.7, False),
    )
    first = fit_hybrid_calibration(
        samples,
        minimum_precision=0.6,
        minimum_coverage=0.5,
        minimum_quality_groups=3,
    )
    second = fit_hybrid_calibration(
        tuple(reversed(samples)),
        minimum_precision=0.6,
        minimum_coverage=0.5,
        minimum_quality_groups=3,
    )

    assert canonical_json_bytes(first.to_dict()) == canonical_json_bytes(
        second.to_dict()
    )
    assert HybridCalibrationParameters.from_dict(first.to_dict()) == first
    drifted = first.to_dict()
    drifted["known_threshold"] = 0.0
    with pytest.raises(ValueError, match="SHA-256"):
        HybridCalibrationParameters.from_dict(drifted)


def test_calibration_parameter_validation_rejects_duplicate_quality() -> None:
    with pytest.raises(ValueError, match="quality thresholds"):
        replace(
            HybridCalibrationParameters(
                global_quality_threshold=0.8,
                quality_thresholds=(("maj", 0.8),),
                quality_threshold_sources=(("maj", "quality-specific"),),
                known_threshold=0.8,
                bass_threshold=0.8,
                minimum_support_fraction=0.6,
            ),
            quality_thresholds=(("maj", 0.8), ("maj", 0.9)),
        )
