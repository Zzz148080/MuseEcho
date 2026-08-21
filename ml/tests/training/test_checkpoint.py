from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pytest
import torch

from museecho_ml.artifacts import file_sha256
from museecho_ml.model.crnn import ChordCrnn, CrnnConfig
from museecho_ml.model.loss import LossConfig
from museecho_ml.training.checkpoint import (
    CheckpointIdentity,
    TrainingState,
    load_checkpoint,
    load_model_initialization,
    save_checkpoint,
)
from museecho_ml.training.early_stop import EarlyStopConfig, EarlyStopper
from museecho_ml.training.trainer import TrainerConfig, build_optimizer


def _identity(value: str = "a") -> CheckpointIdentity:
    return CheckpointIdentity(
        run_config_sha256=value * 64,
        train_manifest_sha256="b" * 64,
        validation_manifest_sha256="c" * 64,
        split_sha256="d" * 64,
    )


def _components():
    model = ChordCrnn(
        CrnnConfig(
            main_conv_channels=(4,),
            bass_conv_channels=(4,),
            gru_hidden_size=8,
            gru_layers=1,
            dropout=0.0,
        )
    )
    trainer_config = TrainerConfig()
    optimizer = build_optimizer(model, trainer_config)
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=1, gamma=0.5)
    early_stopper = EarlyStopper(EarlyStopConfig(patience=2))
    return model, trainer_config, optimizer, scheduler, early_stopper


def test_checkpoint_v2_restores_scheduler_early_stop_and_rng_exactly(
    tmp_path: Path,
) -> None:
    random.seed(11)
    np.random.seed(12)
    torch.manual_seed(13)
    model, trainer_config, optimizer, scheduler, early_stopper = _components()
    for parameter in model.parameters():
        parameter.grad = torch.ones_like(parameter)
    optimizer.step()
    scheduler.step()
    early_stopper.update(0.4, epoch=0)
    data_generator = torch.Generator().manual_seed(14)
    checkpoint = tmp_path / "checkpoint.pt"
    state = TrainingState(epoch=1, step_in_epoch=0, global_step=1)

    save_checkpoint(
        checkpoint,
        model,
        optimizer,
        scheduler,
        early_stopper,
        state,
        identity=_identity(),
        trainer_config=trainer_config,
        loss_config=LossConfig(),
        data_generator=data_generator,
    )
    expected_python = random.random()
    expected_numpy = float(np.random.random())
    expected_torch = torch.rand(2)
    expected_data = torch.rand(2, generator=data_generator)
    expected_parameters = [parameter.detach().clone() for parameter in model.parameters()]

    restored_model, _, restored_optimizer, restored_scheduler, restored_stopper = _components()
    restored_generator = torch.Generator()
    restored_state = load_checkpoint(
        checkpoint,
        restored_model,
        restored_optimizer,
        restored_scheduler,
        restored_stopper,
        identity=_identity(),
        trainer_config=trainer_config,
        loss_config=LossConfig(),
        data_generator=restored_generator,
    )

    assert restored_state == state
    assert restored_scheduler.state_dict() == scheduler.state_dict()
    assert restored_stopper.state_dict() == early_stopper.state_dict()
    assert random.random() == expected_python
    assert float(np.random.random()) == expected_numpy
    assert torch.equal(torch.rand(2), expected_torch)
    assert torch.equal(torch.rand(2, generator=restored_generator), expected_data)
    assert all(
        torch.equal(expected, actual)
        for expected, actual in zip(
            expected_parameters, restored_model.parameters(), strict=True
        )
    )


def test_checkpoint_v2_rejects_identity_drift_before_restore(tmp_path: Path) -> None:
    model, trainer_config, optimizer, scheduler, early_stopper = _components()
    checkpoint = tmp_path / "checkpoint.pt"
    save_checkpoint(
        checkpoint,
        model,
        optimizer,
        scheduler,
        early_stopper,
        TrainingState(epoch=0, step_in_epoch=0, global_step=0),
        identity=_identity(),
        trainer_config=trainer_config,
        loss_config=LossConfig(),
    )
    original = [parameter.detach().clone() for parameter in model.parameters()]

    with pytest.raises(ValueError, match="identity"):
        load_checkpoint(
            checkpoint,
            model,
            optimizer,
            scheduler,
            early_stopper,
            identity=_identity("e"),
            trainer_config=trainer_config,
            loss_config=LossConfig(),
        )

    assert all(
        torch.equal(expected, actual)
        for expected, actual in zip(original, model.parameters(), strict=True)
    )


