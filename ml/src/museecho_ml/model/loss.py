from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import torch
from torch import Tensor
from torch.nn import functional as F

from museecho_ml.model.crnn import ChordLogits


@dataclass(frozen=True)
class LossConfig:
    root_weight: float = 1.0
    quality_weight: float = 1.0
    bass_weight: float = 0.5
    boundary_weight: float = 0.25

    def __post_init__(self) -> None:
        weights = (
            self.root_weight,
            self.quality_weight,
            self.bass_weight,
            self.boundary_weight,
        )
        if any(
            isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or not math.isfinite(weight)
            or weight < 0
            for weight in weights
        ) or not any(weight > 0 for weight in weights):
            raise ValueError(
                "multi-task loss weights must be finite, non-negative and not all zero"
            )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> LossConfig:
        required = {
            "schema_version",
            "loss_version",
            "root_weight",
            "quality_weight",
            "bass_weight",
            "boundary_weight",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("multi-task loss config fields are invalid")
        if value["schema_version"] != 1 or value["loss_version"] != "multitask-v1":
            raise ValueError("multi-task loss config version is unsupported")
        return cls(
            root_weight=value["root_weight"],
            quality_weight=value["quality_weight"],
            bass_weight=value["bass_weight"],
            boundary_weight=value["boundary_weight"],
        )


@dataclass(frozen=True)
class ChordTargets:
    root: Tensor
    quality: Tensor
    bass: Tensor
    boundary: Tensor
    mask: Tensor
    bass_mask: Tensor


@dataclass(frozen=True)
class LossResult:
    total: Tensor
    root: Tensor
    quality: Tensor
    bass: Tensor
    boundary: Tensor


def multitask_loss(
    logits: ChordLogits, targets: ChordTargets, config: LossConfig
) -> LossResult:
    _validate(logits, targets)
    valid = targets.mask
    bass_valid = valid & targets.bass_mask
    root_loss = F.cross_entropy(logits.root[valid], targets.root[valid])
    quality_loss = F.cross_entropy(logits.quality[valid], targets.quality[valid])
    bass_loss = (
        F.cross_entropy(logits.bass[bass_valid], targets.bass[bass_valid])
        if torch.any(bass_valid)
        else logits.bass.sum() * 0.0
    )
    boundary_loss = F.binary_cross_entropy_with_logits(
        logits.boundary[valid], targets.boundary[valid]
    )
    total = (
        float(config.root_weight) * root_loss
        + float(config.quality_weight) * quality_loss
        + float(config.bass_weight) * bass_loss
        + float(config.boundary_weight) * boundary_loss
    )
    if not torch.isfinite(total):
        raise ValueError("multi-task loss must be finite")
    return LossResult(total, root_loss, quality_loss, bass_loss, boundary_loss)


def _validate(logits: ChordLogits, targets: ChordTargets) -> None:
    batch_time = logits.boundary.shape
    if len(batch_time) != 2 or any(
        head.ndim != 3 or head.shape[:2] != batch_time
        for head in (logits.root, logits.quality, logits.bass)
    ):
        raise ValueError("multi-task logits are not batch/time aligned")
    if any(
        tensor.shape != batch_time
        for tensor in (
            targets.root,
            targets.quality,
            targets.bass,
            targets.boundary,
            targets.mask,
            targets.bass_mask,
        )
    ):
        raise ValueError("multi-task targets are not batch/time aligned")
    if targets.mask.dtype != torch.bool or targets.bass_mask.dtype != torch.bool:
        raise ValueError("multi-task masks must be boolean")
    if not torch.any(targets.mask):
        raise ValueError("multi-task targets require a valid frame")
    if any(
        target.dtype != torch.int64
        for target in (targets.root, targets.quality, targets.bass)
    ):
        raise ValueError("multi-task class targets must use int64")
    for name, target, head, mask in (
        ("root", targets.root, logits.root, targets.mask),
        ("quality", targets.quality, logits.quality, targets.mask),
        ("bass", targets.bass, logits.bass, targets.mask & targets.bass_mask),
    ):
        if torch.any(mask) and (
            torch.any(target[mask] < 0) or torch.any(target[mask] >= head.shape[-1])
        ):
            raise ValueError(f"multi-task {name} target is outside its vocabulary")
    if not torch.is_floating_point(targets.boundary) or (
        torch.any(~torch.isfinite(targets.boundary[targets.mask]))
        or torch.any(targets.boundary[targets.mask] < 0)
        or torch.any(targets.boundary[targets.mask] > 1)
    ):
        raise ValueError("multi-task boundary targets must be finite probabilities")
    if any(
        not torch.is_floating_point(head) or not torch.isfinite(head).all()
        for head in (logits.root, logits.quality, logits.bass, logits.boundary)
    ):
        raise ValueError("multi-task logits must be finite floating point tensors")
