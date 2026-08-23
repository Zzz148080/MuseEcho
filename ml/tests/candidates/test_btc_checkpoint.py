from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest
import torch

from museecho_ml.artifacts import file_sha256
from museecho_ml.candidates.btc_artifact import BtcArtifactLock
from museecho_ml.candidates.btc_checkpoint import (
    checkpoint_contract,
    load_btc_checkpoint,
    main,
)
from museecho_ml.candidates.btc_model import BtcModel, BtcModelConfig


def _artifact_lock(path: Path, *, sha256: str | None = None) -> BtcArtifactLock:
    return BtcArtifactLock(
        repository="fixture/btc",
        repository_ref="fixture",
        source_url="https://raw.githubusercontent.com/fixture/btc/fixture/btc.pt",
        size_bytes=path.stat().st_size,
        git_blob_sha1="0" * 40,
        sha256=sha256 or file_sha256(path),
        license_spdx="MIT",
    )


def _save_checkpoint(
    path: Path,
    model: BtcModel,
    *,
    state: OrderedDict[str, torch.Tensor] | dict[str, torch.Tensor] | None = None,
    mean: object = 0.0,
    std: object = np.float64(1.0),
) -> BtcArtifactLock:
    torch.save(
        {
            "model": model.state_dict() if state is None else state,
            "mean": mean,
            "std": std,
        },
        path,
    )
    return _artifact_lock(path)


def test_btc_model_emits_170_logits_per_frame() -> None:
    model = BtcModel(BtcModelConfig.small_test_config())

    output = model(torch.zeros((2, 8, model.config.feature_size)))

    assert output.shape == (2, 8, 170)


def test_btc_model_rejects_wrong_feature_shape() -> None:
    model = BtcModel(BtcModelConfig.small_test_config())

    with pytest.raises(ValueError, match="feature tensor shape"):
        model(torch.zeros((2, 8, 143)))


def test_btc_checkpoint_loads_legacy_numpy_scalar_with_safe_loader(
    tmp_path: Path,
) -> None:
    config = BtcModelConfig.small_test_config()
    model = BtcModel(config)
    path = tmp_path / "safe.pt"
    lock = _save_checkpoint(path, model, mean=-2.25, std=np.float64(1.75))

    loaded = load_btc_checkpoint(path, lock, config)

    assert loaded.mean == pytest.approx(-2.25)
    assert loaded.std == pytest.approx(1.75)
    assert loaded.model.training is False
    assert all(not parameter.requires_grad for parameter in loaded.model.parameters())
    contract = checkpoint_contract(loaded)
    assert contract["num_chords"] == 170
    assert contract["feature_size"] == 144
    assert contract["model_tensor_count"] == len(model.state_dict())
    assert len(contract["tensor_contract_sha256"]) == 64
    assert contract["safe_loader"] is True


def test_btc_checkpoint_refuses_missing_tensor(tmp_path: Path) -> None:
    config = BtcModelConfig.small_test_config()
    model = BtcModel(config)
    state = model.state_dict()
    state.pop(next(iter(state)))
    path = tmp_path / "missing.pt"
    lock = _save_checkpoint(path, model, state=state)

    with pytest.raises(ValueError, match="tensor contract"):
        load_btc_checkpoint(path, lock, config)


def test_btc_checkpoint_refuses_extra_or_wrong_shape_tensor(tmp_path: Path) -> None:
    config = BtcModelConfig.small_test_config()
    model = BtcModel(config)
    extra_state = model.state_dict()
    extra_state["unexpected.weight"] = torch.ones(1)
    extra_path = tmp_path / "extra.pt"
    extra_lock = _save_checkpoint(extra_path, model, state=extra_state)

    with pytest.raises(ValueError, match="tensor contract"):
        load_btc_checkpoint(extra_path, extra_lock, config)

    shape_state = model.state_dict()
    first_name = next(iter(shape_state))
    shape_state[first_name] = torch.ones(1)
    shape_path = tmp_path / "shape.pt"
    shape_lock = _save_checkpoint(shape_path, model, state=shape_state)

    with pytest.raises(ValueError, match="tensor contract"):
        load_btc_checkpoint(shape_path, shape_lock, config)


