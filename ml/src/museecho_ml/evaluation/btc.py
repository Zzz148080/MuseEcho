from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import platform
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import torch

from museecho_ml.artifacts import (
    canonical_json_bytes,
    canonical_sha256,
    file_sha256,
    write_immutable_bytes,
    write_immutable_json,
)
from museecho_ml.candidates.btc_artifact import (
    BtcArtifactLock,
    BtcArtifactSource,
    load_btc_source,
)
from museecho_ml.candidates.btc_checkpoint import (
    checkpoint_contract,
    load_btc_checkpoint,
)
from museecho_ml.candidates.btc_inference import BtcInferenceResult, BtcRecognizer
from museecho_ml.candidates.btc_model import BtcModelConfig
from museecho_ml.evaluation.deep_adapter import manifest_reference_intervals
from museecho_ml.evaluation.metrics import ScoredChordInterval
from museecho_ml.evaluation.report import EvaluationConfig, evaluate_corpus
from museecho_ml.evaluation.statistics import evaluate_dataset_strata
from museecho_ml.labels import CanonicalChord, parse_annotation
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
        legacy_track_cpu = time.process_time() - legacy_started_cpu
        legacy_track_wall = time.perf_counter() - legacy_started_wall
        legacy_cpu += legacy_track_cpu
        legacy_wall += legacy_track_wall
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
                "legacy_cpu_seconds": legacy_track_cpu,
                "legacy_wall_seconds": legacy_track_wall,
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


def freeze_btc_validation_artifacts(
    result: Mapping[str, Any],
    *,
    identity: Mapping[str, Any],
    predictions_output: Path,
    report_output: Path,
    decision_output: Path,
    markdown_output: Path,
) -> dict[str, str]:
    if (
        not isinstance(result, Mapping)
        or not isinstance(result.get("report"), Mapping)
        or not isinstance(result.get("prediction_rows"), list)
        or not result["prediction_rows"]
        or not isinstance(identity, Mapping)
    ):
        raise ValueError("BTC validation result cannot be frozen")
    rows = result["prediction_rows"]
    predictions_payload = b"".join(canonical_json_bytes(row) + b"\n" for row in rows)
    predictions_sha256 = hashlib.sha256(predictions_payload).hexdigest()
    report = deepcopy(dict(result["report"]))
    report["identity"] = dict(identity)
    report["predictions_sha256"] = predictions_sha256
    decision = decide_btc_continuation(report)
    markdown = _comparison_markdown(report, decision).encode("utf-8")
    _assert_path_free(rows, "predictions")
    _assert_path_free(report, "report")
    _assert_path_free(decision, "decision")
    _preflight_immutable_outputs(
        {
            predictions_output: predictions_payload,
            report_output: canonical_json_bytes(report) + b"\n",
            decision_output: canonical_json_bytes(decision) + b"\n",
            markdown_output: markdown,
        }
    )
    write_immutable_bytes(predictions_output, predictions_payload)
    write_immutable_json(report_output, report)
    write_immutable_json(decision_output, decision)
    write_immutable_bytes(markdown_output, markdown)
    return {
        "predictions_sha256": file_sha256(predictions_output),
        "report_sha256": canonical_sha256(report),
        "decision_sha256": canonical_sha256(decision),
        "markdown_sha256": file_sha256(markdown_output),
    }


