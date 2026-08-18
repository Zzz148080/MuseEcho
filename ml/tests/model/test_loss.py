from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch

from museecho_ml.model.crnn import ChordLogits
from museecho_ml.model.loss import (
    ChordTargets,
    LossConfig,
    compute_class_weights,
    multitask_loss,
)

ML_ROOT = Path(__file__).resolve().parents[2]


def _logits() -> ChordLogits:
    generator = torch.Generator().manual_seed(20260818)
    return ChordLogits(
        root=torch.randn(2, 4, 14, generator=generator, requires_grad=True),
        quality=torch.randn(2, 4, 11, generator=generator, requires_grad=True),
        bass=torch.randn(2, 4, 14, generator=generator, requires_grad=True),
        boundary=torch.randn(2, 4, generator=generator, requires_grad=True),
    )


def _targets(*, bass_valid: bool = True) -> ChordTargets:
    mask = torch.tensor(
        [[True, True, True, True], [True, True, False, False]], dtype=torch.bool
    )
    return ChordTargets(
        root=torch.tensor([[0, 1, 2, 3], [4, 5, 0, 0]]),
        quality=torch.tensor([[0, 1, 2, 3], [4, 5, 0, 0]]),
        bass=torch.tensor([[0, 1, 2, 3], [4, 5, 0, 0]]),
        boundary=torch.tensor(
            [[0.0, 1.0, 0.0, 1.0], [0.0, 1.0, 0.0, 0.0]]
        ),
        mask=mask,
        bass_mask=mask & bass_valid,
    )


def test_multitask_loss_is_finite_and_backpropagates_every_enabled_head() -> None:
    logits = _logits()

    result = multitask_loss(logits, _targets(), LossConfig())

    assert torch.isfinite(result.total)
    assert result.root.item() > 0
    assert result.quality.item() > 0
    assert result.bass.item() > 0
    assert result.boundary.item() > 0
    result.total.backward()
    assert logits.root.grad is not None
    assert logits.quality.grad is not None
    assert logits.bass.grad is not None
    assert logits.boundary.grad is not None


def test_masked_frames_do_not_change_multitask_loss() -> None:
    first = _logits()
    second = ChordLogits(
        root=first.root.detach().clone().requires_grad_(),
        quality=first.quality.detach().clone().requires_grad_(),
        bass=first.bass.detach().clone().requires_grad_(),
        boundary=first.boundary.detach().clone().requires_grad_(),
    )
    with torch.no_grad():
        second.root[1, 2:] = 1_000
        second.quality[1, 2:] = -1_000
        second.bass[1, 2:] = 500
        second.boundary[1, 2:] = 1_000

    left = multitask_loss(first, _targets(), LossConfig())
    right = multitask_loss(second, _targets(), LossConfig())

    torch.testing.assert_close(left.total, right.total)


def test_empty_bass_supervision_is_explicit_finite_zero() -> None:
    result = multitask_loss(_logits(), _targets(bass_valid=False), LossConfig())

    assert result.bass.item() == 0.0
    assert torch.isfinite(result.total)


def test_loss_rejects_nonfinite_logits() -> None:
    logits = _logits()
    with torch.no_grad():
        logits.root[0, 0, 0] = torch.nan

    with pytest.raises(ValueError, match="finite"):
        multitask_loss(logits, _targets(), LossConfig())


def test_versioned_loss_config_matches_code() -> None:
    payload = json.loads(
        (ML_ROOT / "configs" / "loss-multitask-v1.json").read_text(encoding="utf-8")
    )

    assert LossConfig.from_dict(payload) == LossConfig()


def test_train_split_class_weights_are_inverse_frequency_and_normalized() -> None:
    original = _targets()
    root = original.root.clone()
    root[0, 1] = 0
    targets = ChordTargets(
        root=root,
        quality=original.quality,
        bass=original.bass,
        boundary=original.boundary,
        mask=original.mask,
        bass_mask=original.bass_mask,
    )

    weights = compute_class_weights(
        [targets], root_classes=14, quality_classes=11, bass_classes=14
    )

    assert weights.root[0] < weights.root[2]
    assert weights.root[6:].count_nonzero() == 0
    torch.testing.assert_close(weights.root[root[targets.mask]].mean(), torch.tensor(1.0))
    result = multitask_loss(_logits(), targets, LossConfig(), weights)
    assert torch.isfinite(result.total)


def test_full_n_x_batch_is_finite_and_has_no_bass_supervision() -> None:
    targets = _targets(bass_valid=False)
    targets = ChordTargets(
        root=torch.tensor([[12, 13, 12, 13], [13, 12, 0, 0]]),
        quality=torch.tensor([[9, 10, 9, 10], [10, 9, 0, 0]]),
        bass=torch.tensor([[12, 13, 12, 13], [13, 12, 0, 0]]),
        boundary=targets.boundary,
        mask=targets.mask,
        bass_mask=torch.zeros_like(targets.mask),
    )

    result = multitask_loss(_logits(), targets, LossConfig())

    assert torch.isfinite(result.total)
    assert result.bass.item() == 0.0
