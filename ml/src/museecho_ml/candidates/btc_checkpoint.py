from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch

from museecho_ml.artifacts import canonical_json_bytes, file_sha256
from museecho_ml.candidates.btc_artifact import BtcArtifactLock
from museecho_ml.candidates.btc_model import BtcModel, BtcModelConfig


@dataclass(frozen=True)
class BtcCheckpoint:
    model: BtcModel
    mean: float
    std: float
    artifact_sha256: str
    tensor_contract_sha256: str
    safe_loader: bool = True


def _safe_numpy_globals() -> list[object]:
    return [
        np._core.multiarray.scalar,
        (np._core.multiarray.scalar, "numpy.core.multiarray.scalar"),
        np.dtype,
        np.dtypes.Float64DType,
    ]


def load_btc_checkpoint(
    checkpoint_path: Path,
    lock: BtcArtifactLock,
    config: BtcModelConfig,
) -> BtcCheckpoint:
    resolved = checkpoint_path.resolve(strict=True)
    if file_sha256(resolved) != lock.sha256:
        raise ValueError("BTC checkpoint SHA-256 does not match the artifact lock")
    try:
        with torch.serialization.safe_globals(_safe_numpy_globals()):
            payload: Any = torch.load(
                resolved,
                map_location="cpu",
                weights_only=True,
            )
    except Exception as error:
        raise ValueError("BTC checkpoint cannot be loaded safely") from error
    if not isinstance(payload, Mapping) or set(payload) != {"model", "mean", "std"}:
        raise ValueError("BTC checkpoint payload fields are invalid")

    model = BtcModel(config)
    state = payload["model"]
    _validate_tensor_contract(state, model.state_dict())
    mean = _normalization_scalar(payload["mean"], "mean")
    std = _normalization_scalar(payload["std"], "std")
    if std <= 0:
        raise ValueError("BTC checkpoint normalization std must be positive")
    model.load_state_dict(state, strict=True)
    model.requires_grad_(False)
    model.eval()
    contract_sha256 = _tensor_contract_sha256(model.state_dict())
    return BtcCheckpoint(
        model=model,
        mean=mean,
        std=std,
        artifact_sha256=lock.sha256,
        tensor_contract_sha256=contract_sha256,
    )


def checkpoint_contract(checkpoint: BtcCheckpoint) -> dict[str, object]:
    state = checkpoint.model.state_dict()
    return {
        "num_chords": checkpoint.model.config.num_chords,
        "feature_size": checkpoint.model.config.feature_size,
        "model_tensor_count": len(state),
        "tensor_contract_sha256": checkpoint.tensor_contract_sha256,
        "artifact_sha256": checkpoint.artifact_sha256,
        "normalization_mean": checkpoint.mean,
        "normalization_std": checkpoint.std,
        "safe_loader": checkpoint.safe_loader,
    }


def _normalization_scalar(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
        raise ValueError(f"BTC checkpoint normalization {name} must be a scalar")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"BTC checkpoint normalization {name} must be finite")
    return converted


def _validate_tensor_contract(
    state: Any,
    expected: Mapping[str, torch.Tensor],
) -> None:
    if not isinstance(state, Mapping) or set(state) != set(expected):
        raise ValueError("BTC checkpoint tensor contract keys do not match")
    for name, expected_tensor in expected.items():
        tensor = state[name]
        if (
            not isinstance(tensor, torch.Tensor)
            or tensor.shape != expected_tensor.shape
            or tensor.dtype != expected_tensor.dtype
            or not tensor.is_floating_point()
            or not torch.isfinite(tensor).all().item()
        ):
            raise ValueError(f"BTC checkpoint tensor contract is invalid for {name}")


def _tensor_contract_sha256(state: Mapping[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for name in sorted(state):
        tensor = state[name].detach().cpu().contiguous()
        metadata = {
            "name": name,
            "shape": list(tensor.shape),
            "dtype": str(tensor.dtype),
        }
        digest.update(canonical_json_bytes(metadata))
        digest.update(b"\0")
        digest.update(tensor.numpy().tobytes(order="C"))
        digest.update(b"\0")
    return digest.hexdigest()


def _load_artifact_lock(path: Path) -> BtcArtifactLock:
    try:
        value = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError
        return BtcArtifactLock(**value)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as error:
        raise ValueError("BTC artifact lock is invalid") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect the approved BTC checkpoint")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--checkpoint", type=Path, required=True)
    inspect_parser.add_argument("--lock", type=Path, required=True)
    arguments = parser.parse_args(argv)

    if arguments.command == "inspect":
        checkpoint = load_btc_checkpoint(
            arguments.checkpoint,
            _load_artifact_lock(arguments.lock),
            BtcModelConfig.official(),
        )
        print(json.dumps(checkpoint_contract(checkpoint), sort_keys=True))
        return 0
    raise AssertionError("unreachable BTC checkpoint command")


if __name__ == "__main__":
    raise SystemExit(main())
