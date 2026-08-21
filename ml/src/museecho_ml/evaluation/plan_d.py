from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from museecho_ml.artifacts import canonical_sha256
from museecho_ml.evaluation.report import EvaluationConfig
from museecho_ml.evaluation.statistics import evaluate_dataset_strata
from museecho_ml.postprocess.hybrid import (
    HybridDecodeConfig,
    HybridFrameProbabilities,
    decode_hybrid,
)
from museecho_ml.postprocess.hybrid_calibration import HybridCalibrationParameters
from museecho_ml.vocabulary import ChordVocabulary

_SEEDS = (20260821, 20260822, 20260823)
_IDENTITY_FIELDS = ("manifest_sha256", "vocabulary_sha256")


@dataclass(frozen=True)
class PlanDDevelopmentGates:
    minimum_exact: float = 0.30
    minimum_exact_gain: float = 0.03
    minimum_known_precision: float = 0.60
    minimum_coverage: float = 0.20
    minimum_event_ratio: float = 0.75
    maximum_event_ratio: float = 1.50
    maximum_dataset_regression: float = 0.02
    maximum_seed_span: float = 0.05
    maximum_cpu_seconds: float = 15.0

    def __post_init__(self) -> None:
        unit_values = (
            self.minimum_exact,
            self.minimum_exact_gain,
            self.minimum_known_precision,
            self.minimum_coverage,
            self.minimum_event_ratio,
            self.maximum_dataset_regression,
            self.maximum_seed_span,
        )
        if any(not _finite(value) or not 0 <= value <= 1 for value in unit_values):
            raise ValueError("Plan D development gate values are invalid")
        if (
            not _finite(self.maximum_event_ratio)
            or self.maximum_event_ratio < self.minimum_event_ratio
            or not _finite(self.maximum_cpu_seconds)
            or self.maximum_cpu_seconds <= 0
        ):
            raise ValueError("Plan D development gate bounds are invalid")


def evaluate_plan_d_replay(
    raw_predictions: Sequence[Any],
    *,
    legacy_by_track: Mapping[str, Sequence[Any]],
    vocabulary: ChordVocabulary,
    calibration: HybridCalibrationParameters,
    config: HybridDecodeConfig,
) -> dict[str, Any]:
    if any(getattr(item, "split", None) == "test" for item in raw_predictions):
        raise ValueError("Plan D replay forbids test split")
    if not raw_predictions or any(
        getattr(item, "split", None) != "validation" for item in raw_predictions
    ):
        raise ValueError("Plan D replay requires validation split")
    if not isinstance(vocabulary, ChordVocabulary) or not isinstance(
        calibration, HybridCalibrationParameters
    ) or not isinstance(config, HybridDecodeConfig):
        raise ValueError("Plan D replay configuration is invalid")
    if set(legacy_by_track) != {item.track_id for item in raw_predictions}:
        raise ValueError("Plan D replay legacy identity drift")
    effective_config = replace(
        config,
        known_threshold=calibration.known_threshold,
        quality_thresholds=calibration.quality_thresholds,
        bass_threshold=calibration.bass_threshold,
        minimum_support_fraction=calibration.minimum_support_fraction,
    )
    tracks: dict[str, tuple[Sequence[Any], Sequence[Any]]] = {}
    metadata: dict[str, dict[str, str]] = {}
    predicted_events = 0
    legacy_events = 0
    cpu_seconds = 0.0
    for raw in sorted(raw_predictions, key=lambda item: item.track_id):
        neural = HybridFrameProbabilities(
            frame_times=np.asarray(raw.frame_times, dtype=np.float64),
            valid_mask=np.asarray(raw.valid_mask),
            root=_softmax(raw.root_logits),
            quality=_softmax(raw.quality_logits),
            bass=_softmax(raw.bass_logits),
            low_energy_mask=np.zeros_like(raw.valid_mask, dtype=np.bool_),
        )
        legacy = tuple(legacy_by_track[raw.track_id])
        prediction = decode_hybrid(
            legacy, neural, vocabulary=vocabulary, config=effective_config
        )
        tracks[raw.track_id] = (raw.reference, prediction)
        metadata[raw.track_id] = {
            "dataset_id": raw.dataset_id,
            "cover_group_id": raw.cover_group_id,
            "split": raw.split,
        }
        predicted_events += len(prediction)
        legacy_events += len(legacy)
        cpu_seconds += float(raw.inference_wall_seconds)
    report = evaluate_dataset_strata(tracks, metadata, EvaluationConfig())
    report["event_ratio"] = predicted_events / legacy_events
    report["inference_wall_seconds"] = cpu_seconds
    return report


