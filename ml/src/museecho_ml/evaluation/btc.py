from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from museecho_ml.artifacts import canonical_sha256
from museecho_ml.candidates.btc_inference import BtcInferenceResult
from museecho_ml.evaluation.deep_adapter import manifest_reference_intervals
from museecho_ml.evaluation.metrics import ScoredChordInterval
from museecho_ml.evaluation.report import EvaluationConfig, evaluate_corpus
from museecho_ml.evaluation.statistics import evaluate_dataset_strata
from museecho_ml.labels import parse_annotation
from museecho_ml.vocabulary import ChordVocabulary

_BTC_ALGORITHM = "btc-ismir19-large-voca-v1"
_LEGACY_EXACT_BASELINE = 0.166596
_BOOTSTRAP_SEED = 20260823


class _BtcRecognizer(Protocol):
    def recognize(
        self, samples: np.ndarray, sample_rate: int
    ) -> BtcInferenceResult: ...


class _LegacyEvent(Protocol):
    symbol: str | None
    start_seconds: float
    end_seconds: float
    confidence: float | None
    algorithm: str


AudioLoader = Callable[[Path], tuple[np.ndarray, int]]
LegacyRecognizer = Callable[[np.ndarray, int], Sequence[_LegacyEvent]]


def load_btc_validation_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("BTC validation manifest is unreadable") from error
    if not isinstance(manifest, dict):
        raise ValueError("BTC validation manifest must be an object")
    if manifest.get("split") != "validation":
        raise PermissionError("BTC experiment is validation only")
    if manifest.get("corpus_role") != "real-gold":
        raise ValueError("BTC validation manifest must contain real-gold")
    if not isinstance(manifest.get("tracks"), list) or not manifest["tracks"]:
        raise ValueError("BTC validation manifest must contain tracks")
    return manifest