def test_btc_checkpoint_refuses_nonfinite_tensor(tmp_path: Path) -> None:
    config = BtcModelConfig.small_test_config()
    model = BtcModel(config)
    state = model.state_dict()
    first_name = next(iter(state))
    state[first_name] = state[first_name].clone()
    state[first_name].view(-1)[0] = float("nan")
    path = tmp_path / "nonfinite.pt"
    lock = _save_checkpoint(path, model, state=state)

    with pytest.raises(ValueError, match="tensor contract"):
        load_btc_checkpoint(path, lock, config)


@pytest.mark.parametrize(
    ("mean", "std"),
    [
        (float("nan"), 1.0),
        (0.0, 0.0),
        (0.0, -1.0),
    ],
)
def test_btc_checkpoint_refuses_invalid_normalization(
    tmp_path: Path, mean: object, std: object
) -> None:
    config = BtcModelConfig.small_test_config()
    model = BtcModel(config)
    path = tmp_path / "normalization.pt"
    lock = _save_checkpoint(path, model, mean=mean, std=std)

    with pytest.raises(ValueError, match="normalization"):
        load_btc_checkpoint(path, lock, config)


def test_btc_checkpoint_refuses_array_normalization_without_broadening_safe_globals(
    tmp_path: Path,
) -> None:
    config = BtcModelConfig.small_test_config()
    model = BtcModel(config)
    path = tmp_path / "array-normalization.pt"
    lock = _save_checkpoint(path, model, mean=np.zeros(144), std=1.0)

    with pytest.raises(ValueError, match="cannot be loaded safely"):
        load_btc_checkpoint(path, lock, config)


def _write_marker(path: str) -> int:
    Path(path).write_text("unsafe loader executed", encoding="utf-8")
    return 0


class _MaliciousPayload:
    def __init__(self, marker: Path) -> None:
        self.marker = marker

    def __reduce__(self):
        return _write_marker, (str(self.marker),)


def test_btc_checkpoint_never_executes_malicious_pickle(tmp_path: Path) -> None:
    marker = tmp_path / "executed.txt"
    path = tmp_path / "malicious.pt"
    torch.save({"model": _MaliciousPayload(marker), "mean": 0.0, "std": 1.0}, path)

    with pytest.raises(ValueError, match="cannot be loaded safely"):
        load_btc_checkpoint(
            path,
            _artifact_lock(path),
            BtcModelConfig.small_test_config(),
        )

    assert not marker.exists()


def test_btc_checkpoint_rejects_sha256_mismatch_before_deserialization(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "executed.txt"
    path = tmp_path / "mismatch.pt"
    torch.save({"model": _MaliciousPayload(marker), "mean": 0.0, "std": 1.0}, path)

    with pytest.raises(ValueError, match="SHA-256"):
        load_btc_checkpoint(
            path,
            _artifact_lock(path, sha256="f" * 64),
            BtcModelConfig.small_test_config(),
        )

    assert not marker.exists()


def test_btc_checkpoint_inspect_cli_emits_safe_path_free_contract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = BtcModelConfig.official()
    model = BtcModel(config)
    checkpoint_path = tmp_path / "inspect.pt"
    lock = _save_checkpoint(checkpoint_path, model)
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(asdict(lock)), encoding="utf-8")

    exit_code = main(
        [
            "inspect",
            "--checkpoint",
            str(checkpoint_path),
            "--lock",
            str(lock_path),
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert report["num_chords"] == 170
    assert report["feature_size"] == 144
    assert report["safe_loader"] is True
    assert "checkpoint_path" not in report
