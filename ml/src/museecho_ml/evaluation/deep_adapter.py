from __future__ import annotations

import json
import math
import time
import wave
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from numpy.typing import NDArray

from museecho_ml.artifacts import canonical_sha256, file_sha256
from museecho_ml.data.vocabulary_freeze import map_to_frozen_vocabulary
from museecho_ml.evaluation.metrics import ScoredChordInterval
from museecho_ml.evaluation.promotion import FrozenTestSession
from museecho_ml.evaluation.report import EvaluationConfig
from museecho_ml.evaluation.statistics import evaluate_dataset_strata
from museecho_ml.features.cqt import extract_features
from museecho_ml.labels import CanonicalChord
from museecho_ml.model.crnn import ChordCrnn, CrnnConfig
from museecho_ml.postprocess.calibration import (
    CalibrationParameters,
    fit_temperature,
    select_publication_threshold,
)
from museecho_ml.postprocess.decode import decode_logits
from museecho_ml.training.train import _config_base, _resolve_relative, load_train_config
from museecho_ml.vocabulary import ChordVocabulary

_REFERENCE_TIME_TOLERANCE_SECONDS = 1e-9


@dataclass(frozen=True)
class RawTrackPrediction:
    track_id: str
    dataset_id: str
    cover_group_id: str
    split: str
    duration_seconds: float
    frame_times: NDArray[np.float64]
    valid_mask: NDArray[np.bool_]
    root_logits: NDArray[np.float64]
    quality_logits: NDArray[np.float64]
    bass_logits: NDArray[np.float64]
    boundary_logits: NDArray[np.float64]
    reference: tuple[ScoredChordInterval, ...]
    inference_wall_seconds: float

    def __post_init__(self) -> None:
        if (
            not self.track_id
            or not self.dataset_id
            or not self.cover_group_id
            or self.split not in {"calibration", "validation", "test"}
            or not math.isfinite(self.duration_seconds)
            or self.duration_seconds <= 0
            or not math.isfinite(self.inference_wall_seconds)
            or self.inference_wall_seconds < 0
            or not self.reference
        ):
            raise ValueError("raw deep prediction metadata is invalid")


@dataclass(frozen=True)
class DeepCalibrationResult:
    status: str
    parameters: CalibrationParameters
    precision: float
    coverage: float

    def to_dict(self) -> dict[str, Any]:
        parameter_payload = self.parameters.to_dict()
        body = {
            "schema_version": 1,
            "fit_version": "plan-c-calibration-fit-v1",
            "status": self.status,
            "precision": self.precision,
            "coverage": self.coverage,
            "parameters": parameter_payload,
        }
        return {**body, "calibration_fit_sha256": canonical_sha256(body)}


def load_deep_evaluation_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("deep evaluation manifest is unreadable") from error
    if not isinstance(manifest, dict):
        raise ValueError("deep evaluation manifest must be an object")
    if manifest.get("split") not in {"calibration", "validation"}:
        raise PermissionError("deep evaluation may read calibration or validation only")
    if manifest.get("corpus_role") != "real-gold":
        raise ValueError("deep evaluation manifest must contain real-gold")
    if not isinstance(manifest.get("tracks"), list) or not manifest["tracks"]:
        raise ValueError("deep evaluation manifest must contain tracks")
    return manifest