def run_btc_validation_experiment(
    *,
    manifest_path: Path,
    dataset_roots: Mapping[str, Path],
    config: EvaluationConfig,
    btc_recognizer_factory: Callable[[], _BtcRecognizer],
    legacy_recognize: LegacyRecognizer,
    audio_loader: AudioLoader,
    peak_rss_reader: Callable[[], int],
    checkpoint_security_passed: bool,
    artifact_identity_passed: bool,
    deterministic_replay: bool,
    bootstrap_resamples: int = 10_000,
) -> dict[str, Any]:
    manifest = load_btc_validation_manifest(manifest_path)
    manifest_sha256 = canonical_sha256(manifest)
    prepared = _prepare_tracks(manifest["tracks"], dataset_roots)
    recognizer = btc_recognizer_factory()
    vocabulary = ChordVocabulary.default()
    btc_tracks: dict[str, tuple[Sequence[ScoredChordInterval], Sequence[ScoredChordInterval]]] = {}
    legacy_tracks: dict[
        str, tuple[Sequence[ScoredChordInterval], Sequence[ScoredChordInterval]]
    ] = {}
    metadata: dict[str, dict[str, str]] = {}
    prediction_rows: list[dict[str, Any]] = []
    btc_cpu = 0.0
    btc_wall = 0.0
    legacy_cpu = 0.0
    legacy_wall = 0.0
    btc_events = 0
    legacy_events = 0
    reference_events = 0
    unsupported_quality_seconds = 0.0
    legacy_algorithms: set[str] = set()

    for track, audio_path in prepared:
        track_id = str(track["track_id"])
        duration = float(track["duration_seconds"])
        samples, sample_rate = audio_loader(audio_path)
        samples = np.asarray(samples, dtype=np.float32)
        if (
            samples.ndim != 1
            or samples.size == 0
            or not np.isfinite(samples).all()
            or type(sample_rate) is not int
            or sample_rate <= 0
        ):
            raise ValueError("BTC audio loader returned invalid samples")
        observed_duration = samples.size / sample_rate
        if not math.isclose(
            observed_duration,
            duration,
            abs_tol=max(0.05, 1 / sample_rate),
        ):
            raise ValueError("BTC audio duration does not match frozen manifest")
        reference = manifest_reference_intervals(track, vocabulary)

        btc_result = recognizer.recognize(samples, sample_rate)
        btc_prediction = _btc_intervals(btc_result, duration)
        legacy_started_cpu = time.process_time()
        legacy_started_wall = time.perf_counter()
        raw_legacy = tuple(legacy_recognize(samples, sample_rate))
        legacy_cpu += time.process_time() - legacy_started_cpu
        legacy_wall += time.perf_counter() - legacy_started_wall
        legacy_prediction, track_algorithms = _legacy_intervals(raw_legacy, duration)
        legacy_algorithms.update(track_algorithms)

        btc_tracks[track_id] = (reference, btc_prediction)
        legacy_tracks[track_id] = (reference, legacy_prediction)
        metadata[track_id] = {
            "dataset_id": str(track["dataset_id"]),
            "cover_group_id": str(track["cover_group_id"]),
            "split": "validation",
        }
        btc_cpu += btc_result.cpu_seconds
        btc_wall += btc_result.wall_seconds
        btc_events += len(btc_prediction)
        legacy_events += len(legacy_prediction)
        reference_events += len(reference)
        unsupported_quality_seconds += sum(
            item.end_seconds - item.start_seconds
            for item in btc_prediction
            if item.chord.root == "X"
        )
        prediction_rows.append(
            {
                "split": "validation",
                "track_id": track_id,
                "dataset_id": str(track["dataset_id"]),
                "cover_group_id": str(track["cover_group_id"]),
                "duration_seconds": duration,
                "btc_events": _serialize_intervals(btc_prediction),
                "legacy_events": _serialize_intervals(legacy_prediction),
                "btc_cpu_seconds": btc_result.cpu_seconds,
                "btc_wall_seconds": btc_result.wall_seconds,
            }
        )

    if legacy_algorithms != {"chroma-triad-viterbi-v1"}:
        raise ValueError("BTC comparison requires the frozen legacy algorithm")
    duration_seconds = sum(float(track["duration_seconds"]) for track, _ in prepared)
    peak_rss_bytes = peak_rss_reader()
    if type(peak_rss_bytes) is not int or peak_rss_bytes <= 0:
        raise ValueError("BTC peak RSS measurement is unavailable")

    btc_evaluation = evaluate_dataset_strata(btc_tracks, metadata, config)
    legacy_evaluation = evaluate_dataset_strata(legacy_tracks, metadata, config)
    paired_bootstrap = paired_group_bootstrap_delta(
        btc_tracks,
        legacy_tracks,
        metadata,
        config,
        resamples=bootstrap_resamples,
    )
    dataset_exact_wins = sum(
        btc_evaluation["datasets"][dataset_id]["aggregate"]["weighted_scores"][
            "exact_quality"
        ]
        > legacy_evaluation["datasets"][dataset_id]["aggregate"]["weighted_scores"][
            "exact_quality"
        ]
        for dataset_id in btc_evaluation["datasets"]
    )
    dataset_track_counts = {
        dataset_id: sum(
            item["dataset_id"] == dataset_id for item in metadata.values()
        )
        for dataset_id in sorted({item["dataset_id"] for item in metadata.values()})
    }
    track_ids = sorted(metadata)
    report = {
        "schema_version": 1,
        "experiment_version": "btc-170-validation-v1",
        "split": "validation",
        "corpus_role": "real-gold",
        "confidence_status": "uncalibrated-diagnostic-only",
        "calibration": {"calibrated": False},
        "manifest_sha256": manifest_sha256,
        "track_count": len(track_ids),
        "dataset_track_counts": dataset_track_counts,
        "candidates": {
            "btc": _candidate_report(
                algorithm=_BTC_ALGORITHM,
                manifest_sha256=manifest_sha256,
                track_ids=track_ids,
                duration_seconds=duration_seconds,
                evaluation=btc_evaluation,
                event_count=btc_events,
                reference_events=reference_events,
                cpu_seconds=btc_cpu,
                wall_seconds=btc_wall,
                unsupported_quality_seconds=unsupported_quality_seconds,
            ),
            "legacy": _candidate_report(
                algorithm="chroma-triad-viterbi-v1",
                manifest_sha256=manifest_sha256,
                track_ids=track_ids,
                duration_seconds=duration_seconds,
                evaluation=legacy_evaluation,
                event_count=legacy_events,
                reference_events=reference_events,
                cpu_seconds=legacy_cpu,
                wall_seconds=legacy_wall,
                unsupported_quality_seconds=0.0,
            ),
        },
        "comparison": {
            "dataset_exact_wins": int(dataset_exact_wins),
            "track_identity_match": True,
            "deterministic_prediction_replay": deterministic_replay is True,
            "paired_bootstrap": paired_bootstrap,
            "exact_quality_delta": _aggregate_metric(
                btc_evaluation, "weighted_scores", "exact_quality"
            )
            - _aggregate_metric(legacy_evaluation, "weighted_scores", "exact_quality"),
            "root_delta": _aggregate_metric(btc_evaluation, "weighted_scores", "root")
            - _aggregate_metric(legacy_evaluation, "weighted_scores", "root"),
            "boundary_f1_delta": _aggregate_metric(btc_evaluation, "boundary", "f1")
            - _aggregate_metric(legacy_evaluation, "boundary", "f1"),
        },
        "operational": {"peak_rss_bytes": peak_rss_bytes},
        "security": {
            "checkpoint_security_passed": checkpoint_security_passed is True,
            "artifact_identity_passed": artifact_identity_passed is True,
        },
        "bass_evaluation_status": "unavailable-btc-has-no-bass-head",
    }
    _require_finite_json(report)
    return {"report": report, "prediction_rows": prediction_rows}


