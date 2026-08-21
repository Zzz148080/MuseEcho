from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from museecho_ml.evaluation.metrics import ScoredChordInterval
from museecho_ml.evaluation.report import (
    EvaluationConfig,
    evaluate_corpus,
)

_SCALAR_METRICS = (
    "exact_vocabulary_wcsr",
    "public_quality_macro_f1",
    "published_known_precision",
    "coverage",
    "ece",
    "majmin_wcsr",
    "seventh_quality_macro_f1",
)
_SEVENTH_QUALITIES = frozenset(("7", "maj7", "min7", "hdim7"))
_PLAN_C_DATASETS = frozenset(
    ("guitarset", "rwc-popular", "schubert-winterreise")
)


def dataset_macro(
    dataset_reports: Mapping[str, Mapping[str, Any]],
) -> dict[str, float]:
    if not isinstance(dataset_reports, Mapping) or not dataset_reports:
        raise ValueError("dataset macro reports cannot be empty")
    validated: list[Mapping[str, Any]] = []
    for dataset_id in sorted(dataset_reports):
        if not isinstance(dataset_id, str) or not dataset_id:
            raise ValueError("dataset macro dataset ID is invalid")
        report = dataset_reports[dataset_id]
        if not isinstance(report, Mapping) or set(report) != set(_SCALAR_METRICS):
            raise ValueError("dataset macro scalar metrics are invalid")
        if any(not _finite_number(report[metric]) for metric in _SCALAR_METRICS):
            raise ValueError("dataset macro scalar metrics must be finite")
        validated.append(report)
    return {
        metric: sum(float(report[metric]) for report in validated) / len(validated)
        for metric in _SCALAR_METRICS
    }


def group_bootstrap_ci(
    group_reports: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    resamples: int = 10_000,
    seed: int = 20260821,
) -> dict[str, Any]:
    groups = _validated_group_reports(group_reports)
    if type(resamples) is not int or resamples <= 0:
        raise ValueError("bootstrap resamples must be a positive integer")
    if type(seed) is not int or seed < 0:
        raise ValueError("bootstrap seed must be a non-negative integer")
    group_ids = tuple(sorted(groups))
    incomplete_support = any(
        report.get("missing_quality_support") is True
        for reports in groups.values()
        for report in reports
    )
    rng = np.random.Generator(np.random.PCG64(seed))
    samples = np.empty((resamples, len(_SCALAR_METRICS)), dtype=np.float64)
    for index in range(resamples):
        selected = rng.choice(len(group_ids), size=len(group_ids), replace=True)
        samples[index] = _aggregate_selected_groups(group_ids, selected, groups)
    point = _aggregate_selected_groups(
        group_ids, np.arange(len(group_ids), dtype=np.int64), groups
    )
    lower = np.percentile(samples, 2.5, axis=0, method="linear")
    upper = np.percentile(samples, 97.5, axis=0, method="linear")
    return {
        "schema_version": 1,
        "implementation_version": "group-bootstrap-pcg64-v1",
        "unit": "cover_group_id",
        "seed": seed,
        "resamples": resamples,
        "group_count": len(group_ids),
        "quality_support_status": (
            "incomplete" if incomplete_support else "complete"
        ),
        "metrics": {
            metric: {
                "point_estimate": float(point[metric_index]),
                "lower": float(lower[metric_index]),
                "upper": float(upper[metric_index]),
            }
            for metric_index, metric in enumerate(_SCALAR_METRICS)
        },
    }