def manifest_reference_intervals(
    track: Mapping[str, Any], vocabulary: ChordVocabulary
) -> tuple[ScoredChordInterval, ...]:
    if not isinstance(track, Mapping):
        raise ValueError("deep evaluation track must be an object")
    duration = track.get("duration_seconds")
    intervals = track.get("intervals")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration <= 0
        or not isinstance(intervals, list)
        or not intervals
    ):
        raise ValueError("deep evaluation reference is invalid")
    result: list[ScoredChordInterval] = []
    cursor = 0.0
    for raw in intervals:
        if not isinstance(raw, Mapping):
            raise ValueError("deep evaluation reference interval must be an object")
        start = raw.get("start_seconds")
        end = raw.get("end_seconds")
        labels = tuple(raw.get(field) for field in ("root", "quality", "bass"))
        if (
            any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in (start, end)
            )
            or float(start) < cursor
            or float(start) >= float(end)
            or float(end) > float(duration) + 1e-6
            or any(not isinstance(value, str) or not value for value in labels)
        ):
            raise ValueError("deep evaluation reference interval is invalid")
        start_value = float(start)
        end_value = min(float(end), float(duration))
        if start_value > cursor:
            _append_interval(
                result,
                cursor,
                start_value,
                CanonicalChord("N", "N", "N"),
            )
        chord = map_to_frozen_vocabulary(
            CanonicalChord(
                str(labels[0]),
                str(labels[1]),
                str(labels[2]),
                (
                    str(raw["mapping_reason"])
                    if raw.get("mapping_reason") is not None
                    else None
                ),
            ),
            vocabulary,
        )
        _append_interval(result, start_value, end_value, chord)
        cursor = end_value
    remaining = float(duration) - cursor
    if remaining > _REFERENCE_TIME_TOLERANCE_SECONDS:
        _append_interval(
            result,
            cursor,
            float(duration),
            CanonicalChord("N", "N", "N"),
        )
    elif remaining > 0:
        previous = result.pop()
        result.append(
            ScoredChordInterval(
                previous.start_seconds,
                float(duration),
                previous.chord,
                previous.confidence,
            )
        )
    if not result or result[0].start_seconds != 0 or result[-1].end_seconds != duration:
        raise ValueError("deep evaluation reference does not cover the track")
    return tuple(result)


def collect_checkpoint_predictions(
    *,
    checkpoint_path: Path,
    manifest_path: Path,
    config_path: Path,
    vocabulary_path: Path,
    expected_manifest_sha256: str,
    expected_checkpoint_sha256: str | None = None,
) -> tuple[RawTrackPrediction, ...]:
    manifest = load_deep_evaluation_manifest(manifest_path)
    return _collect_checkpoint_predictions_from_manifest(
        manifest=manifest,
        checkpoint_path=checkpoint_path,
        config_path=config_path,
        vocabulary_path=vocabulary_path,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_checkpoint_sha256=expected_checkpoint_sha256,
    )


def collect_authorized_test_predictions(
    *,
    session: FrozenTestSession,
    checkpoint_path: Path,
    config_path: Path,
    vocabulary_path: Path,
) -> tuple[tuple[RawTrackPrediction, ...], dict[str, Any]]:
    def collect(
        manifest: Mapping[str, Any],
    ) -> tuple[tuple[RawTrackPrediction, ...], dict[str, Any]]:
        if manifest.get("split") != "test":
            raise PermissionError("authorized deep evaluation requires the test split")
        if manifest.get("corpus_role") != "real-gold":
            raise ValueError("authorized deep evaluation must contain real-gold")
        predictions = _collect_checkpoint_predictions_from_manifest(
            manifest=manifest,
            checkpoint_path=checkpoint_path,
            config_path=config_path,
            vocabulary_path=vocabulary_path,
            expected_manifest_sha256=session.receipt.get("test_manifest_sha256"),
            expected_checkpoint_sha256=session.receipt.get("checkpoint_sha256"),
        )
        return predictions, dict(manifest)

    return session.evaluate_once(collect)


