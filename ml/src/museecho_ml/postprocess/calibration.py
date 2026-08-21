from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from museecho_ml.artifacts import canonical_sha256


@dataclass(frozen=True)
class CalibrationParameters:
    root_temperature: float
    quality_temperature: float
    bass_temperature: float
    publication_threshold: float
    boundary_threshold: float
    minimum_event_seconds: float

    def __post_init__(self) -> None:
        temperatures = (
            self.root_temperature,
            self.quality_temperature,
            self.bass_temperature,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
            for value in temperatures
        ):
            raise ValueError("calibration temperatures must be finite and positive")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1
            for value in (self.publication_threshold, self.boundary_threshold)
        ):
            raise ValueError("calibration thresholds must be within [0, 1]")
        if (
            isinstance(self.minimum_event_seconds, bool)
            or not isinstance(self.minimum_event_seconds, (int, float))
            or not math.isfinite(self.minimum_event_seconds)
            or self.minimum_event_seconds < 0
        ):
            raise ValueError("minimum event duration must be finite and non-negative")

    def to_dict(self) -> dict[str, Any]:
        body = {
            "schema_version": 1,
            "calibration_version": "temperature-threshold-v1",
            "root_temperature": float(self.root_temperature),
            "quality_temperature": float(self.quality_temperature),
            "bass_temperature": float(self.bass_temperature),
            "publication_threshold": float(self.publication_threshold),
            "boundary_threshold": float(self.boundary_threshold),
            "minimum_event_seconds": float(self.minimum_event_seconds),
        }
        return {**body, "calibration_sha256": canonical_sha256(body)}

    @classmethod
    def from_dict(cls, value: Any) -> CalibrationParameters:
        if not isinstance(value, dict):
            raise ValueError("calibration parameters must be an object")
        body = dict(value)
        embedded_hash = body.pop("calibration_sha256", None)
        if not isinstance(embedded_hash, str) or canonical_sha256(body) != embedded_hash:
            raise ValueError("calibration SHA-256 does not match")
        if body.pop("schema_version", None) != 1 or body.pop(
            "calibration_version", None
        ) != "temperature-threshold-v1":
            raise ValueError("calibration parameter version is unsupported")
        try:
            return cls(**body)
        except TypeError as error:
            raise ValueError("calibration parameter fields are invalid") from error


def multiclass_nll(
    logits: NDArray[np.floating],
    targets: NDArray[np.integer],
    *,
    temperature: float,
    mask: NDArray[np.bool_] | None = None,
) -> float:
    selected_logits, selected_targets = _validated_examples(logits, targets, mask)
    if (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float))
        or not math.isfinite(temperature)
        or temperature <= 0
    ):
        raise ValueError("temperature must be finite and positive")
    scaled = selected_logits / float(temperature)
    maximum = np.max(scaled, axis=1, keepdims=True)
    log_normalizer = maximum[:, 0] + np.log(
        np.exp(scaled - maximum).sum(axis=1)
    )
    selected = scaled[np.arange(len(scaled)), selected_targets]
    return float(np.mean(log_normalizer - selected))


def fit_temperature(
    logits: NDArray[np.floating],
    targets: NDArray[np.integer],
    *,
    mask: NDArray[np.bool_] | None = None,
) -> float:
    _validated_examples(logits, targets, mask)
    candidates = np.unique(
        np.concatenate((np.geomspace(0.25, 8.0, num=97), np.asarray([1.0])))
    )
    return float(
        min(
            candidates,
            key=lambda value: (
                multiclass_nll(logits, targets, temperature=float(value), mask=mask),
                float(value),
            ),
        )
    )


def select_publication_threshold(
    *,
    confidences: NDArray[np.floating],
    correct: NDArray[np.bool_],
    durations: NDArray[np.floating],
    minimum_precision: float,
    minimum_coverage: float,
) -> float:
    confidence = np.asarray(confidences, dtype=np.float64)
    correctness = np.asarray(correct)
    weights = np.asarray(durations, dtype=np.float64)
    if (
        confidence.ndim != 1
        or correctness.dtype != np.bool_
        or correctness.shape != confidence.shape
        or weights.shape != confidence.shape
        or not len(confidence)
        or not np.isfinite(confidence).all()
        or not np.isfinite(weights).all()
        or np.any((confidence < 0) | (confidence > 1))
        or np.any(weights <= 0)
    ):
        raise ValueError("publication threshold evidence is invalid")
    for value, name in (
        (minimum_precision, "precision"),
        (minimum_coverage, "coverage"),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            raise ValueError(f"minimum {name} must be within [0, 1]")
    total_duration = float(weights.sum())
    candidates = sorted((float(value) for value in np.unique(confidence)), reverse=True)
    for threshold in candidates:
        selected = confidence >= threshold
        selected_duration = float(weights[selected].sum())
        coverage = selected_duration / total_duration
        precision = (
            float(weights[selected & correctness].sum()) / selected_duration
            if selected_duration
            else 0.0
        )
        if precision >= minimum_precision and coverage >= minimum_coverage:
            return threshold
    raise ValueError("no publication threshold satisfies precision and coverage")


def _validated_examples(
    logits: NDArray[np.floating],
    targets: NDArray[np.integer],
    mask: NDArray[np.bool_] | None,
) -> tuple[NDArray[np.float64], NDArray[np.int64]]:
    scores = np.asarray(logits, dtype=np.float64)
    labels = np.asarray(targets)
    if (
        scores.ndim != 2
        or scores.shape[1] < 2
        or labels.ndim != 1
        or labels.shape[0] != scores.shape[0]
        or not len(scores)
        or not np.isfinite(scores).all()
        or not np.issubdtype(labels.dtype, np.integer)
    ):
        raise ValueError("temperature evidence is invalid")
    selected = np.ones(len(scores), dtype=np.bool_)
    if mask is not None:
        selected = np.asarray(mask)
        if selected.dtype != np.bool_ or selected.shape != labels.shape:
            raise ValueError("temperature mask is invalid")
    if not selected.any():
        raise ValueError("temperature evidence cannot be empty")
    labels = labels.astype(np.int64, copy=False)
    if np.any((labels[selected] < 0) | (labels[selected] >= scores.shape[1])):
        raise ValueError("temperature targets are outside the logits")
    return scores[selected], labels[selected]