def evaluate_dataset_strata(
    tracks: Mapping[
        str,
        tuple[Sequence[ScoredChordInterval], Sequence[ScoredChordInterval]],
    ],
    metadata: Mapping[str, Mapping[str, str]],
    config: EvaluationConfig,
) -> dict[str, Any]:
    frozen_metadata = _validated_metadata(tracks, metadata)
    corpus = evaluate_corpus(tracks, config)
    by_dataset: dict[str, dict[str, Any]] = {}
    for dataset_id in sorted({item["dataset_id"] for item in frozen_metadata.values()}):
        dataset_tracks = {
            track_id: tracks[track_id]
            for track_id, item in frozen_metadata.items()
            if item["dataset_id"] == dataset_id
        }
        report = evaluate_corpus(dataset_tracks, config)
        scalars, missing_public, missing_seventh = _strict_scalars(
            report["aggregate"], config.public_quality_labels
        )
        by_dataset[dataset_id] = {
            **report,
            "scalars": scalars,
            "missing_public_quality_support": missing_public,
            "missing_seventh_quality_support": missing_seventh,
        }
    macro = _partial_dataset_macro(
        {dataset_id: report["scalars"] for dataset_id, report in by_dataset.items()}
    )
    grouped_track_ids: dict[str, list[str]] = {}
    for track_id, item in frozen_metadata.items():
        grouped_track_ids.setdefault(item["cover_group_id"], []).append(track_id)
    group_reports: dict[str, list[dict[str, Any]]] = {}
    for group_id in sorted(grouped_track_ids):
        track_ids = sorted(grouped_track_ids[group_id])
        group_corpus = evaluate_corpus(
            {track_id: tracks[track_id] for track_id in track_ids}, config
        )
        group_scalars = _lenient_scalars(
            group_corpus["aggregate"], config.public_quality_labels
        )
        _, missing_public, missing_seventh = _strict_scalars(
            group_corpus["aggregate"], config.public_quality_labels
        )
        group_reports[group_id] = [
            {
                "track_id": f"cover-group:{group_id}",
                "dataset_id": frozen_metadata[track_ids[0]]["dataset_id"],
                "split": frozen_metadata[track_ids[0]]["split"],
                "duration_seconds": group_corpus["duration_seconds"],
                "missing_quality_support": bool(
                    missing_public or missing_seventh
                ),
                **group_scalars,
            }
        ]
    bootstrap = group_bootstrap_ci(group_reports)
    return {
        **corpus,
        "schema_version": 2,
        "evaluation_version": "plan-c-evaluation-v2",
        "datasets": by_dataset,
        "dataset_macro": macro,
        "bootstrap": bootstrap,
    }


def _strict_scalars(
    aggregate: Mapping[str, Any], public_quality_labels: Sequence[str]
) -> tuple[dict[str, float | None], list[str], list[str]]:
    quality = aggregate["quality"]["per_quality"]
    missing_public = [
        label
        for label in public_quality_labels
        if label not in quality or quality[label]["support_seconds"] <= 0
    ]
    seventh_labels = [
        label for label in public_quality_labels if label in _SEVENTH_QUALITIES
    ]
    missing_seventh = [
        label
        for label in seventh_labels
        if label not in quality or quality[label]["support_seconds"] <= 0
    ]
    values: dict[str, float | None] = {
        "exact_vocabulary_wcsr": float(
            aggregate["weighted_scores"]["exact_quality"]
        ),
        "public_quality_macro_f1": (
            None
            if missing_public
            else _mean(quality[label]["f1"] for label in public_quality_labels)
        ),
        "published_known_precision": float(aggregate["published"]["precision"]),
        "coverage": float(aggregate["published"]["coverage"]),
        "ece": float(aggregate["ece"]),
        "majmin_wcsr": float(aggregate["weighted_scores"]["majmin"]),
        "seventh_quality_macro_f1": (
            None
            if not seventh_labels or missing_seventh
            else _mean(quality[label]["f1"] for label in seventh_labels)
        ),
    }
    return values, missing_public, missing_seventh


def _lenient_scalars(
    aggregate: Mapping[str, Any], public_quality_labels: Sequence[str]
) -> dict[str, float]:
    quality = aggregate["quality"]["per_quality"]
    supported_public = [label for label in public_quality_labels if label in quality]
    supported_seventh = [
        label for label in supported_public if label in _SEVENTH_QUALITIES
    ]
    return {
        "exact_vocabulary_wcsr": float(
            aggregate["weighted_scores"]["exact_quality"]
        ),
        "public_quality_macro_f1": (
            _mean(quality[label]["f1"] for label in supported_public)
            if supported_public
            else 0.0
        ),
        "published_known_precision": float(aggregate["published"]["precision"]),
        "coverage": float(aggregate["published"]["coverage"]),
        "ece": float(aggregate["ece"]),
        "majmin_wcsr": float(aggregate["weighted_scores"]["majmin"]),
        "seventh_quality_macro_f1": (
            _mean(quality[label]["f1"] for label in supported_seventh)
            if supported_seventh
            else 0.0
        ),
    }