def _collect_checkpoint_predictions_from_manifest(
    *,
    manifest: Mapping[str, Any],
    checkpoint_path: Path,
    config_path: Path,
    vocabulary_path: Path,
    expected_manifest_sha256: str,
    expected_checkpoint_sha256: str | None,
) -> tuple[RawTrackPrediction, ...]:
    if canonical_sha256(manifest) != expected_manifest_sha256:
        raise ValueError("deep evaluation manifest SHA-256 does not match")
    try:
        vocabulary_payload = json.loads(
            vocabulary_path.resolve(strict=True).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("deep evaluation vocabulary is unreadable") from error
    vocabulary = ChordVocabulary.from_dict(vocabulary_payload)
    config_source = config_path.resolve(strict=True)
    config = load_train_config(config_source)
    base = _config_base(config_source)
    checkpoint_source = checkpoint_path.resolve(strict=True)
    if (
        expected_checkpoint_sha256 is not None
        and file_sha256(checkpoint_source) != expected_checkpoint_sha256
    ):
        raise ValueError("deep evaluation checkpoint SHA-256 does not match")
    try:
        checkpoint = torch.load(
            checkpoint_source, map_location="cpu", weights_only=False
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise ValueError("deep evaluation checkpoint is unreadable") from error
    if (
        not isinstance(checkpoint, dict)
        or checkpoint.get("schema_version") != 2
        or checkpoint.get("checkpoint_version") != "checkpoint-v2"
        or not isinstance(checkpoint.get("model_config"), dict)
        or not isinstance(checkpoint.get("model_state"), dict)
    ):
        raise ValueError("deep evaluation checkpoint schema is invalid")
    checkpoint_model_config = CrnnConfig(**checkpoint["model_config"])
    if checkpoint_model_config != config.model_config:
        raise ValueError("deep evaluation checkpoint model config does not match")
    if (
        checkpoint_model_config.root_classes != len(vocabulary.root_labels)
        or checkpoint_model_config.quality_classes != len(vocabulary.quality_labels)
        or checkpoint_model_config.bass_classes != len(vocabulary.bass_labels)
    ):
        raise ValueError("deep evaluation checkpoint vocabulary dimensions do not match")
    if manifest["split"] == "validation" and checkpoint.get("identity", {}).get(
        "validation_manifest_sha256"
    ) != expected_manifest_sha256:
        raise ValueError("deep evaluation checkpoint validation identity does not match")
    model = ChordCrnn(checkpoint_model_config)
    model.load_state_dict(checkpoint["model_state"], strict=True)
    model.eval()
    roots = {
        dataset_id: _resolve_relative(base, root, must_exist=True)
        for dataset_id, root in config.dataset_roots.items()
    }
    predictions: list[RawTrackPrediction] = []
    for raw_track in manifest["tracks"]:
        if not isinstance(raw_track, Mapping):
            raise ValueError("deep evaluation track must be an object")
        track_id = raw_track.get("track_id")
        dataset_id = raw_track.get("dataset_id")
        cover_group_id = raw_track.get("cover_group_id")
        audio_relative = raw_track.get("audio_path")
        if any(
            not isinstance(value, str) or not value
            for value in (track_id, dataset_id, cover_group_id, audio_relative)
        ):
            raise ValueError("deep evaluation track identity is invalid")
        dataset_root = roots.get(str(dataset_id))
        if dataset_root is None:
            raise ValueError("deep evaluation dataset root is missing")
        audio_path = (dataset_root / str(audio_relative)).resolve(strict=True)
        if not audio_path.is_relative_to(dataset_root) or not audio_path.is_file():
            raise ValueError("deep evaluation audio path escapes its dataset root")
        started = time.perf_counter()
        audio, sample_rate = _read_wav(audio_path)
        features = extract_features(
            audio, sample_rate=sample_rate, config=config.feature_config
        )
        main = torch.from_numpy(features.main_cqt)[None, None, :, :]
        bass = torch.from_numpy(features.bass_cqt)[None, None, :, :]
        mask = torch.from_numpy(features.valid_mask)[None, :]
        with torch.inference_mode():
            outputs = model(main, bass, mask)
        wall_seconds = time.perf_counter() - started
        duration = raw_track.get("duration_seconds")
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or duration <= 0
        ):
            raise ValueError("deep evaluation track duration is invalid")
        reference = manifest_reference_intervals(raw_track, vocabulary)
        predictions.append(
            RawTrackPrediction(
                track_id=str(track_id),
                dataset_id=str(dataset_id),
                cover_group_id=str(cover_group_id),
                split=manifest["split"],
                duration_seconds=float(duration),
                frame_times=np.asarray(features.frame_times, dtype=np.float64),
                valid_mask=np.asarray(features.valid_mask, dtype=np.bool_),
                root_logits=np.asarray(outputs.root[0].cpu(), dtype=np.float64),
                quality_logits=np.asarray(outputs.quality[0].cpu(), dtype=np.float64),
                bass_logits=np.asarray(outputs.bass[0].cpu(), dtype=np.float64),
                boundary_logits=np.asarray(outputs.boundary[0].cpu(), dtype=np.float64),
                reference=reference,
                inference_wall_seconds=wall_seconds,
            )
        )
    return tuple(predictions)


def fit_deep_calibration(
    predictions: Sequence[RawTrackPrediction],
    vocabulary: ChordVocabulary,
    *,
    minimum_precision: float = 0.85,
    minimum_coverage: float = 0.65,
) -> DeepCalibrationResult:
    tracks = _validated_raw_predictions(predictions, expected_split="calibration")
    root_logits: list[NDArray[np.float64]] = []
    quality_logits: list[NDArray[np.float64]] = []
    bass_logits: list[NDArray[np.float64]] = []
    root_targets: list[NDArray[np.int64]] = []
    quality_targets: list[NDArray[np.int64]] = []
    bass_targets: list[NDArray[np.int64]] = []
    durations: list[NDArray[np.float64]] = []
    for track in tracks:
        count = int(track.valid_mask.sum())
        targets = _frame_targets(track.frame_times[:count], track.reference, vocabulary)
        root_logits.append(np.asarray(track.root_logits[:count], dtype=np.float64))
        quality_logits.append(np.asarray(track.quality_logits[:count], dtype=np.float64))
        bass_logits.append(np.asarray(track.bass_logits[:count], dtype=np.float64))
        root_targets.append(targets[0])
        quality_targets.append(targets[1])
        bass_targets.append(targets[2])
        durations.append(
            _frame_durations(track.frame_times[:count], track.duration_seconds)
        )
    roots = np.concatenate(root_logits)
    qualities = np.concatenate(quality_logits)
    basses = np.concatenate(bass_logits)
    target_roots = np.concatenate(root_targets)
    target_qualities = np.concatenate(quality_targets)
    target_basses = np.concatenate(bass_targets)
    frame_durations = np.concatenate(durations)
    root_temperature = fit_temperature(roots, target_roots)
    quality_temperature = fit_temperature(qualities, target_qualities)
    bass_temperature = fit_temperature(basses, target_basses)
    root_probabilities = _softmax(roots / root_temperature)
    quality_probabilities = _softmax(qualities / quality_temperature)
    bass_probabilities = _softmax(basses / bass_temperature)
    predicted_roots = np.argmax(root_probabilities, axis=1)
    predicted_qualities = np.argmax(quality_probabilities, axis=1)
    predicted_basses = np.argmax(bass_probabilities, axis=1)
    confidences = np.minimum.reduce(
        (
            root_probabilities[np.arange(len(roots)), predicted_roots],
            quality_probabilities[np.arange(len(roots)), predicted_qualities],
            bass_probabilities[np.arange(len(roots)), predicted_basses],
        )
    )
    eligible = np.asarray(
        [
            vocabulary.root_labels[root] not in {"N", "X"}
            and vocabulary.quality_labels[quality] not in {"N", "X"}
            and vocabulary.bass_labels[bass] not in {"N", "X"}
            for root, quality, bass in zip(
                predicted_roots, predicted_qualities, predicted_basses, strict=True
            )
        ],
        dtype=np.bool_,
    )
    correct = (predicted_roots == target_roots) & (
        predicted_qualities == target_qualities
    )
    try:
        threshold = select_publication_threshold(
            confidences=confidences,
            correct=correct,
            durations=frame_durations,
            eligible=eligible,
            minimum_precision=minimum_precision,
            minimum_coverage=minimum_coverage,
        )
    except ValueError:
        threshold = _best_effort_threshold(
            confidences, correct, frame_durations, eligible
        )
    precision, coverage = _precision_coverage_at_threshold(
        confidences, correct, frame_durations, eligible, threshold
    )
    parameters = CalibrationParameters(
        root_temperature=root_temperature,
        quality_temperature=quality_temperature,
        bass_temperature=bass_temperature,
        publication_threshold=threshold,
        boundary_threshold=0.5,
        minimum_event_seconds=0.1,
    )
    return DeepCalibrationResult(
        status=(
            "passed"
            if precision >= minimum_precision and coverage >= minimum_coverage
            else "not-met"
        ),
        parameters=parameters,
        precision=precision,
        coverage=coverage,
    )


def evaluate_deep_predictions(
    predictions: Sequence[RawTrackPrediction],
    vocabulary: ChordVocabulary,
    calibration: CalibrationParameters,
) -> dict[str, Any]:
    return _evaluate_predictions(
        predictions,
        vocabulary,
        calibration,
        expected_split="validation",
    )


def evaluate_authorized_test_predictions(
    predictions: Sequence[RawTrackPrediction],
    vocabulary: ChordVocabulary,
    calibration: CalibrationParameters,
) -> dict[str, Any]:
    return _evaluate_predictions(
        predictions,
        vocabulary,
        calibration,
        expected_split="test",
    )


def _evaluate_predictions(
    predictions: Sequence[RawTrackPrediction],
    vocabulary: ChordVocabulary,
    calibration: CalibrationParameters,
    *,
    expected_split: str,
) -> dict[str, Any]:
    raw = _validated_raw_predictions(predictions, expected_split=expected_split)
    tracks: dict[
        str,
        tuple[tuple[ScoredChordInterval, ...], tuple[ScoredChordInterval, ...]],
    ] = {}
    metadata: dict[str, dict[str, str]] = {}
    total_wall = 0.0
    total_duration = 0.0
    for track in raw:
        prediction = decode_logits(
            track.root_logits,
            track.quality_logits,
            track.bass_logits,
            track.boundary_logits,
            track.frame_times,
            track.valid_mask,
            duration_seconds=track.duration_seconds,
            vocabulary=vocabulary,
            calibration=calibration,
        )
        tracks[track.track_id] = (track.reference, prediction)
        metadata[track.track_id] = {
            "dataset_id": track.dataset_id,
            "cover_group_id": track.cover_group_id,
            "split": track.split,
        }
        total_wall += track.inference_wall_seconds
        total_duration += track.duration_seconds
    config = EvaluationConfig(publication_threshold=calibration.publication_threshold)
    report = evaluate_dataset_strata(tracks, metadata, config)
    aggregate = report["aggregate"]
    quality = aggregate["quality"]["per_quality"]
    public_f1 = [
        float(quality[label]["f1"])
        for label in config.public_quality_labels
        if label in quality
    ]
    selection_metrics = {
        "exact_vocabulary_wcsr": float(
            aggregate["weighted_scores"]["exact_quality"]
        ),
        "public_quality_macro_f1": (
            sum(public_f1) / len(public_f1) if public_f1 else 0.0
        ),
        "published_known_precision": float(aggregate["published"]["precision"]),
        "coverage": float(aggregate["published"]["coverage"]),
        "five_minute_cpu_wall_seconds": total_wall / total_duration * 300.0,
    }
    return {**report, "selection_metrics": selection_metrics}


def _validated_raw_predictions(
    predictions: Sequence[RawTrackPrediction], *, expected_split: str
) -> tuple[RawTrackPrediction, ...]:
    if (
        not isinstance(predictions, Sequence)
        or isinstance(predictions, (str, bytes))
        or not predictions
        or any(not isinstance(item, RawTrackPrediction) for item in predictions)
        or any(item.split != expected_split for item in predictions)
    ):
        raise ValueError(f"deep predictions must contain only {expected_split}")
    track_ids = [item.track_id for item in predictions]
    if len(set(track_ids)) != len(track_ids):
        raise ValueError("deep predictions contain duplicate track IDs")
    return tuple(predictions)


def _frame_targets(
    times: NDArray[np.float64],
    reference: Sequence[ScoredChordInterval],
    vocabulary: ChordVocabulary,
) -> tuple[NDArray[np.int64], NDArray[np.int64], NDArray[np.int64]]:
    root = np.empty(len(times), dtype=np.int64)
    quality = np.empty(len(times), dtype=np.int64)
    bass = np.empty(len(times), dtype=np.int64)
    interval_index = 0
    for frame_index, frame_time in enumerate(times):
        while frame_time >= reference[interval_index].end_seconds:
            interval_index += 1
        encoded = vocabulary.encode(reference[interval_index].chord)
        root[frame_index] = encoded.root
        quality[frame_index] = encoded.quality
        bass[frame_index] = encoded.bass
    return root, quality, bass


def _frame_durations(
    times: NDArray[np.float64], duration_seconds: float
) -> NDArray[np.float64]:
    ends = np.concatenate((times[1:], np.asarray([duration_seconds])))
    result = ends - times
    if np.any(result <= 0) or not np.isfinite(result).all():
        raise ValueError("deep prediction frame durations are invalid")
    return result


def _softmax(logits: NDArray[np.float64]) -> NDArray[np.float64]:
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    exponentials = np.exp(shifted)
    return exponentials / exponentials.sum(axis=1, keepdims=True)


def _precision_coverage_at_threshold(
    confidences: NDArray[np.float64],
    correct: NDArray[np.bool_],
    durations: NDArray[np.float64],
    eligible: NDArray[np.bool_],
    threshold: float,
) -> tuple[float, float]:
    selected = eligible & (confidences >= threshold)
    selected_duration = float(durations[selected].sum())
    precision = (
        float(durations[selected & correct].sum()) / selected_duration
        if selected_duration
        else 0.0
    )
    coverage = selected_duration / float(durations.sum())
    return precision, coverage


def _best_effort_threshold(
    confidences: NDArray[np.float64],
    correct: NDArray[np.bool_],
    durations: NDArray[np.float64],
    eligible: NDArray[np.bool_],
) -> float:
    if not eligible.any():
        return 1.0
    candidates = [float(value) for value in np.unique(confidences[eligible])]
    return max(
        candidates,
        key=lambda threshold: (
            min(
                _precision_coverage_at_threshold(
                    confidences, correct, durations, eligible, threshold
                )[0]
                / 0.85,
                _precision_coverage_at_threshold(
                    confidences, correct, durations, eligible, threshold
                )[1]
                / 0.65,
            ),
            *_precision_coverage_at_threshold(
                confidences, correct, durations, eligible, threshold
            ),
            threshold,
        ),
    )


def _append_interval(
    result: list[ScoredChordInterval],
    start: float,
    end: float,
    chord: CanonicalChord,
) -> None:
    if result and result[-1].chord == chord:
        previous = result.pop()
        result.append(
            ScoredChordInterval(previous.start_seconds, end, chord, 1.0)
        )
    else:
        result.append(ScoredChordInterval(start, end, chord, 1.0))


def _read_wav(path: Path) -> tuple[NDArray[np.int16], int]:
    try:
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            if channels <= 0 or sample_width != 2 or sample_rate <= 0:
                raise ValueError("deep evaluation requires 16-bit PCM WAV audio")
            samples = np.frombuffer(
                source.readframes(source.getnframes()), dtype="<i2"
            )
    except (EOFError, wave.Error) as error:
        raise ValueError(f"deep evaluation WAV is unreadable: {path.name}") from error
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)
    if not len(samples):
        raise ValueError("deep evaluation WAV is empty")
    return np.ascontiguousarray(samples), sample_rate
