from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import torch
from torch import nn
from torch.optim import AdamW, Optimizer

from museecho_ml.model.batch import ModelBatch
from museecho_ml.model.crnn import ChordCrnn
from museecho_ml.model.loss import ChordTargets, LossConfig, multitask_loss


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
) -> dict[str, float]:
    model.train()
    model.to(device)
    main = batch.main.to(device)
    bass = batch.bass.to(device)
    sequence_mask = batch.sequence_mask.to(device)
    targets = _targets_to(batch.targets, device)
    optimizer.zero_grad(set_to_none=True)
    logits = model(main, bass, sequence_mask)
    result = multitask_loss(logits, targets, loss_config)
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


def _targets_to(targets: ChordTargets, device: torch.device) -> ChordTargets:
    return ChordTargets(
        root=targets.root.to(device),
        quality=targets.quality.to(device),
        bass=targets.bass.to(device),
        boundary=targets.boundary.to(device),
        mask=targets.mask.to(device),
        bass_mask=targets.bass_mask.to(device),
    )