def decide_plan_d_development(
    *,
    legacy: Mapping[str, Any],
    deep_by_seed: Sequence[Mapping[str, Any]],
    hybrid_by_seed: Sequence[Mapping[str, Any]],
    gates: PlanDDevelopmentGates,
) -> dict[str, Any]:
    legacy_report, deep, hybrid = _validated_three_way_reports(
        legacy, deep_by_seed, hybrid_by_seed
    )
    legacy_exact = _metric(legacy_report, "exact_vocabulary_wcsr")
    deep_exact = [_metric(report, "exact_vocabulary_wcsr") for report in deep]
    hybrid_exact = [_metric(report, "exact_vocabulary_wcsr") for report in hybrid]
    median_deep = statistics.median(deep_exact)
    median_hybrid = statistics.median(hybrid_exact)
    minimum_precision = min(_metric(report, "known_precision") for report in hybrid)
    minimum_coverage = min(_metric(report, "coverage") for report in hybrid)
    event_ratios = [_metric(report, "event_ratio") for report in hybrid]
    dataset_floor_delta = _dataset_floor_delta(legacy_report, hybrid)
    cpu_maximum = max(
        _metric(report, "five_minute_cpu_wall_seconds") for report in hybrid
    )
    checks = {
        "minimum-exact": _at_least(median_hybrid, gates.minimum_exact),
        "gain-over-legacy": _at_least(
            median_hybrid - legacy_exact, gates.minimum_exact_gain
        ),
        "gain-over-deep": _at_least(
            median_hybrid - median_deep, gates.minimum_exact_gain
        ),
        "known-precision": _at_least(
            minimum_precision, gates.minimum_known_precision
        ),
        "coverage": _at_least(minimum_coverage, gates.minimum_coverage),
        "event-ratio": all(
            gates.minimum_event_ratio <= value <= gates.maximum_event_ratio
            for value in event_ratios
        ),
        "dataset-regression": _at_least(
            dataset_floor_delta, -gates.maximum_dataset_regression
        ),
        "seed-span": max(hybrid_exact) - min(hybrid_exact)
        <= gates.maximum_seed_span + 1e-12,
        "cpu-wall": cpu_maximum <= gates.maximum_cpu_seconds,
    }
    continuation = {
        "gain-over-legacy": _at_least(median_hybrid - legacy_exact, 0.01),
        "gain-over-deep": _at_least(median_hybrid - median_deep, 0.01),
        "known-precision": _at_least(minimum_precision, 0.40),
        "coverage": _at_least(minimum_coverage, 0.10),
        "event-ratio": all(0.75 <= value <= 1.50 for value in event_ratios),
        "dataset-regression": _at_least(dataset_floor_delta, -0.05),
    }
    status = (
        "development-candidate-frozen"
        if all(checks.values())
        else "advance-to-retraining"
        if all(continuation.values())
        else "data-first-required"
    )
    body = {
        "schema_version": 1,
        "decision_version": "plan-d-development-v1",
        "status": status,
        "checks": checks,
        "continuation_checks": continuation,
        "summary": {
            "legacy_exact": legacy_exact,
            "deep_median_exact": median_deep,
            "hybrid_median_exact": median_hybrid,
            "hybrid_seed_span": max(hybrid_exact) - min(hybrid_exact),
            "minimum_known_precision": minimum_precision,
            "minimum_coverage": minimum_coverage,
            "dataset_floor_delta": dataset_floor_delta,
            "maximum_cpu_seconds": cpu_maximum,
        },
    }
    return {**body, "decision_sha256": canonical_sha256(body)}


