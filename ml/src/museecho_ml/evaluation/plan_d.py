from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from museecho_ml.artifacts import (
    canonical_json_bytes,
    canonical_sha256,
    file_sha256,
    write_immutable_json,
)
from museecho_ml.data.plan_d import (
    load_plan_d_development_manifest,
    load_plan_d_protocol,
)
from museecho_ml.evaluation.metrics import ScoredChordInterval
from museecho_ml.evaluation.report import EvaluationConfig
from museecho_ml.evaluation.statistics import evaluate_dataset_strata
from museecho_ml.labels import CanonicalChord
from museecho_ml.postprocess.hybrid import (
    HybridDecodeConfig,
    HybridFrameProbabilities,
    decode_hybrid,
)
from museecho_ml.postprocess.hybrid_calibration import (
    HybridCalibrationParameters,
    HybridCalibrationSample,
    fit_hybrid_calibration,
)
from museecho_ml.vocabulary import ChordVocabulary

_SEEDS = (20260821, 20260822, 20260823)
_IDENTITY_FIELDS = ("manifest_sha256", "vocabulary_sha256")
_ML_ROOT = Path(__file__).resolve().parents[3]
_REPOSITORY_ROOT = _ML_ROOT.parent


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


def collect_plan_d_deep_predictions(
    *,
    protocol_path: Path,
    split: str,
    manifest_path: Path,
    checkpoint_path: Path,
    seed: int,
    output_path: Path,
) -> dict[str, Any]:
    if split not in {"calibration", "validation"}:
        raise ValueError("Plan D prediction collection forbids test split")
    protocol = load_plan_d_protocol(protocol_path)
    if seed not in protocol["seeds"]:
        raise ValueError("Plan D prediction seed is not frozen")
    manifest_sha256 = protocol["development_splits"][split]["manifest_sha256"]
    load_plan_d_development_manifest(
        manifest_path,
        expected_split=split,
        expected_sha256=manifest_sha256,
        protocol=protocol,
    )
    checkpoint_sha256 = _expected_plan_c_checkpoint_sha(protocol, seed)
    from museecho_ml.evaluation.deep_adapter import collect_checkpoint_predictions

    predictions = collect_checkpoint_predictions(
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        config_path=_ML_ROOT / "configs" / "train-plan-c-v1.json",
        vocabulary_path=_REPOSITORY_ROOT / "docs" / "ml" / "plan-c" / "vocabulary-v1.json",
        expected_manifest_sha256=manifest_sha256,
        expected_checkpoint_sha256=checkpoint_sha256,
    )
    write_plan_d_raw_predictions(
        output_path,
        predictions,
        seed=seed,
        manifest_sha256=manifest_sha256,
        checkpoint_sha256=checkpoint_sha256,
        vocabulary_sha256=protocol["plan_c"]["vocabulary_sha256"],
    )
    return {
        "status": "completed",
        "seed": seed,
        "split": split,
        "track_count": len(predictions),
        "output_sha256": file_sha256(output_path),
    }