def paired_group_bootstrap_delta(
    btc_tracks: Mapping[
        str, tuple[Sequence[ScoredChordInterval], Sequence[ScoredChordInterval]]
    ],
    legacy_tracks: Mapping[
        str, tuple[Sequence[ScoredChordInterval], Sequence[ScoredChordInterval]]
    ],
    metadata: Mapping[str, Mapping[str, str]],
    config: EvaluationConfig,
    *,
    resamples: int = 10_000,
    seed: int = _BOOTSTRAP_SEED,
) -> dict[str, Any]:
    if set(btc_tracks) != set(legacy_tracks) or set(btc_tracks) != set(metadata):
        raise ValueError("paired BTC bootstrap track identities do not match")
    if type(resamples) is not int or resamples <= 0:
        raise ValueError("paired BTC bootstrap resamples must be positive")
    groups: dict[str, list[str]] = {}
    for track_id, item in metadata.items():
        group_id = item.get("cover_group_id")
        if not isinstance(group_id, str) or not group_id:
            raise ValueError("paired BTC bootstrap group metadata is invalid")
        groups.setdefault(group_id, []).append(track_id)
    if len(groups) < 2:
        raise ValueError("paired BTC bootstrap requires at least two groups")
    group_ids = sorted(groups)
    statistics = [
        _paired_group_statistics(
            sorted(groups[group_id]), btc_tracks, legacy_tracks, config
        )
        for group_id in group_ids
    ]
    rng = np.random.Generator(np.random.PCG64(seed))
    samples = np.empty((resamples, 3), dtype=np.float64)
    for index in range(resamples):
        selected = rng.integers(0, len(group_ids), size=len(group_ids))
        samples[index] = _aggregate_group_deltas(statistics, selected)
    point = _aggregate_group_deltas(
        statistics, np.arange(len(group_ids), dtype=np.int64)
    )
    lower = np.percentile(samples, 2.5, axis=0, method="linear")
    upper = np.percentile(samples, 97.5, axis=0, method="linear")
    metric_names = ("exact_quality_wcsr", "root_wcsr", "boundary_f1")
    return {
        "schema_version": 1,
        "unit": "cover_group_id",
        "seed": seed,
        "resamples": resamples,
        "group_count": len(group_ids),
        "metrics": {
            name: {
                "point_estimate": float(point[metric_index]),
                "lower": float(lower[metric_index]),
                "upper": float(upper[metric_index]),
            }
            for metric_index, name in enumerate(metric_names)
        },
    }


