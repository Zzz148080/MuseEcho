from __future__ import annotations

import json
import wave
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from museecho_ml.data.manifest import ChordInterval
from museecho_ml.features.cqt import FeatureSequence
from museecho_ml.labels import parse_annotation
from museecho_ml.model.batch import TrainingExample, collate_examples
from museecho_ml.training.checkpoint import CheckpointIdentity
from museecho_ml.training.train import (
    OverfitGateConfig,
    TrainConfig,
    load_train_config,
    run_from_config,
    run_training_batches,
)
from museecho_ml.vocabulary import ChordVocabulary

ML_ROOT = Path(__file__).resolve().parents[2]


def _batch():
    features = FeatureSequence(
        main_cqt=np.random.default_rng(7).normal(size=(8, 12)).astype(np.float32),
        bass_cqt=np.random.default_rng(8).normal(size=(4, 12)).astype(np.float32),
        frame_times=np.arange(12, dtype=np.float64) * 0.1,
        valid_mask=np.ones(12, dtype=np.bool_),
    )
    intervals = (
        ChordInterval(0.0, 0.6, parse_annotation("C:maj")),
        ChordInterval(0.6, 1.2, parse_annotation("G:7")),
    )
    return collate_examples(
        (TrainingExample(features, intervals),), ChordVocabulary.default()
    )


def _identity() -> CheckpointIdentity:
    return CheckpointIdentity(
        run_config_sha256="a" * 64,
        train_manifest_sha256="b" * 64,
        validation_manifest_sha256="c" * 64,
        split_sha256="d" * 64,
    )


def test_cpu_training_runs_are_reproducible_and_validation_selects_best(
    tmp_path: Path,
) -> None:
    config = replace(
        TrainConfig.smoke_defaults(),
        max_epochs=3,
        steps_per_epoch=1,
        overfit_gate=OverfitGateConfig(
            maximum_loss_ratio=2.0,
            minimum_root_accuracy=0.0,
            minimum_quality_accuracy=0.0,
        ),
    )

    first = run_training_batches(
        config, _batch(), _batch(), _identity(), tmp_path / "first"
    )
    second = run_training_batches(
        config, _batch(), _batch(), _identity(), tmp_path / "second"
    )

    assert first["curve"] == second["curve"]
    assert first["best_model_state_sha256"] == second["best_model_state_sha256"]
    assert first["selection_metric"] == "validation_root_quality_accuracy"
    expected_best = max(
        first["curve"], key=lambda item: (item["validation_root_quality_accuracy"], -item["epoch"])
    )
    assert first["best_epoch"] == expected_best["epoch"]
    assert first["device"]["device_type"] == "cpu"
    assert first["overfit_gate"]["passed"] is True
    assert (tmp_path / "first" / "checkpoint-best.pt").is_file()
    assert (tmp_path / "first" / "checkpoint-last.pt").is_file()
    assert (tmp_path / "first" / "artifact-index.json").is_file()


def test_interrupted_cpu_training_resumes_to_uninterrupted_best_state(
    tmp_path: Path,
) -> None:
    config = replace(
        TrainConfig.smoke_defaults(),
        max_epochs=3,
        steps_per_epoch=1,
        overfit_gate=OverfitGateConfig(
            maximum_loss_ratio=2.0,
            minimum_root_accuracy=0.0,
            minimum_quality_accuracy=0.0,
        ),
    )
    interrupted_dir = tmp_path / "interrupted"
    run_training_batches(
        config,
        _batch(),
        _batch(),
        _identity(),
        interrupted_dir,
        epoch_limit=1,
    )

    resumed = run_training_batches(
        config,
        _batch(),
        _batch(),
        _identity(),
        interrupted_dir,
        resume_path=interrupted_dir / "checkpoint-last.pt",
    )
    uninterrupted = run_training_batches(
        config, _batch(), _batch(), _identity(), tmp_path / "uninterrupted"
    )

    assert resumed["best_model_state_sha256"] == uninterrupted["best_model_state_sha256"]
    assert resumed["resumed_from_epoch"] == 1