def replay_btc_validation_artifacts(
    *,
    manifest_path: Path,
    predictions_path: Path,
    config: EvaluationConfig,
    expected_report_path: Path,
    expected_decision_path: Path,
    bootstrap_resamples: int = 10_000,
) -> dict[str, str]:
    manifest = load_btc_validation_manifest(manifest_path)
    report = _read_json_object(expected_report_path, "BTC validation report")
    decision = _read_json_object(expected_decision_path, "BTC validation decision")
    try:
        payload = predictions_path.resolve(strict=True).read_bytes()
        rows = [json.loads(line) for line in payload.splitlines() if line]
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("BTC validation predictions are unreadable") from error
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError("BTC validation predictions must contain object rows")
    predictions_sha256 = hashlib.sha256(payload).hexdigest()
    if (
        report.get("manifest_sha256") != canonical_sha256(manifest)
        or report.get("predictions_sha256") != predictions_sha256
    ):
        raise ValueError("BTC replay identity does not match frozen artifacts")

    manifest_tracks = {
        track.get("track_id"): track
        for track in manifest["tracks"]
        if isinstance(track, Mapping)
    }
    if len(manifest_tracks) != len(manifest["tracks"]):
        raise ValueError("BTC replay manifest track identities are invalid")
    btc_tracks: dict[
        str, tuple[Sequence[ScoredChordInterval], Sequence[ScoredChordInterval]]
    ] = {}
    legacy_tracks: dict[
        str, tuple[Sequence[ScoredChordInterval], Sequence[ScoredChordInterval]]
    ] = {}
    metadata: dict[str, dict[str, str]] = {}
    vocabulary = ChordVocabulary.default()
    consumed: set[str] = set()
    for row in rows:
        track_id = row.get("track_id")
        track = manifest_tracks.get(track_id)
        if not isinstance(track_id, str) or track is None or track_id in consumed:
            raise ValueError("BTC replay prediction track identity is invalid")
        if (
            row.get("split") != "validation"
            or row.get("dataset_id") != track.get("dataset_id")
            or row.get("cover_group_id") != track.get("cover_group_id")
            or row.get("duration_seconds") != track.get("duration_seconds")
        ):
            raise ValueError("BTC replay prediction metadata does not match manifest")
        reference = manifest_reference_intervals(track, vocabulary)
        duration = float(track["duration_seconds"])
        btc_prediction = _deserialize_intervals(row.get("btc_events"), duration, "BTC")
        legacy_prediction = _deserialize_intervals(
            row.get("legacy_events"), duration, "legacy"
        )
        btc_tracks[track_id] = (reference, btc_prediction)
        legacy_tracks[track_id] = (reference, legacy_prediction)
        metadata[track_id] = {
            "dataset_id": str(track["dataset_id"]),
            "cover_group_id": str(track["cover_group_id"]),
            "split": "validation",
        }
        consumed.add(track_id)
    if consumed != set(manifest_tracks):
        raise ValueError("BTC replay predictions do not cover the manifest")

    btc_evaluation = evaluate_dataset_strata(btc_tracks, metadata, config)
    legacy_evaluation = evaluate_dataset_strata(legacy_tracks, metadata, config)
    paired_bootstrap = paired_group_bootstrap_delta(
        btc_tracks,
        legacy_tracks,
        metadata,
        config,
        resamples=bootstrap_resamples,
    )
    if (
        canonical_sha256(btc_evaluation)
        != canonical_sha256(report["candidates"]["btc"]["evaluation"])
        or canonical_sha256(legacy_evaluation)
        != canonical_sha256(report["candidates"]["legacy"]["evaluation"])
        or canonical_sha256(paired_bootstrap)
        != canonical_sha256(report["comparison"]["paired_bootstrap"])
    ):
        raise ValueError("BTC replay metrics do not reproduce the frozen report")
    recomputed_decision = decide_btc_continuation(report)
    if canonical_sha256(recomputed_decision) != canonical_sha256(decision):
        raise ValueError("BTC replay decision does not reproduce the frozen decision")
    return {
        "predictions_sha256": predictions_sha256,
        "report_sha256": canonical_sha256(report),
        "decision_sha256": canonical_sha256(decision),
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


def _deserialize_intervals(
    value: Any, duration: float, name: str
) -> tuple[ScoredChordInterval, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} replay prediction must contain events")
    intervals: list[ScoredChordInterval] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise ValueError(f"{name} replay event must be an object")
        chord = CanonicalChord(
            root=raw.get("root"),
            quality=raw.get("quality"),
            bass=raw.get("bass"),
            mapping_reason=raw.get("mapping_reason"),
        )
        chord.display_symbol
        try:
            intervals.append(
                ScoredChordInterval(
                    float(raw["start_seconds"]),
                    float(raw["end_seconds"]),
                    chord,
                    float(raw["confidence"]),
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"{name} replay event is invalid") from error
    result = tuple(intervals)
    _validate_prediction_extent(result, duration, name)
    return result


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


def _comparison_markdown(
    report: Mapping[str, Any], decision: Mapping[str, Any]
) -> str:
    btc = report["candidates"]["btc"]
    legacy = report["candidates"]["legacy"]
    btc_aggregate = btc["evaluation"]["aggregate"]
    legacy_aggregate = legacy["evaluation"]["aggregate"]
    lines = [
        "# BTC-170 validation comparison",
        "",
        f"- Decision: `{decision['status']}`",
        f"- Tracks: {report['track_count']}",
        f"- Manifest SHA-256: `{report['manifest_sha256']}`",
        f"- Predictions SHA-256: `{report['predictions_sha256']}`",
        "- Confidence: uncalibrated, diagnostic only",
        "- Bass/inversion evaluation: unavailable (BTC has no bass head)",
        "- Product default: unchanged (`chroma-triad-viterbi-v1`)",
        "",
        "| Candidate | Exact WCSR | Root WCSR | Boundary F1 | Events/reference |",
        "| --- | ---: | ---: | ---: | ---: |",
        (
            f"| BTC-170 | {btc_aggregate['weighted_scores']['exact_quality']:.6f} | "
            f"{btc_aggregate['weighted_scores']['root']:.6f} | "
            f"{btc_aggregate['boundary']['f1']:.6f} | {btc['event_ratio']:.6f} |"
        ),
        (
            f"| Legacy | {legacy_aggregate['weighted_scores']['exact_quality']:.6f} | "
            f"{legacy_aggregate['weighted_scores']['root']:.6f} | "
            f"{legacy_aggregate['boundary']['f1']:.6f} | "
            f"{legacy['event_ratio']:.6f} |"
        ),
        "",
    ]
    return "\n".join(lines)


def _assert_path_free(value: Any, label: str) -> None:
    forbidden_keys = ("audio_path", "dataset_root", "checkpoint_path", "cache_path")

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if not isinstance(key, str) or key in forbidden_keys:
                    raise ValueError(f"BTC {label} contains a forbidden path field")
                visit(nested)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            for nested in item:
                visit(nested)
        elif isinstance(item, str) and (
            item.startswith(("/", "\\\\"))
            or re.match(r"^[A-Za-z]:[\\/]", item) is not None
        ):
            raise ValueError(f"BTC {label} contains an absolute path")

    visit(value)


def _preflight_immutable_outputs(outputs: Mapping[Path, bytes]) -> None:
    for path, payload in outputs.items():
        if path.exists() and path.read_bytes() != payload:
            raise FileExistsError(
                f"frozen artifact already exists with different content: {path}"
            )


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is unreadable") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


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


def _parse_path_mappings(values: Sequence[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        key, separator, raw_path = value.partition("=")
        if not separator or not key or not raw_path or key in result:
            raise ValueError("BTC dataset roots must use unique NAME=PATH values")
        result[key] = Path(raw_path)
    return result


def _load_artifact_lock(path: Path) -> BtcArtifactLock:
    value = _read_json_object(path, "BTC artifact lock")
    try:
        return BtcArtifactLock(**value)
    except TypeError as error:
        raise ValueError("BTC artifact lock fields are invalid") from error


def _artifact_source_matches_lock(
    source: BtcArtifactSource, lock: BtcArtifactLock
) -> bool:
    return (
        source.repository == lock.repository
        and source.repository_ref == lock.repository_ref
        and source.source_url == lock.source_url
        and source.size_bytes == lock.size_bytes
        and source.git_blob_sha1 == lock.git_blob_sha1
        and source.license_spdx == lock.license_spdx
    )


def _default_audio_loader(path: Path) -> tuple[np.ndarray, int]:
    import librosa

    samples, sample_rate = librosa.load(path, sr=None, mono=True, dtype=np.float32)
    return np.asarray(samples, dtype=np.float32), int(sample_rate)


def _default_legacy_recognizer(
    samples: np.ndarray, sample_rate: int
) -> Sequence[_LegacyEvent]:
    from museecho.analysis.chords import estimate_chords

    return estimate_chords(samples, sample_rate)


def _peak_rss_bytes() -> int:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        process = kernel32.GetCurrentProcess()
        succeeded = psapi.GetProcessMemoryInfo(
            process, ctypes.byref(counters), counters.cb
        )
        if not succeeded:
            raise RuntimeError("BTC peak RSS measurement failed")
        return int(counters.PeakWorkingSetSize)
    import resource

    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(usage if sys.platform == "darwin" else usage * 1024)


def _prediction_event_identity(rows: Sequence[Mapping[str, Any]]) -> str:
    stable = [
        {
            key: row[key]
            for key in (
                "split",
                "track_id",
                "dataset_id",
                "cover_group_id",
                "duration_seconds",
                "btc_events",
                "legacy_events",
            )
        }
        for row in rows
    ]
    return canonical_sha256(stable)


def _source_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    commit = completed.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("BTC source commit identity is invalid")
    return commit


def _run_official_cli(arguments: argparse.Namespace) -> dict[str, Any]:
    load_btc_validation_manifest(arguments.manifest)
    source = load_btc_source(arguments.source)
    lock = _load_artifact_lock(arguments.artifact_lock)
    if not _artifact_source_matches_lock(source, lock):
        raise ValueError("BTC source descriptor does not match the artifact lock")
    config = _load_evaluation_config(arguments.evaluation_config)
    dataset_roots = _parse_path_mappings(arguments.dataset_root)
    contract_holder: dict[str, Any] = {}

    def create_recognizer() -> BtcRecognizer:
        checkpoint = load_btc_checkpoint(
            arguments.checkpoint,
            lock,
            BtcModelConfig.official(),
        )
        contract_holder.update(checkpoint_contract(checkpoint))
        return BtcRecognizer(checkpoint)

    run_arguments = {
        "manifest_path": arguments.manifest,
        "dataset_roots": dataset_roots,
        "config": config,
        "btc_recognizer_factory": create_recognizer,
        "legacy_recognize": _default_legacy_recognizer,
        "audio_loader": _default_audio_loader,
        "peak_rss_reader": _peak_rss_bytes,
        "checkpoint_security_passed": True,
        "artifact_identity_passed": True,
        "bootstrap_resamples": arguments.bootstrap_resamples,
    }
    first = run_btc_validation_experiment(
        **run_arguments,
        deterministic_replay=False,
    )
    second = run_btc_validation_experiment(
        **run_arguments,
        deterministic_replay=True,
    )
    first_identity = _prediction_event_identity(first["prediction_rows"])
    second_identity = _prediction_event_identity(second["prediction_rows"])
    if first_identity != second_identity:
        raise RuntimeError("BTC deterministic prediction replay does not match")
    first = deepcopy(first)
    first["report"]["comparison"]["deterministic_prediction_replay"] = True
    first["report"]["comparison"]["deterministic_prediction_sha256"] = first_identity
    identity = {
        "source_commit": _source_commit(),
        "evaluation_config_sha256": file_sha256(arguments.evaluation_config),
        "source_descriptor_sha256": file_sha256(arguments.source),
        "artifact_lock_sha256": file_sha256(arguments.artifact_lock),
        "checkpoint_tensor_contract_sha256": contract_holder[
            "tensor_contract_sha256"
        ],
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "numpy_version": np.__version__,
        "librosa_version": importlib.metadata.version("librosa"),
        "torch_version": torch.__version__,
        "torch_num_threads": 1,
    }
    frozen = freeze_btc_validation_artifacts(
        first,
        identity=identity,
        predictions_output=arguments.predictions_output,
        report_output=arguments.report_output,
        decision_output=arguments.decision_output,
        markdown_output=arguments.markdown_output,
    )
    return {
        "status": _read_json_object(arguments.decision_output, "BTC decision")[
            "status"
        ],
        **frozen,
    }


def _load_evaluation_config(path: Path) -> EvaluationConfig:
    from museecho_ml.evaluation.legacy_adapter import load_evaluation_config

    return load_evaluation_config(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BTC-170 validation-only experiment")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--manifest", type=Path, required=True)
    run_parser.add_argument("--dataset-root", action="append", required=True)
    run_parser.add_argument("--evaluation-config", type=Path, required=True)
    run_parser.add_argument("--source", type=Path, required=True)
    run_parser.add_argument("--artifact-lock", type=Path, required=True)
    run_parser.add_argument("--checkpoint", type=Path, required=True)
    run_parser.add_argument("--predictions-output", type=Path, required=True)
    run_parser.add_argument("--report-output", type=Path, required=True)
    run_parser.add_argument("--decision-output", type=Path, required=True)
    run_parser.add_argument("--markdown-output", type=Path, required=True)
    run_parser.add_argument("--bootstrap-resamples", type=int, default=10_000)
    replay_parser = subparsers.add_parser("replay")
    replay_parser.add_argument("--manifest", type=Path, required=True)
    replay_parser.add_argument("--evaluation-config", type=Path, required=True)
    replay_parser.add_argument("--predictions", type=Path, required=True)
    replay_parser.add_argument("--expected-report", type=Path, required=True)
    replay_parser.add_argument("--expected-decision", type=Path, required=True)
    replay_parser.add_argument("--bootstrap-resamples", type=int, default=10_000)
    arguments = parser.parse_args(argv)

    if arguments.command == "run":
        result = _run_official_cli(arguments)
    else:
        result = replay_btc_validation_artifacts(
            manifest_path=arguments.manifest,
            predictions_path=arguments.predictions,
            config=_load_evaluation_config(arguments.evaluation_config),
            expected_report_path=arguments.expected_report,
            expected_decision_path=arguments.expected_decision,
            bootstrap_resamples=arguments.bootstrap_resamples,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