def _partial_dataset_macro(
    reports: Mapping[str, Mapping[str, float | None]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    missing: list[str] = []
    for metric in _SCALAR_METRICS:
        values = [report[metric] for report in reports.values()]
        if any(value is None for value in values):
            result[metric] = None
            missing.append(metric)
        else:
            result[metric] = sum(float(value) for value in values) / len(values)
    result["status"] = "unavailable" if missing else "available"
    result["missing_metrics"] = missing
    return result


def _validated_metadata(
    tracks: Mapping[str, Any], metadata: Mapping[str, Mapping[str, str]]
) -> dict[str, dict[str, str]]:
    if not isinstance(tracks, Mapping) or not tracks:
        raise ValueError("dataset strata tracks cannot be empty")
    if not isinstance(metadata, Mapping) or set(metadata) != set(tracks):
        raise ValueError("dataset strata metadata must match tracks exactly")
    result: dict[str, dict[str, str]] = {}
    group_splits: dict[str, str] = {}
    group_datasets: dict[str, str] = {}
    for track_id in sorted(metadata):
        item = metadata[track_id]
        if not isinstance(item, Mapping):
            raise ValueError("dataset strata metadata item must be an object")
        values = {field: item.get(field) for field in ("dataset_id", "cover_group_id", "split")}
        if any(not isinstance(value, str) or not value for value in values.values()):
            raise ValueError("dataset strata metadata fields are invalid")
        group_id = values["cover_group_id"]
        split = values["split"]
        dataset_id = values["dataset_id"]
        if dataset_id not in _PLAN_C_DATASETS:
            raise ValueError("dataset strata metadata contains an unknown dataset")
        if group_id in group_splits and group_splits[group_id] != split:
            raise ValueError("one cover group maps to multiple frozen splits")
        if group_id in group_datasets and group_datasets[group_id] != dataset_id:
            raise ValueError("one cover group maps to multiple datasets")
        group_splits[group_id] = split
        group_datasets[group_id] = dataset_id
        result[track_id] = values  # type: ignore[assignment]
    return result


def _validated_group_reports(
    value: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, tuple[Mapping[str, Any], ...]]:
    if not isinstance(value, Mapping) or len(value) < 2:
        raise ValueError("bootstrap requires at least two cover groups")
    result: dict[str, tuple[Mapping[str, Any], ...]] = {}
    track_ids: set[str] = set()
    for group_id in sorted(value):
        reports = value[group_id]
        if (
            not isinstance(group_id, str)
            or not group_id
            or not isinstance(reports, Sequence)
            or isinstance(reports, (str, bytes))
            or not reports
        ):
            raise ValueError("bootstrap groups must be non-empty sequences")
        validated: list[Mapping[str, Any]] = []
        for report in reports:
            if not isinstance(report, Mapping):
                raise ValueError("bootstrap track report must be an object")
            track_id = report.get("track_id")
            if not isinstance(track_id, str) or not track_id:
                raise ValueError("bootstrap track ID is invalid")
            if track_id in track_ids:
                raise ValueError("bootstrap duplicate track assignment")
            track_ids.add(track_id)
            if not _finite_number(report.get("duration_seconds")) or report[
                "duration_seconds"
            ] <= 0:
                raise ValueError("bootstrap duration must be finite and positive")
            if any(not _finite_number(report.get(metric)) for metric in _SCALAR_METRICS):
                raise ValueError("bootstrap scalar metrics must be finite")
            validated.append(report)
        result[group_id] = tuple(validated)
    return result


def _aggregate_selected_groups(
    group_ids: Sequence[str],
    selected: Sequence[int],
    reports: Mapping[str, Sequence[Mapping[str, Any]]],
) -> np.ndarray:
    totals = np.zeros(len(_SCALAR_METRICS), dtype=np.float64)
    total_duration = 0.0
    for group_index in selected:
        for report in reports[group_ids[int(group_index)]]:
            duration = float(report["duration_seconds"])
            total_duration += duration
            for metric_index, metric in enumerate(_SCALAR_METRICS):
                totals[metric_index] += duration * float(report[metric])
    return totals / total_duration


def _finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _mean(values: Any) -> float:
    items = tuple(float(value) for value in values)
    return sum(items) / len(items)