def test_versioned_smoke_and_formal_training_configs_are_strictly_loadable() -> None:
    smoke = load_train_config(ML_ROOT / "configs" / "train-smoke.json")
    formal = load_train_config(ML_ROOT / "configs" / "train-crnn-v1.json")
    r0 = load_train_config(ML_ROOT / "configs" / "experiments" / "r0-pipeline-smoke.json")

    assert smoke.purpose == "g3-overfit"
    assert smoke.device == "cpu"
    assert smoke.overfit_gate is not None
    assert formal.purpose == "formal"
    assert formal.validation_manifest.endswith("real-gold-validation.manifest.json")
    assert r0.purpose == "r0-smoke"
    assert r0.validation_manifest.endswith("real-gold-validation.manifest.json")


def test_config_cli_runs_real_wav_pipeline_and_binds_manifest_hashes(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    tracks = []
    for index, frequency in enumerate((220.0, 330.0)):
        audio_path = data_root / f"track-{index}.wav"
        _write_tone(audio_path, frequency)
        tracks.append(
            {
                "track_id": f"fixture:{index}",
                "dataset_id": "fixture",
                "audio_path": audio_path.name,
                "intervals": [
                    {
                        "start_seconds": 0.0,
                        "end_seconds": 0.5,
                        "root": "X",
                        "quality": "X",
                        "bass": "X",
                        "mapping_reason": "fixture-unsupported",
                    },
                    {
                        "start_seconds": 0.5,
                        "end_seconds": 1.25,
                        "root": "C",
                        "quality": "maj",
                        "bass": "1",
                        "mapping_reason": None,
                    },
                    {
                        "start_seconds": 1.25,
                        "end_seconds": 2.0,
                        "root": "G",
                        "quality": "7",
                        "bass": "1",
                        "mapping_reason": None,
                    },
                ],
            }
        )
    manifest = {
        "schema_version": 1,
        "corpus_role": "real-gold",
        "split": "train",
        "split_sha256": "d" * 64,
        "tracks": tracks,
    }
    manifest_path = tmp_path / "train.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    payload = json.loads(
        (ML_ROOT / "configs" / "train-smoke.json").read_text(encoding="utf-8")
    )
    payload.update(
        {
            "max_epochs": 1,
            "train_manifest": "train.json",
            "validation_manifest": "train.json",
            "dataset_roots": {"fixture": "data"},
            "output_root": "runs",
            "segment_seconds": 2.0,
            "overfit_gate": {
                "maximum_loss_ratio": 2.0,
                "minimum_root_accuracy": 0.0,
                "minimum_quality_accuracy": 0.0,
            },
        }
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    payload["max_epochs"] = 2
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    report = run_from_config(
        config_path, run_dir=tmp_path / "run", epoch_limit=1
    )

    assert report["track_ids"] == ["fixture:0", "fixture:1"]
    assert report["train_segment_offsets_seconds"] == [0.5, 0.5]
    assert report["checkpoint_identity"]["split_sha256"] == "d" * 64
    assert report["stop_reason"] == "operational_limit"
    assert (tmp_path / "run" / "training-report.json").is_file()

    resumed = run_from_config(
        config_path,
        run_dir=tmp_path / "run",
        resume_path=tmp_path / "run" / "checkpoint-last.pt",
    )

    assert resumed["resumed_from_epoch"] == 1
    assert resumed["curve"][0]["epoch"] == 1


def test_formal_config_is_blocked_while_g1_is_not_ready(tmp_path: Path) -> None:
    config = ML_ROOT / "configs" / "train-crnn-v1.json"

    with pytest.raises(RuntimeError, match="G1 NOT READY"):
        run_from_config(config, run_dir=tmp_path / "formal")


def _write_tone(path: Path, frequency: float) -> None:
    sample_rate = 22_050
    time = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    samples = (0.1 * np.sin(2 * np.pi * frequency * time) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(samples.tobytes())
