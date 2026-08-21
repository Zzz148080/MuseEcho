from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from museecho_ml.artifacts import canonical_sha256


@dataclass(frozen=True)
class HybridCalibrationSample:
    cover_group_id: str
    quality: str
    confidence: float
    correct: bool
    duration_seconds: float
    split: str = "calibration"


@dataclass(frozen=True)
class HybridCalibrationParameters:
    global_quality_threshold: float
    quality_thresholds: tuple[tuple[str, float], ...]
    quality_threshold_sources: tuple[tuple[str, str], ...]
    known_threshold: float
    bass_threshold: float
    minimum_support_fraction: float

    def __post_init__(self) -> None:
        values = (
            self.global_quality_threshold,
            self.known_threshold,
            self.bass_threshold,
            self.minimum_support_fraction,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1
            for value in values
        ):
            raise ValueError("hybrid calibration thresholds must be within [0, 1]")
        names = [quality for quality, _ in self.quality_thresholds]
        source_names = [quality for quality, _ in self.quality_threshold_sources]
        if (
            len(set(names)) != len(names)
            or len(set(source_names)) != len(source_names)
            or set(names) != set(source_names)
            or any(not isinstance(quality, str) or not quality for quality in names)
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1
                for _, value in self.quality_thresholds
            )
            or any(
                source not in {"quality-specific", "global-insufficient-groups"}
                for _, source in self.quality_threshold_sources
            )
        ):
            raise ValueError("hybrid calibration quality thresholds are invalid")

    def threshold_for(self, quality: str) -> float:
        return dict(self.quality_thresholds).get(
            quality, self.global_quality_threshold
        )

    def source_for(self, quality: str) -> str:
        return dict(self.quality_threshold_sources).get(
            quality, "global-insufficient-groups"
        )

    def to_dict(self) -> dict[str, Any]:
        body = {
            "schema_version": 1,
            "calibration_version": "hybrid-calibration-v1",
            "global_quality_threshold": float(self.global_quality_threshold),
            "quality_thresholds": [list(item) for item in self.quality_thresholds],
            "quality_threshold_sources": [
                list(item) for item in self.quality_threshold_sources
            ],
            "known_threshold": float(self.known_threshold),
            "bass_threshold": float(self.bass_threshold),
            "minimum_support_fraction": float(self.minimum_support_fraction),
        }
        return {**body, "calibration_sha256": canonical_sha256(body)}

    @classmethod
    def from_dict(cls, value: Any) -> HybridCalibrationParameters:
        if not isinstance(value, dict):
            raise ValueError("hybrid calibration parameters must be an object")
        body = dict(value)
        embedded_hash = body.pop("calibration_sha256", None)
        if not isinstance(embedded_hash, str) or canonical_sha256(body) != embedded_hash:
            raise ValueError("hybrid calibration SHA-256 mismatch")
        if body.pop("schema_version", None) != 1 or body.pop(
            "calibration_version", None
        ) != "hybrid-calibration-v1":
            raise ValueError("hybrid calibration version is unsupported")
        try:
            body["quality_thresholds"] = tuple(
                (str(quality), float(threshold))
                for quality, threshold in body["quality_thresholds"]
            )
            body["quality_threshold_sources"] = tuple(
                (str(quality), str(source))
                for quality, source in body["quality_threshold_sources"]
            )
            return cls(**body)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("hybrid calibration fields are invalid") from error


def fit_hybrid_calibration(
    samples: Sequence[HybridCalibrationSample],
    *,
    minimum_precision: float,
    minimum_coverage: float,
    minimum_quality_groups: int,
) -> HybridCalibrationParameters:
    evidence = _validated_calibration_samples(samples)
    _validate_gate(minimum_precision, "precision")
    _validate_gate(minimum_coverage, "coverage")
    if type(minimum_quality_groups) is not int or minimum_quality_groups <= 0:
        raise ValueError("minimum quality groups must be a positive integer")
    global_threshold = _precision_first_threshold(
        evidence,
        minimum_precision=minimum_precision,
        minimum_coverage=minimum_coverage,
    )
    thresholds: list[tuple[str, float]] = []
    sources: list[tuple[str, str]] = []
    for quality in sorted({sample.quality for sample in evidence}):
        subset = tuple(sample for sample in evidence if sample.quality == quality)
        if len({sample.cover_group_id for sample in subset}) < minimum_quality_groups:
            thresholds.append((quality, global_threshold))
            sources.append((quality, "global-insufficient-groups"))
            continue
        thresholds.append(
            (
                quality,
                _precision_first_threshold(
                    subset,
                    minimum_precision=minimum_precision,
                    minimum_coverage=minimum_coverage,
                ),
            )
        )
        sources.append((quality, "quality-specific"))
    return HybridCalibrationParameters(
        global_quality_threshold=global_threshold,
        quality_thresholds=tuple(thresholds),
        quality_threshold_sources=tuple(sources),
        known_threshold=global_threshold,
        bass_threshold=global_threshold,
        minimum_support_fraction=0.6,
    )


def _validated_calibration_samples(
    samples: Sequence[HybridCalibrationSample],
) -> tuple[HybridCalibrationSample, ...]:
    if not isinstance(samples, Sequence) or not samples:
        raise ValueError("hybrid calibration samples cannot be empty")
    validated: list[HybridCalibrationSample] = []
    for sample in samples:
        if not isinstance(sample, HybridCalibrationSample):
            raise ValueError("hybrid calibration sample type is invalid")
        if sample.split != "calibration":
            raise ValueError("hybrid calibration requires calibration split")
        if (
            not sample.cover_group_id
            or not sample.quality
            or not math.isfinite(sample.confidence)
            or not 0 <= sample.confidence <= 1
            or type(sample.correct) is not bool
            or not math.isfinite(sample.duration_seconds)
            or sample.duration_seconds <= 0
        ):
            raise ValueError("hybrid calibration sample is invalid")
        validated.append(sample)
    return tuple(
        sorted(
            validated,
            key=lambda item: (
                item.quality,
                item.cover_group_id,
                -item.confidence,
                not item.correct,
                item.duration_seconds,
            ),
        )
    )


def _validate_gate(value: float, name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError(f"minimum {name} must be within [0, 1]")


def _precision_first_threshold(
    samples: Sequence[HybridCalibrationSample],
    *,
    minimum_precision: float,
    minimum_coverage: float,
) -> float:
    total_duration = sum(sample.duration_seconds for sample in samples)

    def score(threshold: float) -> tuple[bool, float, float, float, float]:
        selected = [sample for sample in samples if sample.confidence >= threshold]
        selected_duration = sum(sample.duration_seconds for sample in selected)
        correct_duration = sum(
            sample.duration_seconds for sample in selected if sample.correct
        )
        precision = correct_duration / selected_duration
        coverage = selected_duration / total_duration
        return (
            precision >= minimum_precision and coverage >= minimum_coverage,
            precision,
            coverage,
            correct_duration,
            threshold,
        )

    candidates = sorted({sample.confidence for sample in samples})
    return float(max(candidates, key=score))
