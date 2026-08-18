from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np
import torch

from museecho_ml.data.manifest import ChordInterval
from museecho_ml.features.cqt import FeatureSequence
from museecho_ml.labels import parse_annotation
from museecho_ml.model.batch import TrainingExample, collate_examples
from museecho_ml.model.crnn import ChordCrnn, CrnnConfig
from museecho_ml.model.loss import LossConfig
from museecho_ml.training.trainer import (
    TrainerConfig,
    TrainingState,
    build_optimizer,
    configure_cpu_reproducibility,
    load_checkpoint,
    save_checkpoint,
    train_step,
)
from museecho_ml.vocabulary import ChordVocabulary

ML_ROOT = Path(__file__).resolve().parents[2]


def _batch():
    features = FeatureSequence(
        main_cqt=np.random.default_rng(7).normal(size=(8, 8)).astype(np.float32),
        bass_cqt=np.random.default_rng(8).normal(size=(4, 8)).astype(np.float32),
        frame_times=np.arange(8, dtype=np.float64) * 0.1,
        valid_mask=np.ones(8, dtype=np.bool_),
    )
    intervals = (
        ChordInterval(0.0, 0.4, parse_annotation("C:maj")),
        ChordInterval(0.4, 0.8, parse_annotation("G:7")),
    )
    return collate_examples(
        (TrainingExample(features, intervals),), ChordVocabulary.default()
    )


def test_train_step_updates_parameters_with_finite_metrics() -> None:
    torch.manual_seed(20260818)
    model = ChordCrnn(
        CrnnConfig(
            main_conv_channels=(4,),
            bass_conv_channels=(4,),
            gru_hidden_size=8,
            gru_layers=1,
            dropout=0.0,
        )
    )
    optimizer = build_optimizer(model, TrainerConfig())
    before = [parameter.detach().clone() for parameter in model.parameters()]

    metrics = train_step(
        model,
        _batch(),
        optimizer,
        loss_config=LossConfig(),
        trainer_config=TrainerConfig(),
        device=torch.device("cpu"),
    )

    assert all(np.isfinite(value) for value in metrics.values())
    assert metrics["total"] > 0
    assert any(
        not torch.equal(previous, current)
        for previous, current in zip(before, model.parameters(), strict=True)
    )


def test_versioned_trainer_config_matches_code() -> None:
    payload = json.loads(
        (ML_ROOT / "configs" / "trainer-v1.json").read_text(encoding="utf-8")
    )

    assert TrainerConfig.from_dict(payload) == TrainerConfig()


def test_checkpoint_restores_exact_cpu_training_and_rng_state(tmp_path: Path) -> None:
    configure_cpu_reproducibility(20260818)
    config = CrnnConfig(
        main_conv_channels=(4,),
        bass_conv_channels=(4,),
        gru_hidden_size=8,
        gru_layers=1,
        dropout=0.2,
    )
    trainer_config = TrainerConfig()
    loss_config = LossConfig()
    model = ChordCrnn(config)
    optimizer = build_optimizer(model, trainer_config)
    generator = torch.Generator().manual_seed(99)
    train_step(
        model,
        _batch(),
        optimizer,
        loss_config=loss_config,
        trainer_config=trainer_config,
        device=torch.device("cpu"),
    )
    checkpoint = tmp_path / "checkpoint.pt"
    state = TrainingState(epoch=2, step_in_epoch=3, global_step=11)
    save_checkpoint(
        checkpoint,
        model,
        optimizer,
        state,
        trainer_config=trainer_config,
        loss_config=loss_config,
        data_generator=generator,
    )

    expected_python = random.random()
    expected_numpy = float(np.random.random())
    expected_generator = torch.rand(3, generator=generator)
    expected_metrics = train_step(
        model,
        _batch(),
        optimizer,
        loss_config=loss_config,
        trainer_config=trainer_config,
        device=torch.device("cpu"),
    )
    expected_parameters = [parameter.detach().clone() for parameter in model.parameters()]

    restored = load_checkpoint(
        checkpoint,
        model,
        optimizer,
        trainer_config=trainer_config,
        loss_config=loss_config,
        data_generator=generator,
    )
    assert restored == state
    assert random.random() == expected_python
    assert float(np.random.random()) == expected_numpy
    assert torch.equal(torch.rand(3, generator=generator), expected_generator)
    actual_metrics = train_step(
        model,
        _batch(),
        optimizer,
        loss_config=loss_config,
        trainer_config=trainer_config,
        device=torch.device("cpu"),
    )

    assert actual_metrics == expected_metrics
    assert all(
        torch.equal(expected, actual)
        for expected, actual in zip(expected_parameters, model.parameters(), strict=True)
    )


def test_cpu_reproducibility_repeats_initialization_and_step() -> None:
    def run_once() -> tuple[dict[str, float], list[torch.Tensor]]:
        configure_cpu_reproducibility(1234)
        model = ChordCrnn(
            CrnnConfig(
                main_conv_channels=(4,),
                bass_conv_channels=(4,),
                gru_hidden_size=8,
                gru_layers=1,
                dropout=0.2,
            )
        )
        trainer_config = TrainerConfig()
        metrics = train_step(
            model,
            _batch(),
            build_optimizer(model, trainer_config),
            loss_config=LossConfig(),
            trainer_config=trainer_config,
            device=torch.device("cpu"),
        )
        return metrics, [parameter.detach().clone() for parameter in model.parameters()]

    first_metrics, first_parameters = run_once()
    second_metrics, second_parameters = run_once()

    assert first_metrics == second_metrics
    assert all(
        torch.equal(first, second)
        for first, second in zip(first_parameters, second_parameters, strict=True)
    )