def _validated_three_way_reports(
    legacy: Mapping[str, Any],
    deep: Sequence[Mapping[str, Any]],
    hybrid: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], tuple[Mapping[str, Any], ...], tuple[Mapping[str, Any], ...]]:
    if not isinstance(legacy, Mapping) or legacy.get("variant") != "legacy":
        raise ValueError("Plan D legacy report is invalid")
    ordered_deep = _validated_seed_reports(deep, "deep-only")
    ordered_hybrid = _validated_seed_reports(hybrid, "hybrid")
    reports = (legacy, *ordered_deep, *ordered_hybrid)
    if any(report.get("split") != "validation" for report in reports):
        raise ValueError("Plan D reports must use validation split")
    for field in _IDENTITY_FIELDS:
        values = {report.get(field) for report in reports}
        if len(values) != 1 or any(not isinstance(value, str) for value in values):
            raise ValueError("Plan D replay identity drift")
    for report in reports:
        for metric in (
            "exact_vocabulary_wcsr",
            "known_precision",
            "coverage",
            "event_ratio",
            "five_minute_cpu_wall_seconds",
        ):
            _metric(report, metric)
        if not isinstance(report.get("datasets"), Mapping) or not report["datasets"]:
            raise ValueError("Plan D dataset reports are invalid")
    datasets = set(legacy["datasets"])
    if any(set(report["datasets"]) != datasets for report in reports):
        raise ValueError("Plan D replay identity drift")
    return legacy, ordered_deep, ordered_hybrid


def _validated_seed_reports(
    reports: Sequence[Mapping[str, Any]], variant: str
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(reports, Sequence) or len(reports) != 3:
        raise ValueError("Plan D requires exactly three seed reports")
    ordered = tuple(sorted(reports, key=lambda report: report.get("seed", -1)))
    if tuple(report.get("seed") for report in ordered) != _SEEDS or any(
        report.get("variant") != variant for report in ordered
    ):
        raise ValueError("Plan D seed report identity drift")
    return ordered


def _metric(report: Mapping[str, Any], name: str) -> float:
    metrics = report.get("metrics")
    value = metrics.get(name) if isinstance(metrics, Mapping) else None
    if not _finite(value):
        raise ValueError("Plan D report metrics are invalid")
    return float(value)


def _dataset_floor_delta(
    legacy: Mapping[str, Any], hybrid: Sequence[Mapping[str, Any]]
) -> float:
    deltas: list[float] = []
    for report in hybrid:
        for dataset, baseline in legacy["datasets"].items():
            current = report["datasets"][dataset]
            baseline_value = baseline.get("exact_vocabulary_wcsr")
            current_value = current.get("exact_vocabulary_wcsr")
            if not _finite(baseline_value) or not _finite(current_value):
                raise ValueError("Plan D dataset metrics are invalid")
            deltas.append(float(current_value) - float(baseline_value))
    return min(deltas)


def _softmax(values: Any) -> np.ndarray:
    logits = np.asarray(values, dtype=np.float64)
    if logits.ndim != 2 or not np.isfinite(logits).all():
        raise ValueError("Plan D replay logits are invalid")
    shifted = logits - logits.max(axis=1, keepdims=True)
    exponentials = np.exp(shifted)
    return exponentials / exponentials.sum(axis=1, keepdims=True)


def _finite(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _at_least(value: float, threshold: float) -> bool:
    return value + 1e-12 >= threshold