def test_pretrain_transfer_loads_model_only_and_keeps_optimizer_fresh(
    tmp_path: Path,
) -> None:
    source_model, trainer_config, source_optimizer, scheduler, early_stopper = (
        _components()
    )
    for parameter in source_model.parameters():
        parameter.grad = torch.ones_like(parameter)
    source_optimizer.step()
    checkpoint = tmp_path / "pretrain.pt"
    save_checkpoint(
        checkpoint,
        source_model,
        source_optimizer,
        scheduler,
        early_stopper,
        TrainingState(epoch=1, step_in_epoch=0, global_step=1),
        identity=_identity(),
        trainer_config=trainer_config,
        loss_config=LossConfig(),
    )
    target_model, _, target_optimizer, _, _ = _components()

    load_model_initialization(
        checkpoint,
        target_model,
        expected_checkpoint_sha256=file_sha256(checkpoint),
    )

    assert target_optimizer.state == {}
    assert all(
        torch.equal(source, target)
        for source, target in zip(
            source_model.parameters(), target_model.parameters(), strict=True
        )
    )


def test_pretrain_transfer_rejects_wrong_hash_before_mutating_model(
    tmp_path: Path,
) -> None:
    source_model, trainer_config, optimizer, scheduler, early_stopper = _components()
    checkpoint = tmp_path / "pretrain.pt"
    save_checkpoint(
        checkpoint,
        source_model,
        optimizer,
        scheduler,
        early_stopper,
        TrainingState(epoch=0, step_in_epoch=0, global_step=0),
        identity=_identity(),
        trainer_config=trainer_config,
        loss_config=LossConfig(),
    )
    target_model, _, _, _, _ = _components()
    original = [parameter.detach().clone() for parameter in target_model.parameters()]

    with pytest.raises(ValueError, match="SHA-256"):
        load_model_initialization(
            checkpoint,
            target_model,
            expected_checkpoint_sha256="f" * 64,
        )

    assert all(
        torch.equal(expected, actual)
        for expected, actual in zip(original, target_model.parameters(), strict=True)
    )


def test_pretrain_transfer_rejects_model_configuration_drift(tmp_path: Path) -> None:
    source_model, trainer_config, optimizer, scheduler, early_stopper = _components()
    checkpoint = tmp_path / "pretrain.pt"
    save_checkpoint(
        checkpoint,
        source_model,
        optimizer,
        scheduler,
        early_stopper,
        TrainingState(epoch=0, step_in_epoch=0, global_step=0),
        identity=_identity(),
        trainer_config=trainer_config,
        loss_config=LossConfig(),
    )
    incompatible_model = ChordCrnn(
        CrnnConfig(
            main_conv_channels=(4,),
            bass_conv_channels=(4,),
            gru_hidden_size=8,
            gru_layers=1,
            dropout=0.0,
            quality_classes=10,
        )
    )

    with pytest.raises(ValueError, match="model config"):
        load_model_initialization(
            checkpoint,
            incompatible_model,
            expected_checkpoint_sha256=file_sha256(checkpoint),
        )


def test_pretrain_transfer_rejects_invalid_state_before_partial_mutation(
    tmp_path: Path,
) -> None:
    source_model, trainer_config, optimizer, scheduler, early_stopper = _components()
    checkpoint = tmp_path / "pretrain.pt"
    save_checkpoint(
        checkpoint,
        source_model,
        optimizer,
        scheduler,
        early_stopper,
        TrainingState(epoch=0, step_in_epoch=0, global_step=0),
        identity=_identity(),
        trainer_config=trainer_config,
        loss_config=LossConfig(),
    )
    payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
    state = payload["model_state"]
    first_name = next(iter(state))
    state[first_name] = torch.zeros_like(state[first_name])
    state.pop(next(reversed(state)))
    torch.save(payload, checkpoint)
    target_model, _, _, _, _ = _components()
    original = [parameter.detach().clone() for parameter in target_model.parameters()]

    with pytest.raises(ValueError, match="model state"):
        load_model_initialization(
            checkpoint,
            target_model,
            expected_checkpoint_sha256=file_sha256(checkpoint),
        )

    assert all(
        torch.equal(expected, actual)
        for expected, actual in zip(original, target_model.parameters(), strict=True)
    )