def collect_plan_d_legacy_predictions(
    *,
    protocol_path: Path,
    split: str,
    manifest_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    if split != "validation":
        raise ValueError("Plan D legacy collection forbids test split")
    protocol = load_plan_d_protocol(protocol_path)
    manifest_sha256 = protocol["development_splits"][split]["manifest_sha256"]
    manifest = load_plan_d_development_manifest(
        manifest_path,
        expected_split=split,
        expected_sha256=manifest_sha256,
        protocol=protocol,
    )
    from museecho_ml.evaluation.legacy_adapter import (
        _default_audio_loader,
        _default_recognizer,
        evaluate_legacy_manifest,
        load_evaluation_config,
    )
    from museecho_ml.training.train import (
        _config_base,
        _resolve_relative,
        load_train_config,
    )

    config_path = _ML_ROOT / "configs" / "train-plan-c-v1.json"
    train_config = load_train_config(config_path)
    base = _config_base(config_path)
    roots = {
        dataset_id: _resolve_relative(base, root, must_exist=True)
        for dataset_id, root in train_config.dataset_roots.items()
    }
    evaluated = evaluate_legacy_manifest(
        manifest,
        dataset_roots=roots,
        config=load_evaluation_config(_ML_ROOT / "configs" / "evaluation-v1.json"),
        recognize=_default_recognizer,
        audio_loader=_default_audio_loader,
    )
    manifest_tracks = {track["track_id"]: track for track in manifest["tracks"]}
    tracks = []
    for prediction in evaluated["predictions"]:
        metadata = manifest_tracks[prediction["track_id"]]
        tracks.append(
            {
                "track_id": prediction["track_id"],
                "dataset_id": metadata["dataset_id"],
                "cover_group_id": metadata["cover_group_id"],
                "duration_seconds": metadata["duration_seconds"],
                "events": prediction["events"],
            }
        )
    body = {
        "schema_version": 1,
        "format_version": "plan-d-legacy-predictions-v1",
        "split": split,
        "manifest_sha256": manifest_sha256,
        "algorithm_version": evaluated["report"]["algorithm_version"],
        "tracks": tracks,
    }
    result = {**body, "predictions_sha256": canonical_sha256(body)}
    write_immutable_json(output_path, result)
    return {
        "status": "completed",
        "split": split,
        "track_count": len(tracks),
        "predictions_sha256": result["predictions_sha256"],
    }


def load_plan_d_legacy_predictions(
    path: Path,
) -> tuple[dict[str, tuple[ScoredChordInterval, ...]], dict[str, Any]]:
    try:
        payload = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Plan D legacy predictions are unreadable") from error
    if not isinstance(payload, dict) or payload.get("split") != "validation":
        raise ValueError("Plan D legacy predictions forbid test split")
    body = dict(payload)
    embedded = body.pop("predictions_sha256", None)
    if not isinstance(embedded, str) or canonical_sha256(body) != embedded:
        raise ValueError("Plan D legacy prediction SHA-256 mismatch")
    predictions: dict[str, tuple[ScoredChordInterval, ...]] = {}
    for track in payload.get("tracks", []):
        track_id = track.get("track_id")
        if not isinstance(track_id, str) or track_id in predictions:
            raise ValueError("Plan D legacy track identity is invalid")
        predictions[track_id] = tuple(
            _deserialize_interval(event) for event in track.get("events", [])
        )
    if not predictions:
        raise ValueError("Plan D legacy predictions cannot be empty")
    identity = {
        "algorithm_version": payload["algorithm_version"],
        "manifest_sha256": payload["manifest_sha256"],
        "split": payload["split"],
    }
    return predictions, identity


def write_plan_d_raw_predictions(
    path: Path,
    predictions: Sequence[Any],
    *,
    seed: int,
    manifest_sha256: str,
    checkpoint_sha256: str,
    vocabulary_sha256: str,
) -> None:
    if type(seed) is not int or seed not in _SEEDS or not predictions:
        raise ValueError("Plan D raw prediction identity is invalid")
    hashes = (manifest_sha256, checkpoint_sha256, vocabulary_sha256)
    if any(not isinstance(value, str) or len(value) != 64 for value in hashes):
        raise ValueError("Plan D raw prediction hashes are invalid")
    splits = {getattr(item, "split", None) for item in predictions}
    if len(splits) != 1 or next(iter(splits)) not in {"calibration", "validation"}:
        raise ValueError("Plan D raw predictions forbid test split")
    arrays: dict[str, np.ndarray] = {}
    tracks: list[dict[str, Any]] = []
    for index, item in enumerate(sorted(predictions, key=lambda value: value.track_id)):
        prefix = f"track_{index}"
        arrays[f"{prefix}_frame_times"] = np.asarray(item.frame_times, dtype=np.float64)
        arrays[f"{prefix}_valid_mask"] = np.asarray(item.valid_mask, dtype=np.bool_)
        arrays[f"{prefix}_root_logits"] = np.asarray(item.root_logits, dtype=np.float64)
        arrays[f"{prefix}_quality_logits"] = np.asarray(
            item.quality_logits, dtype=np.float64
        )
        arrays[f"{prefix}_bass_logits"] = np.asarray(item.bass_logits, dtype=np.float64)
        arrays[f"{prefix}_boundary_logits"] = np.asarray(
            item.boundary_logits, dtype=np.float64
        )
        tracks.append(
            {
                "array_prefix": prefix,
                "track_id": item.track_id,
                "dataset_id": item.dataset_id,
                "cover_group_id": item.cover_group_id,
                "duration_seconds": item.duration_seconds,
                "inference_wall_seconds": item.inference_wall_seconds,
                "reference": [_serialize_interval(value) for value in item.reference],
            }
        )
    metadata = {
        "schema_version": 1,
        "format_version": "plan-d-raw-predictions-v1",
        "seed": seed,
        "split": next(iter(splits)),
        "manifest_sha256": manifest_sha256,
        "checkpoint_sha256": checkpoint_sha256,
        "vocabulary_sha256": vocabulary_sha256,
        "tracks": tracks,
    }
    arrays["metadata"] = np.frombuffer(canonical_json_bytes(metadata), dtype=np.uint8)
    destination = path.resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            np.savez_compressed(output, **arrays)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, destination)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def load_plan_d_raw_predictions(
    path: Path,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from museecho_ml.evaluation.deep_adapter import RawTrackPrediction

    try:
        archive = np.load(path.resolve(strict=True), allow_pickle=False)
    except (OSError, ValueError) as error:
        raise ValueError("Plan D raw prediction archive is unreadable") from error
    with archive:
        try:
            metadata = json.loads(archive["metadata"].tobytes().decode("utf-8"))
        except (KeyError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("Plan D raw prediction metadata is invalid") from error
        if (
            not isinstance(metadata, dict)
            or metadata.get("schema_version") != 1
            or metadata.get("format_version") != "plan-d-raw-predictions-v1"
            or metadata.get("split") not in {"calibration", "validation"}
            or not isinstance(metadata.get("tracks"), list)
            or not metadata["tracks"]
        ):
            raise ValueError("Plan D raw prediction identity is invalid")
        predictions = []
        for track in metadata["tracks"]:
            prefix = track["array_prefix"]
            predictions.append(
                RawTrackPrediction(
                    track_id=track["track_id"],
                    dataset_id=track["dataset_id"],
                    cover_group_id=track["cover_group_id"],
                    split=metadata["split"],
                    duration_seconds=track["duration_seconds"],
                    frame_times=np.asarray(archive[f"{prefix}_frame_times"]),
                    valid_mask=np.asarray(archive[f"{prefix}_valid_mask"]),
                    root_logits=np.asarray(archive[f"{prefix}_root_logits"]),
                    quality_logits=np.asarray(archive[f"{prefix}_quality_logits"]),
                    bass_logits=np.asarray(archive[f"{prefix}_bass_logits"]),
                    boundary_logits=np.asarray(archive[f"{prefix}_boundary_logits"]),
                    reference=tuple(
                        _deserialize_interval(value) for value in track["reference"]
                    ),
                    inference_wall_seconds=track["inference_wall_seconds"],
                )
            )
    identity = {
        field: metadata[field]
        for field in (
            "checkpoint_sha256",
            "manifest_sha256",
            "seed",
            "split",
            "vocabulary_sha256",
        )
    }
    return tuple(predictions), identity


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
    reference_events = 0
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
        reference_events += len(raw.reference)
        cpu_seconds += float(raw.inference_wall_seconds)
    report = evaluate_dataset_strata(
        tracks, metadata, EvaluationConfig(publication_threshold=0.0)
    )
    report["event_ratio"] = predicted_events / reference_events
    report["inference_wall_seconds"] = cpu_seconds
    return report


def validate_plan_d_replay_identity(
    *,
    protocol: Mapping[str, Any],
    seed: int,
    expected_checkpoint_sha256: str,
    deep_calibration_identity: Mapping[str, Any],
    deep_validation_identity: Mapping[str, Any],
    legacy_identity: Mapping[str, Any],
) -> dict[str, Any]:
    calibration_sha256 = protocol["development_splits"]["calibration"][
        "manifest_sha256"
    ]
    validation_sha256 = protocol["development_splits"]["validation"][
        "manifest_sha256"
    ]
    vocabulary_sha256 = protocol["plan_c"]["vocabulary_sha256"]
    expected_calibration = {
        "checkpoint_sha256": expected_checkpoint_sha256,
        "manifest_sha256": calibration_sha256,
        "seed": seed,
        "split": "calibration",
        "vocabulary_sha256": vocabulary_sha256,
    }
    expected_validation = {
        **expected_calibration,
        "manifest_sha256": validation_sha256,
        "split": "validation",
    }
    expected_legacy = {
        "algorithm_version": protocol["legacy_algorithm"]["version"],
        "manifest_sha256": validation_sha256,
        "split": "validation",
    }
    if (
        dict(deep_calibration_identity) != expected_calibration
        or dict(deep_validation_identity) != expected_validation
        or dict(legacy_identity) != expected_legacy
    ):
        raise ValueError("Plan D replay identity drift")
    return {
        "seed": seed,
        "checkpoint_sha256": expected_checkpoint_sha256,
        "calibration_manifest_sha256": calibration_sha256,
        "manifest_sha256": validation_sha256,
        "vocabulary_sha256": vocabulary_sha256,
        "legacy_algorithm_version": expected_legacy["algorithm_version"],
    }


def fit_plan_d_hybrid_calibration(
    predictions: Sequence[Any],
    *,
    vocabulary: ChordVocabulary,
    minimum_precision: float,
    minimum_coverage: float,
    minimum_quality_groups: int,
) -> HybridCalibrationParameters:
    if not predictions or any(
        getattr(item, "split", None) != "calibration" for item in predictions
    ):
        raise ValueError("Plan D hybrid calibration requires calibration split")
    samples: list[HybridCalibrationSample] = []
    for raw in sorted(predictions, key=lambda item: item.track_id):
        times = np.asarray(raw.frame_times, dtype=np.float64)
        valid = np.asarray(raw.valid_mask)
        if (
            times.ndim != 1
            or valid.dtype != np.bool_
            or valid.shape != times.shape
            or not valid.any()
            or np.any(np.maximum.accumulate(~valid) & valid)
        ):
            raise ValueError("Plan D calibration frame evidence is invalid")
        count = int(valid.sum())
        times = times[:count]
        probabilities = _softmax(np.asarray(raw.quality_logits)[:count])
        candidates = np.argmax(probabilities, axis=1)
        durations = np.concatenate(
            (times[1:], np.asarray([raw.duration_seconds], dtype=np.float64))
        ) - times
        if np.any(durations <= 0) or not np.isfinite(durations).all():
            raise ValueError("Plan D calibration frame durations are invalid")
        reference_index = 0
        for frame_index, frame_time in enumerate(times):
            while frame_time >= raw.reference[reference_index].end_seconds:
                reference_index += 1
            quality = vocabulary.quality_labels[int(candidates[frame_index])]
            if quality in {"N", "X"}:
                continue
            samples.append(
                HybridCalibrationSample(
                    cover_group_id=raw.cover_group_id,
                    quality=quality,
                    confidence=float(
                        probabilities[frame_index, candidates[frame_index]]
                    ),
                    correct=quality == raw.reference[reference_index].chord.quality,
                    duration_seconds=float(durations[frame_index]),
                )
            )
    return fit_hybrid_calibration(
        samples,
        minimum_precision=minimum_precision,
        minimum_coverage=minimum_coverage,
        minimum_quality_groups=minimum_quality_groups,
    )


def build_plan_d_seed_replay_artifact(
    *,
    protocol_sha256: str,
    seed: int,
    identity: Mapping[str, Any],
    calibration: HybridCalibrationParameters,
    legacy: Mapping[str, Any],
    deep: Mapping[str, Any],
    hybrid: Mapping[str, Any],
) -> dict[str, Any]:
    if seed not in _SEEDS or not isinstance(calibration, HybridCalibrationParameters):
        raise ValueError("Plan D replay artifact identity is invalid")
    reports = {"legacy": legacy, "deep-only": deep, "hybrid": hybrid}
    if (
        legacy.get("variant") != "legacy"
        or legacy.get("seed") is not None
        or deep.get("variant") != "deep-only"
        or deep.get("seed") != seed
        or hybrid.get("variant") != "hybrid"
        or hybrid.get("seed") != seed
        or any(report.get("split") != "validation" for report in reports.values())
    ):
        raise ValueError("Plan D replay artifact report identity drift")
    manifest_sha256 = identity.get("manifest_sha256")
    vocabulary_sha256 = identity.get("vocabulary_sha256")
    if any(
        report.get("manifest_sha256") != manifest_sha256
        or report.get("vocabulary_sha256") != vocabulary_sha256
        for report in reports.values()
    ):
        raise ValueError("Plan D replay artifact report identity drift")
    body = {
        "schema_version": 1,
        "experiment_version": "plan-d-D1-replay-v1",
        "status": "completed",
        "seed": seed,
        "protocol_sha256": protocol_sha256,
        "identity": dict(identity),
        "hybrid_calibration": calibration.to_dict(),
        "reports": reports,
    }
    serialized = canonical_json_bytes(body).decode("utf-8").lower()
    if "audio_path" in serialized or "checkpoint_path" in serialized:
        raise ValueError("Plan D public replay artifact contains a path")
    return {**body, "experiment_sha256": canonical_sha256(body)}


def decide_plan_d_replay_reports(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    gates: PlanDDevelopmentGates,
    protocol_sha256: str,
) -> dict[str, Any]:
    if not isinstance(artifacts, Sequence) or len(artifacts) != 3:
        raise ValueError("Plan D replay decision requires three reports")
    ordered = tuple(sorted(artifacts, key=lambda item: item.get("seed", -1)))
    if tuple(item.get("seed") for item in ordered) != _SEEDS:
        raise ValueError("Plan D replay decision seed identity drift")
    for artifact in ordered:
        body = dict(artifact)
        embedded = body.pop("experiment_sha256", None)
        if (
            not isinstance(embedded, str)
            or canonical_sha256(body) != embedded
            or artifact.get("protocol_sha256") != protocol_sha256
            or artifact.get("status") != "completed"
        ):
            raise ValueError("Plan D replay decision artifact identity drift")
    legacy_reports = tuple(item["reports"]["legacy"] for item in ordered)
    if any(
        canonical_json_bytes(report) != canonical_json_bytes(legacy_reports[0])
        for report in legacy_reports[1:]
    ):
        raise ValueError("Plan D replay legacy report drift")
    decision = decide_plan_d_development(
        legacy=legacy_reports[0],
        deep_by_seed=tuple(item["reports"]["deep-only"] for item in ordered),
        hybrid_by_seed=tuple(item["reports"]["hybrid"] for item in ordered),
        gates=gates,
    )
    body = {
        "schema_version": 1,
        "decision_version": "plan-d-replay-decision-v1",
        "status": decision["status"],
        "protocol_sha256": protocol_sha256,
        "report_sha256s": [item["experiment_sha256"] for item in ordered],
        "checks": decision["checks"],
        "continuation_checks": decision["continuation_checks"],
        "summary": decision["summary"],
    }
    return {**body, "decision_sha256": canonical_sha256(body)}


def replay_plan_d_seed(
    *,
    protocol_path: Path,
    seed: int,
    deep_calibration_path: Path,
    deep_validation_path: Path,
    legacy_validation_path: Path,
    run_output_path: Path,
    public_output_path: Path,
) -> dict[str, Any]:
    input_identities = (
        str(deep_calibration_path),
        str(deep_validation_path),
        str(legacy_validation_path),
    )
    from museecho_ml.data.plan_d import PLAN_C_TEST_MANIFEST_SHA256

    if any(PLAN_C_TEST_MANIFEST_SHA256 in value for value in input_identities):
        raise ValueError("Plan D replay forbids the Plan C test manifest")
    protocol = load_plan_d_protocol(protocol_path)
    if seed not in protocol["seeds"]:
        raise ValueError("Plan D replay seed is not frozen")
    expected_checkpoint_sha256 = _expected_plan_c_checkpoint_sha(protocol, seed)
    calibration_raw, calibration_identity = load_plan_d_raw_predictions(
        deep_calibration_path
    )
    validation_raw, validation_identity = load_plan_d_raw_predictions(
        deep_validation_path
    )
    legacy_by_track, legacy_identity = load_plan_d_legacy_predictions(
        legacy_validation_path
    )
    identity = validate_plan_d_replay_identity(
        protocol=protocol,
        seed=seed,
        expected_checkpoint_sha256=expected_checkpoint_sha256,
        deep_calibration_identity=calibration_identity,
        deep_validation_identity=validation_identity,
        legacy_identity=legacy_identity,
    )
    if set(legacy_by_track) != {item.track_id for item in validation_raw}:
        raise ValueError("Plan D replay identity drift")
    vocabulary = _load_plan_d_vocabulary(protocol)
    development_gate = protocol["development_gate"]
    hybrid_calibration = fit_plan_d_hybrid_calibration(
        calibration_raw,
        vocabulary=vocabulary,
        minimum_precision=development_gate["minimum_known_precision"],
        minimum_coverage=development_gate["minimum_coverage"],
        minimum_quality_groups=protocol["minimum_quality_groups"],
    )
    hybrid_config = HybridDecodeConfig(
        known_threshold=hybrid_calibration.known_threshold,
        quality_thresholds=hybrid_calibration.quality_thresholds,
        bass_threshold=hybrid_calibration.bass_threshold,
        minimum_support_fraction=hybrid_calibration.minimum_support_fraction,
        minimum_event_seconds=0.1,
        hysteresis_frames=1,
        maximum_event_ratio=development_gate["maximum_event_ratio"],
    )
    hybrid_evaluation = evaluate_plan_d_replay(
        validation_raw,
        legacy_by_track=legacy_by_track,
        vocabulary=vocabulary,
        calibration=hybrid_calibration,
        config=hybrid_config,
    )
    legacy_evaluation = _evaluate_plan_d_legacy_replay(
        validation_raw, legacy_by_track=legacy_by_track
    )
    deep_evaluation, deep_artifacts = _load_plan_c_validation_evidence(
        protocol=protocol,
        seed=seed,
        checkpoint_sha256=expected_checkpoint_sha256,
    )
    report_identity = {
        "manifest_sha256": identity["manifest_sha256"],
        "vocabulary_sha256": identity["vocabulary_sha256"],
    }
    legacy_report = _standardize_plan_d_evaluation(
        legacy_evaluation,
        variant="legacy",
        seed=None,
        identity=report_identity,
        cpu_seconds=0.0,
    )
    deep_report = _standardize_plan_d_evaluation(
        deep_evaluation,
        variant="deep-only",
        seed=seed,
        identity=report_identity,
        cpu_seconds=None,
    )
    hybrid_report = _standardize_plan_d_evaluation(
        hybrid_evaluation,
        variant="hybrid",
        seed=seed,
        identity=report_identity,
        cpu_seconds=float(hybrid_evaluation["inference_wall_seconds"]),
    )
    public_identity = {
        **identity,
        "plan_c_calibration_sha256": deep_artifacts["calibration_sha256"],
        "plan_c_threshold_sha256": deep_artifacts["threshold_sha256"],
    }
    public = build_plan_d_seed_replay_artifact(
        protocol_sha256=protocol["protocol_sha256"],
        seed=seed,
        identity=public_identity,
        calibration=hybrid_calibration,
        legacy=legacy_report,
        deep=deep_report,
        hybrid=hybrid_report,
    )
    run_body = {
        "schema_version": 1,
        "run_version": "plan-d-D1-replay-run-v1",
        "status": "completed",
        "seed": seed,
        "identity": public_identity,
        "hybrid_calibration": hybrid_calibration.to_dict(),
        "evaluations": {
            "deep-only": deep_evaluation,
            "hybrid": hybrid_evaluation,
            "legacy": legacy_evaluation,
        },
        "public_experiment_sha256": public["experiment_sha256"],
    }
    run_result = {**run_body, "run_sha256": canonical_sha256(run_body)}
    write_immutable_json(run_output_path, run_result)
    write_immutable_json(public_output_path, public)
    return public


def decide_plan_d_replay_from_files(
    *, protocol_path: Path, report_paths: Sequence[Path], output_path: Path
) -> dict[str, Any]:
    protocol = load_plan_d_protocol(protocol_path)
    reports = tuple(_load_replay_public_artifact(path) for path in report_paths)
    gate = protocol["development_gate"]
    if gate["minimum_exact_gain_over_legacy"] != gate[
        "minimum_exact_gain_over_deep"
    ]:
        raise ValueError("Plan D replay gain gates are inconsistent")
    decision = decide_plan_d_replay_reports(
        reports,
        gates=PlanDDevelopmentGates(
            minimum_exact=gate["minimum_exact"],
            minimum_exact_gain=gate["minimum_exact_gain_over_legacy"],
            minimum_known_precision=gate["minimum_known_precision"],
            minimum_coverage=gate["minimum_coverage"],
            minimum_event_ratio=gate["minimum_event_ratio"],
            maximum_event_ratio=gate["maximum_event_ratio"],
            maximum_dataset_regression=gate["maximum_dataset_regression"],
            maximum_seed_span=gate["maximum_seed_span"],
            maximum_cpu_seconds=gate["maximum_cpu_seconds"],
        ),
        protocol_sha256=protocol["protocol_sha256"],
    )
    write_immutable_json(output_path, decision)
    return decision


def _load_plan_d_vocabulary(protocol: Mapping[str, Any]) -> ChordVocabulary:
    path = _REPOSITORY_ROOT / "docs" / "ml" / "plan-c" / "vocabulary-v1.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Plan D replay vocabulary is unreadable") from error
    vocabulary = ChordVocabulary.from_dict(payload)
    if payload.get("vocabulary_sha256") != protocol["plan_c"]["vocabulary_sha256"]:
        raise ValueError("Plan D replay vocabulary identity drift")
    return vocabulary


def _evaluate_plan_d_legacy_replay(
    raw_predictions: Sequence[Any],
    *,
    legacy_by_track: Mapping[str, Sequence[ScoredChordInterval]],
) -> dict[str, Any]:
    tracks = {
        raw.track_id: (raw.reference, tuple(legacy_by_track[raw.track_id]))
        for raw in raw_predictions
    }
    metadata = {
        raw.track_id: {
            "dataset_id": raw.dataset_id,
            "cover_group_id": raw.cover_group_id,
            "split": raw.split,
        }
        for raw in raw_predictions
    }
    report = evaluate_dataset_strata(
        tracks, metadata, EvaluationConfig(publication_threshold=0.0)
    )
    report["event_ratio"] = sum(len(value) for value in legacy_by_track.values()) / sum(
        len(raw.reference) for raw in raw_predictions
    )
    report["inference_wall_seconds"] = 0.0
    return report


def _standardize_plan_d_evaluation(
    evaluation: Mapping[str, Any],
    *,
    variant: str,
    seed: int | None,
    identity: Mapping[str, str],
    cpu_seconds: float | None,
) -> dict[str, Any]:
    aggregate = evaluation["aggregate"]
    segmentation = aggregate["segmentation"]
    event_ratio = float(
        evaluation.get(
            "event_ratio",
            segmentation["predicted_events"] / segmentation["reference_events"],
        )
    )
    if cpu_seconds is None:
        five_minute_cpu = float(
            evaluation["selection_metrics"]["five_minute_cpu_wall_seconds"]
        )
    else:
        five_minute_cpu = (
            cpu_seconds / float(evaluation["duration_seconds"]) * 300.0
        )
    report = {
        "split": "validation",
        "variant": variant,
        "seed": seed,
        "manifest_sha256": identity["manifest_sha256"],
        "vocabulary_sha256": identity["vocabulary_sha256"],
        "metrics": {
            "exact_vocabulary_wcsr": float(
                aggregate["weighted_scores"]["exact_quality"]
            ),
            "majmin_wcsr": float(aggregate["weighted_scores"]["majmin"]),
            "known_precision": float(aggregate["published"]["precision"]),
            "coverage": float(aggregate["published"]["coverage"]),
            "boundary_f1": float(aggregate["boundary"]["f1"]),
            "event_ratio": event_ratio,
            "five_minute_cpu_wall_seconds": five_minute_cpu,
        },
        "datasets": {
            dataset: {
                "exact_vocabulary_wcsr": float(
                    value["aggregate"]["weighted_scores"]["exact_quality"]
                )
            }
            for dataset, value in sorted(evaluation["datasets"].items())
        },
        "bootstrap": evaluation["bootstrap"],
    }
    return report


def _load_plan_c_validation_evidence(
    *, protocol: Mapping[str, Any], seed: int, checkpoint_sha256: str
) -> tuple[dict[str, Any], dict[str, str]]:
    candidates = sorted(
        (_ML_ROOT / "runs" / "plan-c").glob(f"*/C1/{seed}/finetune")
    )
    for directory in candidates:
        try:
            payload = json.loads(
                (directory / "validation-report.json").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        body = dict(payload)
        embedded = body.pop("validation_report_sha256", None)
        if (
            not isinstance(embedded, str)
            or canonical_sha256(body) != embedded
            or payload.get("course_id") != "C1"
            or payload.get("seed") != seed
            or payload.get("split") != "validation"
            or payload.get("checkpoint_sha256") != checkpoint_sha256
            or payload.get("validation_manifest_sha256")
            != protocol["development_splits"]["validation"]["manifest_sha256"]
            or payload.get("vocabulary_sha256")
            != protocol["plan_c"]["vocabulary_sha256"]
            or payload.get("protocol_sha256") != protocol["plan_c"]["protocol_sha256"]
            or not isinstance(payload.get("evaluation"), dict)
        ):
            continue
        return payload["evaluation"], {
            "calibration_sha256": payload["calibration_sha256"],
            "threshold_sha256": payload["threshold_sha256"],
        }
    raise ValueError(f"Plan D seed {seed} validation evidence is unavailable")


def _load_replay_public_artifact(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Plan D replay report is unreadable") from error
    if not isinstance(payload, dict):
        raise ValueError("Plan D replay report is invalid")
    body = dict(payload)
    embedded = body.pop("experiment_sha256", None)
    if not isinstance(embedded, str) or canonical_sha256(body) != embedded:
        raise ValueError("Plan D replay report SHA-256 mismatch")
    return payload


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


def _serialize_interval(value: ScoredChordInterval) -> dict[str, Any]:
    return {
        "start_seconds": value.start_seconds,
        "end_seconds": value.end_seconds,
        "root": value.chord.root,
        "quality": value.chord.quality,
        "bass": value.chord.bass,
        "confidence": value.confidence,
    }


def _deserialize_interval(value: Mapping[str, Any]) -> ScoredChordInterval:
    try:
        return ScoredChordInterval(
            float(value["start_seconds"]),
            float(value["end_seconds"]),
            CanonicalChord(
                str(value["root"]), str(value["quality"]), str(value["bass"])
            ),
            float(value["confidence"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Plan D raw prediction reference is invalid") from error


def _expected_plan_c_checkpoint_sha(
    protocol: Mapping[str, Any], seed: int
) -> str:
    path = _REPOSITORY_ROOT / "docs" / "ml" / "plan-c" / "selection-v1.json"
    try:
        selection = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Plan C selection is unreadable") from error
    body = dict(selection)
    embedded_hash = body.pop("selection_sha256", None)
    if (
        not isinstance(embedded_hash, str)
        or canonical_sha256(body) != embedded_hash
        or embedded_hash != protocol["plan_c"]["selection_sha256"]
    ):
        raise ValueError("Plan C selection identity drift")
    runs = selection.get("courses", {}).get("C1", {}).get("runs", [])
    matches = [run for run in runs if run.get("seed") == seed]
    if len(matches) != 1 or not isinstance(matches[0].get("checkpoint_sha256"), str):
        raise ValueError("Plan C seed checkpoint identity is missing")
    return str(matches[0]["checkpoint_sha256"])


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Plan D development-only evaluation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect_deep = subparsers.add_parser("collect-deep")
    collect_deep.add_argument("--protocol", type=Path, required=True)
    collect_deep.add_argument("--split", required=True)
    collect_deep.add_argument("--manifest", type=Path, required=True)
    collect_deep.add_argument("--checkpoint", type=Path, required=True)
    collect_deep.add_argument("--seed", type=int, required=True)
    collect_deep.add_argument("--output", type=Path, required=True)
    collect_legacy = subparsers.add_parser("collect-legacy")
    collect_legacy.add_argument("--protocol", type=Path, required=True)
    collect_legacy.add_argument("--split", required=True)
    collect_legacy.add_argument("--manifest", type=Path, required=True)
    collect_legacy.add_argument("--output", type=Path, required=True)
    replay = subparsers.add_parser("replay")
    replay.add_argument("--protocol", type=Path, required=True)
    replay.add_argument("--seed", type=int, required=True)
    replay.add_argument("--deep-calibration", type=Path, required=True)
    replay.add_argument("--deep-validation", type=Path, required=True)
    replay.add_argument("--legacy-validation", type=Path, required=True)
    replay.add_argument("--run-output", type=Path, required=True)
    replay.add_argument("--public-output", type=Path, required=True)
    decide = subparsers.add_parser("decide")
    decide.add_argument("--protocol", type=Path, required=True)
    decide.add_argument("--report", type=Path, action="append", default=[])
    decide.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "collect-deep":
        result = collect_plan_d_deep_predictions(
            protocol_path=args.protocol,
            split=args.split,
            manifest_path=args.manifest,
            checkpoint_path=args.checkpoint,
            seed=args.seed,
            output_path=args.output,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    elif args.command == "collect-legacy":
        result = collect_plan_d_legacy_predictions(
            protocol_path=args.protocol,
            split=args.split,
            manifest_path=args.manifest,
            output_path=args.output,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    elif args.command == "replay":
        result = replay_plan_d_seed(
            protocol_path=args.protocol,
            seed=args.seed,
            deep_calibration_path=args.deep_calibration,
            deep_validation_path=args.deep_validation,
            legacy_validation_path=args.legacy_validation,
            run_output_path=args.run_output,
            public_output_path=args.public_output,
        )
        print(
            json.dumps(
                {
                    "experiment_sha256": result["experiment_sha256"],
                    "seed": result["seed"],
                    "status": result["status"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    elif args.command == "decide":
        result = decide_plan_d_replay_from_files(
            protocol_path=args.protocol,
            report_paths=args.report,
            output_path=args.output,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
