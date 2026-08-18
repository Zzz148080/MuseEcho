from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch

from museecho_ml.data.manifest import ChordInterval
from museecho_ml.features.cqt import FeatureSequence
from museecho_ml.labels import parse_annotation
from museecho_ml.model.batch import TrainingExample, collate_examples
from museecho_ml.model.crnn import ChordCrnn, CrnnConfig
from museecho_ml.model.loss import LossConfig
from museecho_ml.training.trainer import TrainerConfig, build_optimizer, train_step
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
