from __future__ import annotations

import os
import random
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch

from museecho_ml.artifacts import file_sha256

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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


@dataclass(frozen=True)
class CheckpointIdentity:
    run_config_sha256: str
    train_manifest_sha256: str
    validation_manifest_sha256: str
    split_sha256: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or _SHA256.fullmatch(value) is None
            for value in asdict(self).values()
        ):
            raise ValueError("checkpoint identity values must be lowercase SHA-256")


def save_checkpoint(
    path: Path,
    model: Any,
    optimizer: Any,
    scheduler: Any,
    early_stopper: Any,
    state: TrainingState,
    *,
    identity: CheckpointIdentity,
    trainer_config: Any,
    loss_config: Any,
    data_generator: torch.Generator | None = None,
) -> None:
    destination = path.resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(f"{destination.suffix}.tmp")
    payload = {
        "schema_version": 2,
        "checkpoint_version": "checkpoint-v2",
        "identity": asdict(identity),
        "model_config": asdict(model.config),
        "trainer_config": _config_dict(trainer_config),
        "loss_config": _config_dict(loss_config),
        "training_state": asdict(state),
        "model_state": model.state_dict(),
        "optimizer_state": optimizer.state_dict(),
        "scheduler_state": scheduler.state_dict(),
        "early_stop_state": early_stopper.state_dict(),
        "python_rng_state": random.getstate(),
        "numpy_rng_state": np.random.get_state(),
        "torch_rng_state": torch.get_rng_state(),
        "cuda_rng_states": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None,
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
    model: Any,
    optimizer: Any,
    scheduler: Any,
    early_stopper: Any,
    *,
    identity: CheckpointIdentity,
    trainer_config: Any,
    loss_config: Any,
    data_generator: torch.Generator | None = None,
) -> TrainingState:
    source = path.resolve(strict=True)
    try:
        payload = torch.load(source, map_location="cpu", weights_only=False)
    except (OSError, RuntimeError, ValueError) as error:
        raise ValueError("training checkpoint is unreadable") from error
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 2
        or payload.get("checkpoint_version") != "checkpoint-v2"
    ):
        raise ValueError("training checkpoint version is unsupported")
    if payload.get("identity") != asdict(identity):
        raise ValueError("training checkpoint identity does not match")
    if payload.get("model_config") != asdict(model.config):
        raise ValueError("training checkpoint model config does not match")
    if payload.get("trainer_config") != _config_dict(trainer_config):
        raise ValueError("training checkpoint trainer config does not match")
    if payload.get("loss_config") != _config_dict(loss_config):
        raise ValueError("training checkpoint loss config does not match")
    try:
        state = TrainingState(**payload["training_state"])
        cuda_rng_states = payload["cuda_rng_states"]
        generator_state = payload["data_generator_state"]
        if cuda_rng_states is not None and not torch.cuda.is_available():
            raise ValueError("CUDA checkpoint cannot be exactly resumed without CUDA")
        if generator_state is not None and data_generator is None:
            raise ValueError("checkpoint requires a data generator for exact resume")
        if generator_state is None and data_generator is not None:
            raise ValueError("checkpoint does not contain a data generator state")
        model.load_state_dict(payload["model_state"], strict=True)
        optimizer.load_state_dict(payload["optimizer_state"])
        scheduler.load_state_dict(payload["scheduler_state"])
        early_stopper.load_state_dict(payload["early_stop_state"])
        random.setstate(payload["python_rng_state"])
        np.random.set_state(payload["numpy_rng_state"])
        torch.set_rng_state(payload["torch_rng_state"])
        if cuda_rng_states is not None:
            torch.cuda.set_rng_state_all(cuda_rng_states)
        if data_generator is not None:
            data_generator.set_state(generator_state)
    except (KeyError, TypeError, RuntimeError, ValueError) as error:
        raise ValueError("training checkpoint state is invalid") from error
    return state


def load_model_initialization(
    path: Path,
    model: Any,
    *,
    expected_checkpoint_sha256: str,
) -> None:
    source = path.resolve(strict=True)
    if file_sha256(source) != expected_checkpoint_sha256:
        raise ValueError("initialization checkpoint SHA-256 does not match")
    try:
        payload = torch.load(source, map_location="cpu", weights_only=False)
    except (OSError, RuntimeError, ValueError) as error:
        raise ValueError("initialization checkpoint is unreadable") from error
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 2
        or payload.get("checkpoint_version") != "checkpoint-v2"
    ):
        raise ValueError("initialization checkpoint version is unsupported")
    if payload.get("model_config") != asdict(model.config):
        raise ValueError("initialization checkpoint model config does not match")
    model_state = payload.get("model_state")
    expected_state = model.state_dict()
    if (
        not isinstance(model_state, Mapping)
        or set(model_state) != set(expected_state)
        or any(
            not isinstance(model_state[name], torch.Tensor)
            or model_state[name].shape != expected.shape
            or model_state[name].dtype != expected.dtype
            for name, expected in expected_state.items()
        )
    ):
        raise ValueError("initialization checkpoint model state is invalid")
    try:
        model.load_state_dict(model_state, strict=True)
    except (KeyError, TypeError, RuntimeError, ValueError) as error:
        raise ValueError("initialization checkpoint model state is invalid") from error


def _config_dict(value: Any) -> dict[str, Any]:
    if not is_dataclass(value) or isinstance(value, type):
        raise ValueError("checkpoint configurations must be dataclass instances")
    return asdict(value)