def decide_btc_continuation(report: Mapping[str, Any]) -> dict[str, Any]:
    try:
        _require_finite_json(report)
        if (
            report["confidence_status"] != "uncalibrated-diagnostic-only"
            or report["calibration"]["calibrated"] is not False
            or report["comparison"]["track_identity_match"] is not True
        ):
            raise ValueError
        btc = report["candidates"]["btc"]
        legacy = report["candidates"]["legacy"]
        btc_exact = _finite_metric(
            btc,
            "evaluation",
            "aggregate",
            "weighted_scores",
            "exact_quality",
        )
        btc_root = _finite_metric(btc, "evaluation", "aggregate", "weighted_scores", "root")
        legacy_root = _finite_metric(
            legacy, "evaluation", "aggregate", "weighted_scores", "root"
        )
        btc_boundary = _finite_metric(btc, "evaluation", "aggregate", "boundary", "f1")
        legacy_boundary = _finite_metric(
            legacy, "evaluation", "aggregate", "boundary", "f1"
        )
        dataset_exact_wins = report["comparison"]["dataset_exact_wins"]
        deterministic_replay = report["comparison"]["deterministic_prediction_replay"]
        cpu_seconds = _finite_metric(btc, "operational", "cpu_seconds")
        five_minute_cpu_seconds = _finite_metric(
            btc, "operational", "five_minute_cpu_seconds"
        )
        checkpoint_security_passed = report["security"][
            "checkpoint_security_passed"
        ]
        artifact_identity_passed = report["security"]["artifact_identity_passed"]
        if (
            type(dataset_exact_wins) is not int
            or dataset_exact_wins < 0
            or type(deterministic_replay) is not bool
            or type(checkpoint_security_passed) is not bool
            or type(artifact_identity_passed) is not bool
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError("BTC continuation report is invalid") from None

    predicates = {
        "exact_above_legacy_0_166596": btc_exact > _LEGACY_EXACT_BASELINE,
        "at_least_two_dataset_exact_wins": dataset_exact_wins >= 2,
        "root_not_below_legacy": btc_root >= legacy_root,
        "boundary_not_below_legacy": btc_boundary >= legacy_boundary,
        "deterministic_prediction_replay": deterministic_replay is True,
        "cpu_benchmark_completed": cpu_seconds > 0 and five_minute_cpu_seconds > 0,
        "checkpoint_security_passed": checkpoint_security_passed is True,
        "artifact_identity_passed": artifact_identity_passed is True,
    }
    failed = [name for name, passed in predicates.items() if not passed]
    return {
        "schema_version": 1,
        "decision_version": "btc-170-continuation-v1",
        "status": "continue-btc-research" if not failed else "btc-not-selected",
        "predicates": predicates,
        "failed_predicates": failed,
        "product_default_changed": False,
    }


def _prepare_tracks(
    tracks: Sequence[Any], dataset_roots: Mapping[str, Path]
) -> list[tuple[Mapping[str, Any], Path]]:
    dataset_ids = {
        track.get("dataset_id") for track in tracks if isinstance(track, Mapping)
    }
    if None in dataset_ids or any(not isinstance(value, str) for value in dataset_ids):
        raise ValueError("BTC validation track dataset metadata is invalid")
    roots = {
        dataset_id: dataset_roots[dataset_id].resolve(strict=True)
        for dataset_id in dataset_ids
        if dataset_id in dataset_roots
    }
    if set(roots) != dataset_ids:
        raise ValueError("BTC validation is missing a dataset root")
    prepared: list[tuple[Mapping[str, Any], Path]] = []
    seen: set[str] = set()
    for track in sorted(tracks, key=lambda item: item.get("track_id", "")):
        if not isinstance(track, Mapping):
            raise ValueError("BTC validation track must be an object")
        track_id = track.get("track_id")
        dataset_id = track.get("dataset_id")
        cover_group_id = track.get("cover_group_id")
        audio_relative = track.get("audio_path")
        duration = track.get("duration_seconds")
        if (
            not isinstance(track_id, str)
            or not track_id
            or track_id in seen
            or not isinstance(dataset_id, str)
            or not isinstance(cover_group_id, str)
            or not cover_group_id
            or not isinstance(audio_relative, str)
            or not audio_relative
            or isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or duration <= 0
        ):
            raise ValueError("BTC validation track metadata is invalid")
        seen.add(track_id)
        root = roots[dataset_id]
        audio_path = (root / audio_relative).resolve(strict=True)
        try:
            audio_path.relative_to(root)
        except ValueError:
            raise ValueError("BTC validation audio path escapes its dataset root") from None
        prepared.append((track, audio_path))
    return prepared


def _btc_intervals(
    result: BtcInferenceResult, duration: float
) -> tuple[ScoredChordInterval, ...]:
    if not result.events or result.frame_count <= 0:
        raise ValueError("BTC recognizer returned no prediction")
    intervals = tuple(
        ScoredChordInterval(
            event.start_seconds,
            event.end_seconds,
            event.chord,
            event.confidence,
        )
        for event in result.events
    )
    _validate_prediction_extent(intervals, duration, "BTC")
    return intervals


def _legacy_intervals(
    events: Sequence[_LegacyEvent], duration: float
) -> tuple[tuple[ScoredChordInterval, ...], set[str]]:
    if not events:
        raise ValueError("legacy recognizer returned no prediction")
    algorithms: set[str] = set()
    intervals = []
    for event in events:
        chord = parse_annotation("X" if event.symbol is None else event.symbol)
        confidence = 0.0 if event.confidence is None else float(event.confidence)
        intervals.append(
            ScoredChordInterval(
                float(event.start_seconds),
                float(event.end_seconds),
                chord,
                confidence,
            )
        )
        algorithms.add(event.algorithm)
    result = tuple(intervals)
    _validate_prediction_extent(result, duration, "legacy")
    return result, algorithms


def _validate_prediction_extent(
    intervals: Sequence[ScoredChordInterval], duration: float, name: str
) -> None:
    if (
        not math.isclose(intervals[0].start_seconds, 0.0, abs_tol=1e-9)
        or not math.isclose(intervals[-1].end_seconds, duration, abs_tol=1e-9)
        or any(
            not math.isclose(left.end_seconds, right.start_seconds, abs_tol=1e-9)
            for left, right in zip(intervals, intervals[1:], strict=False)
        )
    ):
        raise ValueError(f"{name} prediction must cover the frozen track")


def _serialize_intervals(
    intervals: Sequence[ScoredChordInterval],
) -> list[dict[str, Any]]:
    return [
        {
            "start_seconds": item.start_seconds,
            "end_seconds": item.end_seconds,
            "root": item.chord.root,
            "quality": item.chord.quality,
            "bass": item.chord.bass,
            "mapping_reason": item.chord.mapping_reason,
            "confidence": item.confidence,
        }
        for item in intervals
    ]


def _candidate_report(
    *,
    algorithm: str,
    manifest_sha256: str,
    track_ids: list[str],
    duration_seconds: float,
    evaluation: Mapping[str, Any],
    event_count: int,
    reference_events: int,
    cpu_seconds: float,
    wall_seconds: float,
    unsupported_quality_seconds: float,
) -> dict[str, Any]:
    return {
        "algorithm_version": algorithm,
        "manifest_sha256": manifest_sha256,
        "track_ids": track_ids,
        "duration_seconds": duration_seconds,
        "evaluation": evaluation,
        "event_count": event_count,
        "event_ratio": event_count / reference_events,
        "unsupported_quality_seconds": unsupported_quality_seconds,
        "operational": {
            "cpu_seconds": cpu_seconds,
            "wall_seconds": wall_seconds,
            "five_minute_cpu_seconds": cpu_seconds / duration_seconds * 300.0,
            "five_minute_wall_seconds": wall_seconds / duration_seconds * 300.0,
        },
    }


def _paired_group_statistics(
    track_ids: Sequence[str],
    btc_tracks: Mapping[str, tuple[Sequence[ScoredChordInterval], Sequence[ScoredChordInterval]]],
    legacy_tracks: Mapping[
        str, tuple[Sequence[ScoredChordInterval], Sequence[ScoredChordInterval]]
    ],
    config: EvaluationConfig,
) -> dict[str, float]:
    btc = evaluate_corpus({track_id: btc_tracks[track_id] for track_id in track_ids}, config)
    legacy = evaluate_corpus(
        {track_id: legacy_tracks[track_id] for track_id in track_ids}, config
    )
    duration = float(btc["duration_seconds"])
    btc_reference_boundaries = sum(len(btc_tracks[track_id][0]) - 1 for track_id in track_ids)
    btc_prediction_boundaries = sum(len(btc_tracks[track_id][1]) - 1 for track_id in track_ids)
    legacy_prediction_boundaries = sum(
        len(legacy_tracks[track_id][1]) - 1 for track_id in track_ids
    )
    return {
        "duration": duration,
        "btc_exact": duration * _aggregate_metric(btc, "weighted_scores", "exact_quality"),
        "legacy_exact": duration
        * _aggregate_metric(legacy, "weighted_scores", "exact_quality"),
        "btc_root": duration * _aggregate_metric(btc, "weighted_scores", "root"),
        "legacy_root": duration * _aggregate_metric(legacy, "weighted_scores", "root"),
        "reference_boundaries": float(btc_reference_boundaries),
        "btc_prediction_boundaries": float(btc_prediction_boundaries),
        "legacy_prediction_boundaries": float(legacy_prediction_boundaries),
        "btc_true_boundaries": _true_boundary_count(
            btc, btc_prediction_boundaries
        ),
        "legacy_true_boundaries": _true_boundary_count(
            legacy, legacy_prediction_boundaries
        ),
    }


def _true_boundary_count(report: Mapping[str, Any], prediction_count: int) -> float:
    if prediction_count == 0:
        return 0.0
    return _aggregate_metric(report, "boundary", "precision") * prediction_count


def _aggregate_group_deltas(
    statistics: Sequence[Mapping[str, float]], selected: Sequence[int]
) -> np.ndarray:
    duration = sum(statistics[int(index)]["duration"] for index in selected)
    exact = sum(
        statistics[int(index)]["btc_exact"]
        - statistics[int(index)]["legacy_exact"]
        for index in selected
    ) / duration
    root = sum(
        statistics[int(index)]["btc_root"]
        - statistics[int(index)]["legacy_root"]
        for index in selected
    ) / duration
    reference_boundaries = sum(
        statistics[int(index)]["reference_boundaries"] for index in selected
    )
    btc_prediction_boundaries = sum(
        statistics[int(index)]["btc_prediction_boundaries"] for index in selected
    )
    legacy_prediction_boundaries = sum(
        statistics[int(index)]["legacy_prediction_boundaries"] for index in selected
    )
    btc_true = sum(statistics[int(index)]["btc_true_boundaries"] for index in selected)
    legacy_true = sum(
        statistics[int(index)]["legacy_true_boundaries"] for index in selected
    )
    btc_boundary = _boundary_f1_from_counts(
        btc_true, reference_boundaries, btc_prediction_boundaries
    )
    legacy_boundary = _boundary_f1_from_counts(
        legacy_true, reference_boundaries, legacy_prediction_boundaries
    )
    return np.asarray((exact, root, btc_boundary - legacy_boundary), dtype=np.float64)


def _boundary_f1_from_counts(
    true_positive: float, reference_count: float, prediction_count: float
) -> float:
    denominator = reference_count + prediction_count
    return 1.0 if denominator == 0 else 2 * true_positive / denominator


def _aggregate_metric(report: Mapping[str, Any], section: str, metric: str) -> float:
    return float(report["aggregate"][section][metric])


def _finite_metric(value: Mapping[str, Any], *path: str) -> float:
    current: Any = value
    for part in path:
        current = current[part]
    if (
        isinstance(current, bool)
        or not isinstance(current, (int, float))
        or not math.isfinite(current)
    ):
        raise ValueError
    return float(current)


def _require_finite_json(value: Any) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("BTC continuation report contains invalid values") from error
