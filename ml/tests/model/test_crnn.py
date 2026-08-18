from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch

from museecho_ml.model.crnn import ChordCrnn, CrnnConfig

ML_ROOT = Path(__file__).resolve().parents[2]


def _inputs() -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    generator = torch.Generator().manual_seed(20260818)
    main = torch.randn(2, 1, 144, 40, generator=generator)
    bass = torch.randn(2, 1, 72, 40, generator=generator)
    mask = torch.zeros(2, 40, dtype=torch.bool)
    mask[0, :] = True
    mask[1, :31] = True
    return main, bass, mask


def test_crnn_outputs_four_time_aligned_heads_and_finite_gradients() -> None:
    torch.manual_seed(20260818)
    model = ChordCrnn(CrnnConfig())
    main, bass, mask = _inputs()

    output = model(main, bass, mask)

    assert output.root.shape == (2, 40, 14)
    assert output.quality.shape == (2, 40, 11)
    assert output.bass.shape == (2, 40, 14)
    assert output.boundary.shape == (2, 40)
    loss = (
        output.root.square().mean()
        + output.quality.square().mean()
        + output.bass.square().mean()
        + output.boundary.square().mean()
    )
    loss.backward()
    gradients = [parameter.grad for parameter in model.parameters() if parameter.grad is not None]
    assert gradients
    assert all(torch.isfinite(gradient).all() for gradient in gradients)


@pytest.mark.parametrize("failure", ["time", "mask", "nan"])
def test_crnn_rejects_invalid_feature_contract(failure: str) -> None:
    model = ChordCrnn(CrnnConfig())
    main, bass, mask = _inputs()
    if failure == "time":
        bass = bass[..., :-1]
    elif failure == "mask":
        mask[1, 20] = False
        mask[1, 21] = True
    else:
        main[0, 0, 0, 0] = torch.nan

    with pytest.raises(ValueError):
        model(main, bass, mask)


def test_versioned_crnn_config_matches_code_and_vocabulary() -> None:
    payload = json.loads(
        (ML_ROOT / "configs" / "model-crnn-v1.json").read_text(encoding="utf-8")
    )

    assert CrnnConfig.from_dict(payload) == CrnnConfig()
