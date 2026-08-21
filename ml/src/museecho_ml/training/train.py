from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch

from museecho_ml.data.manifest import ChordInterval
from museecho_ml.data.split_freeze import load_training_manifest
from museecho_ml.data.vocabulary_freeze import map_to_frozen_vocabulary
from museecho_ml.features.cqt import CqtConfig, extract_features
from museecho_ml.labels import CanonicalChord
from museecho_ml.model.batch import ModelBatch, TrainingExample, collate_examples
from museecho_ml.model.crnn import CrnnConfig
from museecho_ml.model.loss import LossConfig, compute_class_weights, multitask_loss
from museecho_ml.training.checkpoint import (
    CheckpointIdentity,
    TrainingState,
    load_checkpoint,
    load_model_initialization,
    save_checkpoint,
)
from museecho_ml.training.early_stop import EarlyStopConfig, EarlyStopper
from museecho_ml.training.seed import (
    collect_device_metadata,
    configure_reproducibility,
    resolve_device,
)
from museecho_ml.training.trainer import TrainerConfig, build_optimizer, train_step
from museecho_ml.vocabulary import ChordVocabulary


@dataclass(frozen=True)
class SchedulerConfig:
    factor: float = 0.5
    patience: int = 2
    minimum_learning_rate: float = 1e-6

    def __post_init__(self) -> None:
        if (
            isinstance(self.factor, bool)
            or not isinstance(self.factor, (int, float))
            or not math.isfinite(self.factor)
            or not 0 < self.factor < 1
        ):
            raise ValueError("scheduler factor must be finite and within (0, 1)")
        if type(self.patience) is not int or self.patience < 0:
            raise ValueError("scheduler patience must be a non-negative integer")
        if (
            isinstance(self.minimum_learning_rate, bool)
            or not isinstance(self.minimum_learning_rate, (int, float))
            or not math.isfinite(self.minimum_learning_rate)
            or self.minimum_learning_rate < 0
        ):
            raise ValueError("scheduler minimum learning rate must be finite and non-negative")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SchedulerConfig:
        required = {"factor", "patience", "minimum_learning_rate"}
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("scheduler config fields are invalid")
        return cls(**value)


