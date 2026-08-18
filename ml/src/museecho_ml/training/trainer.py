from __future__ import annotations

import math
import os
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn
from torch.optim import AdamW, Optimizer

from museecho_ml.model.batch import ModelBatch
from museecho_ml.model.crnn import ChordCrnn
from museecho_ml.model.loss import (
    ChordTargets,
    ClassWeights,
    LossConfig,
    multitask_loss,
)


@dataclass(frozen=True)
class TrainerConfig:
    learning_rate: float = 0.001
    weight_decay: float = 0.0001
    gradient_clip_norm: float = 5.0

    def __post_init__(self) -> None:
        values = (self.learning_rate, self.weight_decay, self.gradient_clip_norm)
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in values
        ) or (
            self.learning_rate <= 0
            or self.weight_decay < 0
            or self.gradient_clip_norm <= 0
        ):
            raise ValueError("trainer numeric parameters are invalid")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TrainerConfig:
        required = {
            "schema_version",
            "trainer_version",
            "learning_rate",
            "weight_decay",
            "gradient_clip_norm",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("trainer config fields are invalid")
        if value["schema_version"] != 1 or value["trainer_version"] != "trainer-v1":
            raise ValueError("trainer config version is unsupported")
        return cls(
            learning_rate=value["learning_rate"],
            weight_decay=value["weight_decay"],
            gradient_clip_norm=value["gradient_clip_norm"],
        )


@dataclass(frozen=True)
class TrainingState:
    epoch: int
    step_in_epoch: int
    global_step: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0
            for value in (self.epoch, self.step_in_epoch, self.global_step)
        ):
            raise ValueError("training state counters must be non-negative integers")


def build_optimizer(model: nn.Module, config: TrainerConfig) -> Optimizer:
    return AdamW(
        model.parameters(),
        lr=float(config.learning_rate),
        weight_decay=float(config.weight_decay),
    )


def train_step(
    model: ChordCrnn,
    batch: ModelBatch,
    optimizer: Optimizer,
    *,
    loss_config: LossConfig,
    trainer_config: TrainerConfig,
    device: torch.device,
    class_weights: ClassWeights | None = None,
) -> dict[str, float]:
    model.train()
    model.to(device)
    main = batch.main.to(device)
    bass = batch.bass.to(device)
    sequence_mask = batch.sequence_mask.to(device)
    targets = _targets_to(batch.targets, device)
    optimizer.zero_grad(set_to_none=True)
    logits = model(main, bass, sequence_mask)
    weights = class_weights.to(device) if class_weights is not None else None
    result = multitask_loss(logits, targets, loss_config, weights)
    result.total.backward()
    gradient_norm = torch.nn.utils.clip_grad_norm_(
        model.parameters(), float(trainer_config.gradient_clip_norm), error_if_nonfinite=True
    )
    optimizer.step()
    metrics = {
        "total": float(result.total.detach().cpu()),
        "root": float(result.root.detach().cpu()),
        "quality": float(result.quality.detach().cpu()),
        "bass": float(result.bass.detach().cpu()),
        "boundary": float(result.boundary.detach().cpu()),
        "gradient_norm": float(gradient_norm.detach().cpu()),
    }
    if not all(math.isfinite(value) for value in metrics.values()):
        raise ValueError("trainer metrics must be finite")
    return metrics


def configure_cpu_reproducibility(seed: int) -> None:
    """Seed CPU training and require deterministic PyTorch kernels."""

    if type(seed) is not int or seed < 0:
        raise ValueError("reproducibility seed must be a non-negative integer")
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)


def save_checkpoint(
    path: Path,
    model: ChordCrnn,
    optimizer: Optimizer,
    state: TrainingState,
    *,
    trainer_config: TrainerConfig,
    loss_config: LossConfig,
    data_generator: torch.Generator | None = None,
) -> None:
    """Atomically save exact optimizer, counter and random-number state."""

    destination = path.resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(f"{destination.suffix}.tmp")
    payload = {
        "schema_version": 1,
        "checkpoint_version": "checkpoint-v1",
        "model_config": asdict(model.config),
        "trainer_config": asdict(trainer_config),
        "loss_config": asdict(loss_config),
        "training_state": asdict(state),
        "model_state": model.state_dict(),
        "optimizer_state": optimizer.state_dict(),
        "python_rng_state": random.getstate(),
        "numpy_rng_state": np.random.get_state(),
        "torch_rng_state": torch.get_rng_state(),
        "data_generator_state": (
            data_generator.get_state() if data_generator is not None else None
        ),
    }
    try:
        torch.save(payload, temporary)
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def load_checkpoint(
    path: Path,
    model: ChordCrnn,
    optimizer: Optimizer,
    *,
    trainer_config: TrainerConfig,
    loss_config: LossConfig,
    data_generator: torch.Generator | None = None,
) -> TrainingState:
    """Restore an exact checkpoint and reject incompatible configurations."""

    source = path.resolve(strict=True)
    try:
        payload = torch.load(source, map_location="cpu", weights_only=False)
    except (OSError, RuntimeError, ValueError) as error:
        raise ValueError("training checkpoint is unreadable") from error
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or payload.get("checkpoint_version") != "checkpoint-v1"
    ):
        raise ValueError("training checkpoint version is unsupported")
    if payload.get("model_config") != asdict(model.config):
        raise ValueError("training checkpoint model config does not match")
    if payload.get("trainer_config") != asdict(trainer_config):
        raise ValueError("training checkpoint trainer config does not match")
    if payload.get("loss_config") != asdict(loss_config):
        raise ValueError("training checkpoint loss config does not match")
    try:
        state = TrainingState(**payload["training_state"])
        model.load_state_dict(payload["model_state"], strict=True)
        optimizer.load_state_dict(payload["optimizer_state"])
        random.setstate(payload["python_rng_state"])
        np.random.set_state(payload["numpy_rng_state"])
        torch.set_rng_state(payload["torch_rng_state"])
        generator_state = payload["data_generator_state"]
        if generator_state is not None:
            if data_generator is None:
                raise ValueError("checkpoint requires a data generator for exact resume")
            data_generator.set_state(generator_state)
        elif data_generator is not None:
            raise ValueError("checkpoint does not contain a data generator state")
    except (KeyError, TypeError, RuntimeError, ValueError) as error:
        raise ValueError("training checkpoint state is invalid") from error
    return state


def _targets_to(targets: ChordTargets, device: torch.device) -> ChordTargets:
    return ChordTargets(
        root=targets.root.to(device),
        quality=targets.quality.to(device),
        bass=targets.bass.to(device),
        boundary=targets.boundary.to(device),
        mask=targets.mask.to(device),
        bass_mask=targets.bass_mask.to(device),
    )