@dataclass(frozen=True)
class OverfitGateConfig:
    maximum_loss_ratio: float
    minimum_root_accuracy: float
    minimum_quality_accuracy: float

    def __post_init__(self) -> None:
        values = (
            self.maximum_loss_ratio,
            self.minimum_root_accuracy,
            self.minimum_quality_accuracy,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in values
        ):
            raise ValueError("overfit gate values must be finite numbers")
        if self.maximum_loss_ratio <= 0 or not (
            0 <= self.minimum_root_accuracy <= 1
            and 0 <= self.minimum_quality_accuracy <= 1
        ):
            raise ValueError("overfit gate thresholds are invalid")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> OverfitGateConfig:
        required = {
            "maximum_loss_ratio",
            "minimum_root_accuracy",
            "minimum_quality_accuracy",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("overfit gate config fields are invalid")
        return cls(**value)


@dataclass(frozen=True)
class TrainConfig:
    purpose: str
    seed: int
    device: str
    precision_mode: str
    max_epochs: int
    steps_per_epoch: int
    train_manifest: str
    validation_manifest: str
    dataset_roots: dict[str, str]
    output_root: str
    track_limit: int | None
    segment_seconds: float
    segment_start_policy: str
    feature_config: CqtConfig
    model_config: CrnnConfig
    loss_config: LossConfig
    trainer_config: TrainerConfig
    scheduler_config: SchedulerConfig
    early_stop_config: EarlyStopConfig
    overfit_gate: OverfitGateConfig | None

    def __post_init__(self) -> None:
        if self.purpose not in {"g3-overfit", "r0-smoke", "formal"}:
            raise ValueError("training purpose is unsupported")
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError("training seed must be a non-negative integer")
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("training device is unsupported")
        if self.precision_mode != "float32":
            raise ValueError("train-v1 supports float32 precision only")
        if any(
            type(value) is not int or value <= 0
            for value in (self.max_epochs, self.steps_per_epoch)
        ):
            raise ValueError("training epoch and step counts must be positive integers")
        if self.track_limit is not None and (
            type(self.track_limit) is not int or self.track_limit <= 0
        ):
            raise ValueError("training track limit must be null or a positive integer")
        if (
            isinstance(self.segment_seconds, bool)
            or not isinstance(self.segment_seconds, (int, float))
            or not math.isfinite(self.segment_seconds)
            or self.segment_seconds <= 0
        ):
            raise ValueError("training segment seconds must be finite and positive")
        if self.segment_start_policy not in {"start", "first-supervised"}:
            raise ValueError("training segment start policy is unsupported")
        paths = (self.train_manifest, self.validation_manifest, self.output_root)
        if any(not isinstance(value, str) or not value.strip() for value in paths):
            raise ValueError("training paths must be non-empty strings")
        if not isinstance(self.dataset_roots, dict) or not self.dataset_roots or any(
            not isinstance(dataset_id, str)
            or not dataset_id.strip()
            or not isinstance(root, str)
            or not root.strip()
            for dataset_id, root in self.dataset_roots.items()
        ):
            raise ValueError("training dataset roots must map dataset IDs to paths")
        if self.purpose == "g3-overfit" and self.overfit_gate is None:
            raise ValueError("G3 overfit training requires an overfit gate")
        if self.purpose != "g3-overfit" and self.overfit_gate is not None:
            raise ValueError("only G3 overfit training may define an overfit gate")

    @classmethod
    def smoke_defaults(cls) -> TrainConfig:
        return cls(
            purpose="g3-overfit",
            seed=20260820,
            device="cpu",
            precision_mode="float32",
            max_epochs=80,
            steps_per_epoch=1,
            train_manifest="data/manifests/splits-v1/real-gold-train.manifest.json",
            validation_manifest="data/manifests/splits-v1/real-gold-train.manifest.json",
            dataset_roots={"guitarset": "data/sources"},
            output_root="runs/train-smoke",
            track_limit=2,
            segment_seconds=4.0,
            segment_start_policy="first-supervised",
            feature_config=CqtConfig(),
            model_config=CrnnConfig(
                main_conv_channels=(4,),
                bass_conv_channels=(4,),
                gru_hidden_size=12,
                gru_layers=1,
                dropout=0.0,
            ),
            loss_config=LossConfig(),
            trainer_config=TrainerConfig(learning_rate=0.01, weight_decay=0.0),
            scheduler_config=SchedulerConfig(),
            early_stop_config=EarlyStopConfig(patience=10),
            overfit_gate=OverfitGateConfig(0.05, 0.95, 0.95),
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TrainConfig:
        required = {
            "schema_version",
            "train_version",
            "purpose",
            "seed",
            "device",
            "precision_mode",
            "max_epochs",
            "steps_per_epoch",
            "train_manifest",
            "validation_manifest",
            "dataset_roots",
            "output_root",
            "track_limit",
            "segment_seconds",
            "segment_start_policy",
            "features",
            "model",
            "loss",
            "trainer",
            "scheduler",
            "early_stop",
            "overfit_gate",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("train config fields are invalid")
        if value["schema_version"] != 1 or value["train_version"] != "train-v1":
            raise ValueError("train config version is unsupported")
        gate = value["overfit_gate"]
        return cls(
            purpose=value["purpose"],
            seed=value["seed"],
            device=value["device"],
            precision_mode=value["precision_mode"],
            max_epochs=value["max_epochs"],
            steps_per_epoch=value["steps_per_epoch"],
            train_manifest=value["train_manifest"],
            validation_manifest=value["validation_manifest"],
            dataset_roots=value["dataset_roots"],
            output_root=value["output_root"],
            track_limit=value["track_limit"],
            segment_seconds=value["segment_seconds"],
            segment_start_policy=value["segment_start_policy"],
            feature_config=CqtConfig.from_dict(value["features"]),
            model_config=CrnnConfig.from_dict(value["model"]),
            loss_config=LossConfig.from_dict(value["loss"]),
            trainer_config=TrainerConfig.from_dict(value["trainer"]),
            scheduler_config=SchedulerConfig.from_dict(value["scheduler"]),
            early_stop_config=EarlyStopConfig(**value["early_stop"]),
            overfit_gate=None if gate is None else OverfitGateConfig.from_dict(gate),
        )


def load_train_config(path: Path) -> TrainConfig:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("training config is unreadable") from error
    return TrainConfig.from_dict(payload)


def run_training_batches(
    config: TrainConfig,
    train_batch: Any,
    validation_batch: Any,
    identity: CheckpointIdentity,
    run_dir: Path,
    *,
    vocabulary: ChordVocabulary | None = None,
    initialization_checkpoint: tuple[Path, str] | None = None,
    resume_path: Path | None = None,
    epoch_limit: int | None = None,
) -> dict[str, Any]:
    streaming_batches = callable(train_batch)
    if (not isinstance(train_batch, ModelBatch) and not streaming_batches) or not (
        isinstance(validation_batch, ModelBatch)
    ):
        raise ValueError(
            "training batches must use ModelBatch or a deterministic batch provider"
        )
    if epoch_limit is not None and (type(epoch_limit) is not int or epoch_limit <= 0):
        raise ValueError("training epoch limit must be null or a positive integer")
    frozen_vocabulary = vocabulary or ChordVocabulary.default()
    if config.model_config.root_classes != len(frozen_vocabulary.root_labels):
        raise ValueError("model root classes do not match frozen vocabulary")
    if config.model_config.quality_classes != len(frozen_vocabulary.quality_labels):
        raise ValueError("model quality classes do not match frozen vocabulary")
    if config.model_config.bass_classes != len(frozen_vocabulary.bass_labels):
        raise ValueError("model bass classes do not match frozen vocabulary")
    if initialization_checkpoint is not None and resume_path is not None:
        raise ValueError("model initialization and exact resume are mutually exclusive")
    device = resolve_device(config.device)
    configure_reproducibility(config.seed, device)
    output = run_dir.resolve(strict=False)
    output.mkdir(parents=True, exist_ok=True)
    best_path = output / "checkpoint-best.pt"
    last_path = output / "checkpoint-last.pt"
    model = _build_model(config)
    if initialization_checkpoint is not None:
        initialization_path, initialization_sha256 = initialization_checkpoint
        load_model_initialization(
            initialization_path,
            model,
            expected_checkpoint_sha256=initialization_sha256,
        )
    optimizer = build_optimizer(model, config.trainer_config)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        mode=config.early_stop_config.mode,
        factor=float(config.scheduler_config.factor),
        patience=config.scheduler_config.patience,
        min_lr=float(config.scheduler_config.minimum_learning_rate),
    )
    early_stopper = EarlyStopper(config.early_stop_config)
    data_generator = torch.Generator().manual_seed(config.seed)
    state = TrainingState(epoch=0, step_in_epoch=0, global_step=0)
    if resume_path is not None:
        state = load_checkpoint(
            resume_path,
            model,
            optimizer,
            scheduler,
            early_stopper,
            identity=identity,
            trainer_config=config.trainer_config,
            loss_config=config.loss_config,
            data_generator=data_generator,
        )
    resumed_from_epoch = state.epoch if resume_path is not None else None
    audit_train_batch = _training_batch_at(train_batch, epoch=0, step=0)
    class_weights = compute_class_weights(
        [audit_train_batch.targets],
        root_classes=config.model_config.root_classes,
        quality_classes=config.model_config.quality_classes,
        bass_classes=config.model_config.bass_classes,
    )
    initial_train = _evaluate(model, audit_train_batch, config.loss_config, device)
    curve: list[dict[str, Any]] = []
    global_step = state.global_step
    stop_reason = "max_epochs"
    end_epoch = config.max_epochs
    if epoch_limit is not None:
        end_epoch = min(config.max_epochs, state.epoch + epoch_limit)
        if end_epoch < config.max_epochs:
            stop_reason = "operational_limit"
    for epoch in range(state.epoch, end_epoch):
        train_metrics: dict[str, float] | None = None
        for step in range(config.steps_per_epoch):
            current_train_batch = _training_batch_at(
                train_batch, epoch=epoch, step=step
            )
            train_metrics = train_step(
                model,
                current_train_batch,
                optimizer,
                loss_config=config.loss_config,
                trainer_config=config.trainer_config,
                device=device,
                class_weights=class_weights,
            )
            global_step += 1
        assert train_metrics is not None
        validation = _evaluate(model, validation_batch, config.loss_config, device)
        selection_metric = validation["root_quality_accuracy"]
        scheduler.step(selection_metric)
        improved = early_stopper.update(selection_metric, epoch=epoch)
        next_state = TrainingState(
            epoch=epoch + 1,
            step_in_epoch=0,
            global_step=global_step,
        )
        curve.append(
            {
                "epoch": epoch,
                "global_step": global_step,
                "learning_rate": float(optimizer.param_groups[0]["lr"]),
                "train_total_loss": train_metrics["total"],
                "validation_total_loss": validation["total_loss"],
                "validation_root_accuracy": validation["root_accuracy"],
                "validation_quality_accuracy": validation["quality_accuracy"],
                "validation_root_quality_accuracy": selection_metric,
            }
        )
        save_checkpoint(
            last_path,
            model,
            optimizer,
            scheduler,
            early_stopper,
            next_state,
            identity=identity,
            trainer_config=config.trainer_config,
            loss_config=config.loss_config,
            data_generator=data_generator,
        )
        if improved:
            save_checkpoint(
                best_path,
                model,
                optimizer,
                scheduler,
                early_stopper,
                next_state,
                identity=identity,
                trainer_config=config.trainer_config,
                loss_config=config.loss_config,
                data_generator=data_generator,
            )
        if early_stopper.should_stop:
            stop_reason = "early_stop"
            break
    if not best_path.is_file():
        raise RuntimeError("training produced no validation-selected checkpoint")
    load_checkpoint(
        best_path,
        model,
        optimizer,
        scheduler,
        early_stopper,
        identity=identity,
        trainer_config=config.trainer_config,
        loss_config=config.loss_config,
        data_generator=data_generator,
    )
    best_metrics = _evaluate(model, validation_batch, config.loss_config, device)
    final_train = _evaluate(model, audit_train_batch, config.loss_config, device)
    loss_ratio = final_train["total_loss"] / initial_train["total_loss"]
    gate_report = _overfit_gate_report(config.overfit_gate, final_train, loss_ratio)
    artifacts = {
        "checkpoint-best.pt": _file_sha256(best_path),
        "checkpoint-last.pt": _file_sha256(last_path),
    }
    artifact_index = {
        "schema_version": 1,
        "checkpoint_identity": asdict(identity),
        "artifacts": artifacts,
    }
    (output / "artifact-index.json").write_text(
        json.dumps(artifact_index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report = {
        "schema_version": 1,
        "purpose": config.purpose,
        "seed": config.seed,
        "selection_metric": "validation_root_quality_accuracy",
        "training_batch_mode": (
            "deterministic-stream" if streaming_batches else "fixed"
        ),
        "checkpoint_identity": asdict(identity),
        "device": collect_device_metadata(device, precision_mode=config.precision_mode),
        "curve": curve,
        "resumed_from_epoch": resumed_from_epoch,
        "best_epoch": early_stopper.best_epoch,
        "best_validation": best_metrics,
        "stop_reason": stop_reason,
        "initial_train": initial_train,
        "final_train": final_train,
        "loss_ratio": loss_ratio,
        "overfit_gate": gate_report,
        "best_model_state_sha256": _model_state_sha256(model),
        "artifacts": artifacts,
        "is_model_score": False,
    }
    (output / "training-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _training_batch_at(value: Any, *, epoch: int, step: int) -> ModelBatch:
    batch = value(epoch, step) if callable(value) else value
    if not isinstance(batch, ModelBatch):
        raise ValueError("deterministic batch provider must return ModelBatch")
    return batch


def run_from_config(
    config_path: Path,
    *,
    run_dir: Path | None = None,
    resume_path: Path | None = None,
    epoch_limit: int | None = None,
) -> dict[str, Any]:
    source = config_path.resolve(strict=True)
    config = load_train_config(source)
    if config.purpose == "formal":
        raise RuntimeError("formal training is blocked while G1 NOT READY")
    base = _config_base(source)
    train_manifest_path = _resolve_relative(base, config.train_manifest, must_exist=True)
    validation_manifest_path = _resolve_relative(
        base, config.validation_manifest, must_exist=True
    )
    train_manifest = load_training_manifest(train_manifest_path)
    if config.purpose == "g3-overfit" and validation_manifest_path == train_manifest_path:
        validation_manifest = train_manifest
    else:
        validation_manifest = _load_validation_manifest(validation_manifest_path)
    train_split_sha256 = train_manifest.get("split_sha256")
    validation_split_sha256 = validation_manifest.get("split_sha256")
    if train_split_sha256 != validation_split_sha256:
        raise ValueError("training and validation manifests use different frozen splits")
    roots = {
        dataset_id: _resolve_relative(base, root, must_exist=True)
        for dataset_id, root in config.dataset_roots.items()
    }
    train_ids, train_offsets, train_batch = _load_manifest_batch(
        train_manifest,
        roots,
        limit=config.track_limit,
        segment_seconds=config.segment_seconds,
        segment_start_policy=config.segment_start_policy,
        feature_config=config.feature_config,
        vocabulary=ChordVocabulary.default(),
    )
    if validation_manifest is train_manifest:
        validation_ids, validation_offsets, validation_batch = (
            train_ids,
            train_offsets,
            train_batch,
        )
    else:
        validation_ids, validation_offsets, validation_batch = _load_manifest_batch(
            validation_manifest,
            roots,
            limit=config.track_limit,
            segment_seconds=config.segment_seconds,
            segment_start_policy=config.segment_start_policy,
            feature_config=config.feature_config,
            vocabulary=ChordVocabulary.default(),
        )
    identity = CheckpointIdentity(
        run_config_sha256=_file_sha256(source),
        train_manifest_sha256=_file_sha256(train_manifest_path),
        validation_manifest_sha256=_file_sha256(validation_manifest_path),
        split_sha256=str(train_split_sha256),
    )
    destination = (
        _resolve_relative(base, config.output_root, must_exist=False)
        if run_dir is None
        else run_dir.resolve(strict=False)
    )
    report = run_training_batches(
        config,
        train_batch,
        validation_batch,
        identity,
        destination,
        resume_path=resume_path,
        epoch_limit=epoch_limit,
    )
    report.update(
        {
            "track_ids": list(train_ids),
            "validation_track_ids": list(validation_ids),
            "train_segment_offsets_seconds": list(train_offsets),
            "validation_segment_offsets_seconds": list(validation_offsets),
            "git_commit": _git_commit(base),
            "config_file_sha256": identity.run_config_sha256,
        }
    )
    (destination / "training-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    gate = report["overfit_gate"]
    if gate is not None and not gate["passed"]:
        raise RuntimeError("G3 overfit gate failed; report was preserved")
    return report


def _load_validation_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("validation manifest is unreadable") from error
    if not isinstance(manifest, dict) or manifest.get("split") != "validation":
        raise PermissionError("only the frozen validation split is available to validation")
    if manifest.get("corpus_role") != "real-gold":
        raise ValueError("validation split must contain real-gold tracks")
    if not isinstance(manifest.get("tracks"), list) or not manifest["tracks"]:
        raise ValueError("validation split must contain tracks")
    return manifest


def _load_manifest_batch(
    manifest: dict[str, Any],
    dataset_roots: dict[str, Path],
    *,
    limit: int | None,
    track_indices: tuple[int, ...] | None = None,
    segment_seconds: float,
    segment_start_policy: str,
    feature_config: CqtConfig,
    vocabulary: ChordVocabulary,
) -> tuple[tuple[str, ...], tuple[float, ...], ModelBatch]:
    tracks = manifest.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        raise ValueError("training manifest must contain tracks")
    if track_indices is not None and limit is not None:
        raise ValueError("training track indices and limit are mutually exclusive")
    if track_indices is not None:
        if not track_indices or any(
            type(index) is not int or not 0 <= index < len(tracks)
            for index in track_indices
        ):
            raise ValueError("training track indices are invalid")
        selected = [tracks[index] for index in track_indices]
    else:
        selected = tracks if limit is None else tracks[:limit]
    if limit is not None and len(selected) < limit:
        raise ValueError("training manifest does not contain the configured track limit")
    identifiers: list[str] = []
    offsets: list[float] = []
    examples: list[TrainingExample] = []
    for track in selected:
        if not isinstance(track, dict):
            raise ValueError("training manifest track must be an object")
        track_id = track.get("track_id")
        dataset_id = track.get("dataset_id", manifest.get("dataset_id"))
        audio_relative = track.get("audio_path")
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (track_id, dataset_id, audio_relative)
        ):
            raise ValueError("training manifest track identifiers and path are invalid")
        root = dataset_roots.get(dataset_id)
        if root is None:
            raise ValueError(f"training config has no dataset root for {dataset_id}")
        audio_path = (root / audio_relative).resolve(strict=True)
        if not audio_path.is_relative_to(root) or not audio_path.is_file():
            raise ValueError("training audio path escapes its dataset root")
        offset = (
            0.0
            if segment_start_policy == "start"
            else _first_supervised_offset(track.get("intervals"))
        )
        audio, sample_rate = _read_wav_segment(audio_path, offset, segment_seconds)
        duration = len(audio) / sample_rate
        features = extract_features(audio, sample_rate=sample_rate, config=feature_config)
        intervals = _manifest_intervals(
            track.get("intervals"), offset, duration, vocabulary=vocabulary
        )
        identifiers.append(track_id)
        offsets.append(offset)
        examples.append(TrainingExample(features, intervals))
    return (
        tuple(identifiers),
        tuple(offsets),
        collate_examples(examples, vocabulary),
    )


def _read_wav_segment(path: Path, start: float, seconds: float) -> tuple[np.ndarray, int]:
    try:
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            if channels <= 0 or sample_width != 2 or sample_rate <= 0:
                raise ValueError("training requires 16-bit PCM WAV audio")
            start_frame = min(source.getnframes(), math.floor(start * sample_rate))
            source.setpos(start_frame)
            frame_count = min(
                source.getnframes() - start_frame, math.ceil(seconds * sample_rate)
            )
            samples = np.frombuffer(source.readframes(frame_count), dtype="<i2")
    except (EOFError, wave.Error) as error:
        raise ValueError(f"training WAV is unreadable: {path.name}") from error
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)
    if not len(samples):
        raise ValueError("training WAV segment is empty")
    return np.ascontiguousarray(samples), sample_rate


def _first_supervised_offset(value: object) -> float:
    if not isinstance(value, list):
        raise ValueError("training manifest intervals are invalid")
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("training manifest interval is invalid")
        labels = (item.get("root"), item.get("quality"), item.get("bass"))
        if all(isinstance(label, str) and label not in {"N", "X"} for label in labels):
            offset = float(item["start_seconds"])
            if math.isfinite(offset) and offset >= 0:
                return offset
    raise ValueError("training track has no fully supervised chord interval")


def _manifest_intervals(
    value: object,
    offset: float,
    duration: float,
    *,
    vocabulary: ChordVocabulary,
) -> tuple[ChordInterval, ...]:
    if not isinstance(value, list):
        raise ValueError("training manifest intervals are invalid")
    intervals: list[ChordInterval] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("training manifest interval is invalid")
        absolute_start = float(item["start_seconds"])
        absolute_end = float(item["end_seconds"])
        if absolute_end <= offset:
            continue
        if absolute_start >= offset + duration:
            break
        start = max(absolute_start, offset) - offset
        end = min(absolute_end, offset + duration) - offset
        if end <= start:
            continue
        chord = map_to_frozen_vocabulary(
            CanonicalChord(
                str(item["root"]),
                str(item["quality"]),
                str(item["bass"]),
                item.get("mapping_reason"),
            ),
            vocabulary,
        )
        intervals.append(
            ChordInterval(
                start,
                end,
                chord,
            )
        )
    if not intervals:
        raise ValueError("training segment does not contain chord labels")
    return tuple(intervals)


def _resolve_relative(base: Path, value: str, *, must_exist: bool) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError("training config paths must be relative")
    resolved = (base / candidate).resolve(strict=must_exist)
    if not resolved.is_relative_to(base.resolve(strict=True)):
        raise ValueError("training config path escapes the ML project root")
    return resolved


def _config_base(source: Path) -> Path:
    for candidate in source.parents:
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "src" / "museecho_ml"
        ).is_dir():
            return candidate
    return source.parent


def _git_commit(base: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(base), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value if len(value) == 40 else None


def _build_model(config: TrainConfig):
    from museecho_ml.model.crnn import ChordCrnn

    return ChordCrnn(config.model_config)


def _evaluate(
    model: Any,
    batch: ModelBatch,
    loss_config: LossConfig,
    device: torch.device,
) -> dict[str, float]:
    model.eval()
    model.to(device)
    targets = batch.targets
    device_targets = type(targets)(
        root=targets.root.to(device),
        quality=targets.quality.to(device),
        bass=targets.bass.to(device),
        boundary=targets.boundary.to(device),
        mask=targets.mask.to(device),
        bass_mask=targets.bass_mask.to(device),
    )
    with torch.no_grad():
        logits = model(
            batch.main.to(device),
            batch.bass.to(device),
            batch.sequence_mask.to(device),
        )
        loss = multitask_loss(logits, device_targets, loss_config)
        valid = device_targets.mask
        root_accuracy = (logits.root.argmax(-1)[valid] == device_targets.root[valid]).float().mean()
        quality_accuracy = (
            logits.quality.argmax(-1)[valid] == device_targets.quality[valid]
        ).float().mean()
    result = {
        "total_loss": float(loss.total.cpu()),
        "root_accuracy": float(root_accuracy.cpu()),
        "quality_accuracy": float(quality_accuracy.cpu()),
    }
    result["root_quality_accuracy"] = (
        result["root_accuracy"] + result["quality_accuracy"]
    ) / 2
    if not all(math.isfinite(value) for value in result.values()):
        raise RuntimeError("training evaluation metrics must be finite")
    return result


def _overfit_gate_report(
    gate: OverfitGateConfig | None,
    final_train: dict[str, float],
    loss_ratio: float,
) -> dict[str, Any] | None:
    if gate is None:
        return None
    passed = (
        loss_ratio <= gate.maximum_loss_ratio
        and final_train["root_accuracy"] >= gate.minimum_root_accuracy
        and final_train["quality_accuracy"] >= gate.minimum_quality_accuracy
    )
    return {
        "passed": passed,
        "maximum_loss_ratio": gate.maximum_loss_ratio,
        "minimum_root_accuracy": gate.minimum_root_accuracy,
        "minimum_quality_accuracy": gate.minimum_quality_accuracy,
    }


def _model_state_sha256(model: Any) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        value = tensor.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(json.dumps(list(value.shape), separators=(",", ":")).encode("ascii"))
        digest.update(value.numpy().tobytes())
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run a configuration-bound reproducible chord training job"
    )
    parser.add_argument("config", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--epoch-limit", type=int)
    args = parser.parse_args(argv)
    report = run_from_config(
        args.config,
        run_dir=args.run_dir,
        resume_path=args.resume,
        epoch_limit=args.epoch_limit,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
