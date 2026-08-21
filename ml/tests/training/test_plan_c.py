from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch

from museecho_ml.artifacts import canonical_sha256, file_sha256
from museecho_ml.labels import BASS_INTERVALS, PITCH_NAMES
from museecho_ml.training.plan_c import (
    build_plan_c_stage_identity,
    deterministic_manifest_batch_indices,
    main,
    run_plan_c_stage,
)

ML_ROOT = Path(__file__).resolve().parents[2]


def _write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _vocabulary_payload() -> dict:
    body = {
        "schema_version": 1,
        "vocabulary_version": "plan-c-v1",
        "source_corpus_role": "real-gold",
        "source_split": "train",
        "source_split_sha256": "9" * 64,
        "minimum_group_count": 20,
        "quality_group_counts": {"maj": 20},
        "root_labels": [*PITCH_NAMES, "N", "X"],
        "quality_labels": [
            "maj",
            "min",
            "7",
            "maj7",
            "min7",
            "dim",
            "hdim7",
            "sus4",
            "N",
            "X",
        ],
        "bass_labels": [*BASS_INTERVALS, "N", "X"],
        "mapped_to_x": ["sus2"],
    }
    return {**body, "vocabulary_sha256": canonical_sha256(body)}


def _protocol_payload(vocabulary_sha256: str) -> dict:
    body = {
        "schema_version": 1,
        "plan_version": "plan-c-v1",
        "g1a_status": "passed",
        "vocabulary_sha256": vocabulary_sha256,
        "seeds": [20260821, 20260822, 20260823],
        "real_splits": {
            "train": {
                "corpus_role": "real-gold",
                "dataset_ids": ["fixture-real"],
                "split_sha256": "9" * 64,
                "manifest_sha256": "a" * 64,
            },
            "validation": {
                "corpus_role": "real-gold",
                "dataset_ids": ["fixture-real"],
                "split_sha256": "9" * 64,
                "manifest_sha256": "b" * 64,
            },
        },
        "courses": {
            "C0": {"status": "ready", "pretrain": None},
            "C1": {
                "status": "ready",
                "pretrain": [
                    {
                        "dataset_id": "idmt-smt-chord-sequences",
                        "corpus_role": "synthetic-supervised",
                        "manifest_sha256": "c" * 64,
                    },
                    {
                        "dataset_id": "jazznet",
                        "corpus_role": "synthetic-supervised",
                        "manifest_sha256": "d" * 64,
                    },
                ],
            },
            "C2": {
                "status": "skipped",
                "reason_code": "score-supervision-not-approved",
            },
        },
    }
    return {**body, "protocol_sha256": canonical_sha256(body)}


def _stage_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    vocabulary = _vocabulary_payload()
    vocabulary_path = _write_json(tmp_path / "vocabulary.json", vocabulary)
    protocol_path = _write_json(
        tmp_path / "protocol.json",
        _protocol_payload(vocabulary["vocabulary_sha256"]),
    )
    config = json.loads(
        (ML_ROOT / "configs" / "train-smoke.json").read_text(encoding="utf-8")
    )
    config.update(
        {
            "purpose": "formal",
            "seed": 20260821,
            "train_manifest": "train.json",
            "validation_manifest": "validation.json",
            "dataset_roots": {"fixture-real": "data"},
            "output_root": "runs",
            "track_limit": 1,
            "overfit_gate": None,
        }
    )
    config["model"]["quality_classes"] = 10
    config_path = _write_json(tmp_path / "train.json.config", config)
    return protocol_path, vocabulary_path, config_path


def _write_real_stage_manifests(tmp_path: Path, protocol_path: Path) -> None:
    track = {
        "dataset_id": "fixture-real",
        "track_id": "fixture-real:track-001",
        "audio_path": "track.wav",
        "intervals": [
            {
                "start_seconds": 0.0,
                "end_seconds": 2.0,
                "root": "C",
                "quality": "maj",
                "bass": "1",
                "mapping_reason": None,
            }
        ],
    }
    manifests = {}
    for split in ("train", "validation"):
        manifests[split] = {
            "schema_version": 1,
            "corpus_role": "real-gold",
            "split": split,
            "split_sha256": "9" * 64,
            "tracks": [track],
        }
        _write_json(tmp_path / f"{split}.json", manifests[split])
    (tmp_path / "data").mkdir()
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    protocol.pop("protocol_sha256")
    for split, manifest in manifests.items():
        protocol["real_splits"][split]["manifest_sha256"] = canonical_sha256(
            manifest
        )
    protocol["protocol_sha256"] = canonical_sha256(protocol)
    _write_json(protocol_path, protocol)


def _write_synthetic_stage_manifests(
    tmp_path: Path,
    protocol_path: Path,
    *,
    jazznet_role: str = "synthetic-supervised",
) -> dict[str, Path]:
    manifests = {}
    paths = {}
    roles = {
        "idmt-smt-chord-sequences": "synthetic-supervised",
        "jazznet": jazznet_role,
    }
    for dataset_id, role in roles.items():
        manifest = {
            "schema_version": 1,
            "dataset_id": dataset_id,
            "corpus_role": role,
            "tracks": [
                {
                    "track_id": f"{dataset_id}:track-001",
                    "audio_path": "track.wav",
                    "intervals": [
                        {
                            "start_seconds": 0.0,
                            "end_seconds": 2.0,
                            "root": "C",
                            "quality": "maj",
                            "bass": "1",
                            "mapping_reason": None,
                        }
                    ],
                }
            ],
        }
        manifests[dataset_id] = manifest
        paths[dataset_id] = _write_json(tmp_path / f"{dataset_id}.json", manifest)
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    protocol.pop("protocol_sha256")
    for binding in protocol["courses"]["C1"]["pretrain"]:
        binding["manifest_sha256"] = canonical_sha256(
            manifests[binding["dataset_id"]]
        )
    protocol["protocol_sha256"] = canonical_sha256(protocol)
    _write_json(protocol_path, protocol)
    return paths


def _write_pretrain_checkpoint_provenance(
    tmp_path: Path,
    protocol_path: Path,
    vocabulary_path: Path,
    config_path: Path,
    *,
    seed: int = 20260821,
) -> Path:
    run_dir = tmp_path / "pretrain-run"
    run_dir.mkdir()
    checkpoint = run_dir / "checkpoint-best.pt"
    checkpoint.write_bytes(b"fixture-checkpoint")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    vocabulary = json.loads(vocabulary_path.read_text(encoding="utf-8"))
    _write_json(
        run_dir / "stage-identity.json",
        {
            "schema_version": 1,
            "plan_version": "plan-c-v1",
            "course_id": "C1",
            "stage": "pretrain",
            "seed": seed,
            "base_config_sha256": file_sha256(config_path),
            "protocol_sha256": protocol["protocol_sha256"],
            "vocabulary_sha256": vocabulary["vocabulary_sha256"],
            "initialization_checkpoint_sha256": None,
            "checkpoint_identity": {
                "run_config_sha256": "a" * 64,
                "train_manifest_sha256": "b" * 64,
                "validation_manifest_sha256": "c" * 64,
                "split_sha256": "d" * 64,
            },
        },
    )
    _write_json(
        run_dir / "artifact-index.json",
        {
            "schema_version": 1,
            "artifacts": {"checkpoint-best.pt": file_sha256(checkpoint)},
        },
    )
    return checkpoint


def test_plan_c_stage_identity_binds_protocol_vocabulary_course_stage_and_seed() -> None:
    common = {
        "base_config_sha256": "a" * 64,
        "protocol_sha256": "b" * 64,
        "vocabulary_sha256": "c" * 64,
        "course_id": "C1",
        "stage": "finetune",
        "train_manifest_sha256": "d" * 64,
        "validation_manifest_sha256": "e" * 64,
        "initialization_checkpoint_sha256": "f" * 64,
    }

    first = build_plan_c_stage_identity(**common, seed=20260821)
    second = build_plan_c_stage_identity(**common, seed=20260822)

    assert first.run_config_sha256 != second.run_config_sha256
    assert first.train_manifest_sha256 == "d" * 64
    assert first.validation_manifest_sha256 == "e" * 64
    assert first.split_sha256 == second.split_sha256


def test_manifest_batch_indices_are_reproducible_and_cover_before_repeating() -> None:
    batches = [
        deterministic_manifest_batch_indices(
            11, seed=20260821, batch_index=index, batch_size=4
        )
        for index in range(3)
    ]
    repeated = [
        deterministic_manifest_batch_indices(
            11, seed=20260821, batch_index=index, batch_size=4
        )
        for index in range(3)
    ]

    assert batches == repeated
    assert len(set((*batches[0], *batches[1]))) == 8
    assert len(set((*batches[0], *batches[1], *batches[2][:3]))) == 11
    assert batches[2][3] in range(11)


def test_manifest_batch_indices_change_with_seed() -> None:
    first = deterministic_manifest_batch_indices(
        100, seed=20260821, batch_index=0, batch_size=8
    )
    second = deterministic_manifest_batch_indices(
        100, seed=20260822, batch_index=0, batch_size=8
    )

    assert first != second


def test_skipped_c2_returns_without_loading_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol, vocabulary, config = _stage_files(tmp_path)

    def forbidden_loader(*args, **kwargs):
        raise AssertionError("skipped C2 must not load audio")

    monkeypatch.setattr(
        "museecho_ml.training.plan_c._load_manifest_batch", forbidden_loader
    )

    report = run_plan_c_stage(
        protocol,
        vocabulary,
        config,
        course_id="C2",
        stage="pretrain",
        seed=20260821,
        run_dir=tmp_path / "c2",
    )

    assert report == {
        "schema_version": 1,
        "plan_version": "plan-c-v1",
        "course_id": "C2",
        "status": "skipped",
        "reason_code": "score-supervision-not-approved",
    }
    assert not (tmp_path / "c2").exists()


def test_plan_c_cli_emits_structured_skip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    protocol, vocabulary, config = _stage_files(tmp_path)

    main(
        [
            "--protocol",
            str(protocol),
            "--vocabulary",
            str(vocabulary),
            "--base-config",
            str(config),
            "--course",
            "C2",
            "--stage",
            "pretrain",
            "--seed",
            "20260821",
            "--run-dir",
            str(tmp_path / "c2"),
        ]
    )

    assert json.loads(capsys.readouterr().out)["reason_code"] == (
        "score-supervision-not-approved"
    )


def test_c1_finetune_requires_pretrain_checkpoint_before_loading_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol, vocabulary, config = _stage_files(tmp_path)

    def forbidden_loader(*args, **kwargs):
        raise AssertionError("invalid stage must not load audio")

    monkeypatch.setattr(
        "museecho_ml.training.plan_c._load_manifest_batch", forbidden_loader
    )

    with pytest.raises(ValueError, match="initialization checkpoint"):
        run_plan_c_stage(
            protocol,
            vocabulary,
            config,
            course_id="C1",
            stage="finetune",
            seed=20260821,
            run_dir=tmp_path / "c1-finetune",
        )


def test_c0_rejects_initialization_checkpoint_before_loading_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol, vocabulary, config = _stage_files(tmp_path)
    checkpoint = tmp_path / "unexpected.pt"
    checkpoint.write_bytes(b"not-a-checkpoint")

    def forbidden_loader(*args, **kwargs):
        raise AssertionError("invalid stage must not load audio")

    monkeypatch.setattr(
        "museecho_ml.training.plan_c._load_manifest_batch", forbidden_loader
    )

    with pytest.raises(ValueError, match="C0.*initialization"):
        run_plan_c_stage(
            protocol,
            vocabulary,
            config,
            course_id="C0",
            stage="finetune",
            seed=20260821,
            run_dir=tmp_path / "c0",
            initialization_checkpoint_path=checkpoint,
        )


def test_c0_ready_stage_runs_all_frozen_seeds_with_streamed_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol, vocabulary, config = _stage_files(tmp_path)
    _write_real_stage_manifests(tmp_path, protocol)
    loaded_splits: list[str] = []
    trained_seeds: list[int] = []

    def fake_loader(manifest, *args, **kwargs):
        loaded_splits.append(manifest["split"])
        return ((manifest["split"],), (0.0,), object())

    def fake_training(config, train_batch, validation_batch, identity, run_dir, **kwargs):
        streamed = train_batch(0, 0)
        assert streamed is not None
        trained_seeds.append(config.seed)
        return {
            "schema_version": 1,
            "artifacts": {
                "checkpoint-best.pt": "e" * 64,
                "checkpoint-last.pt": "f" * 64,
            },
        }

    monkeypatch.setattr("museecho_ml.training.plan_c._load_manifest_batch", fake_loader)
    monkeypatch.setattr(
        "museecho_ml.training.plan_c.run_training_batches", fake_training
    )

    reports = [
        run_plan_c_stage(
            protocol,
            vocabulary,
            config,
            course_id="C0",
            stage="finetune",
            seed=seed,
            run_dir=tmp_path / f"c0-{seed}",
        )
        for seed in (20260821, 20260822, 20260823)
    ]

    assert trained_seeds == [20260821, 20260822, 20260823]
    assert {report["status"] for report in reports} == {"completed"}
    assert {report["seed"] for report in reports} == {
        20260821,
        20260822,
        20260823,
    }
    assert set(loaded_splits) == {"train", "validation"}


def test_operational_limit_does_not_freeze_stage_report_before_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol, vocabulary, config = _stage_files(tmp_path)
    _write_real_stage_manifests(tmp_path, protocol)
    stop_reasons = iter(("operational_limit", "max_epochs"))

    def fake_loader(manifest, *args, **kwargs):
        return ((manifest["split"],), (0.0,), object())

    def fake_training(config, train_batch, validation_batch, identity, run_dir, **kwargs):
        train_batch(0, 0)
        return {
            "schema_version": 1,
            "stop_reason": next(stop_reasons),
            "artifacts": {
                "checkpoint-best.pt": "e" * 64,
                "checkpoint-last.pt": "f" * 64,
            },
        }

    monkeypatch.setattr("museecho_ml.training.plan_c._load_manifest_batch", fake_loader)
    monkeypatch.setattr(
        "museecho_ml.training.plan_c.run_training_batches", fake_training
    )
    run_dir = tmp_path / "c0"

    interrupted = run_plan_c_stage(
        protocol,
        vocabulary,
        config,
        course_id="C0",
        stage="finetune",
        seed=20260821,
        run_dir=run_dir,
        epoch_limit=1,
    )
    completed = run_plan_c_stage(
        protocol,
        vocabulary,
        config,
        course_id="C0",
        stage="finetune",
        seed=20260821,
        run_dir=run_dir,
    )

    assert interrupted["status"] == "interrupted"
    assert completed["status"] == "completed"
    assert json.loads((run_dir / "stage-report.json").read_text(encoding="utf-8"))[
        "status"
    ] == "completed"


def test_c1_pretrain_requires_both_synthetic_manifests_before_loading_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol, vocabulary, config = _stage_files(tmp_path)
    paths = _write_synthetic_stage_manifests(tmp_path, protocol)

    def forbidden_loader(*args, **kwargs):
        raise AssertionError("incomplete pretrain stage must not load audio")

    monkeypatch.setattr(
        "museecho_ml.training.plan_c._load_manifest_batch", forbidden_loader
    )

    with pytest.raises(ValueError, match="required synthetic"):
        run_plan_c_stage(
            protocol,
            vocabulary,
            config,
            course_id="C1",
            stage="pretrain",
            seed=20260821,
            run_dir=tmp_path / "c1-pretrain",
            pretrain_manifest_paths={
                "idmt-smt-chord-sequences": paths["idmt-smt-chord-sequences"]
            },
        )


def test_c1_pretrain_rejects_mixed_roles_before_loading_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol, vocabulary, config = _stage_files(tmp_path)
    paths = _write_synthetic_stage_manifests(
        tmp_path, protocol, jazznet_role="real-gold"
    )

    def forbidden_loader(*args, **kwargs):
        raise AssertionError("mixed-role pretrain stage must not load audio")

    monkeypatch.setattr(
        "museecho_ml.training.plan_c._load_manifest_batch", forbidden_loader
    )

    with pytest.raises(ValueError, match="role-pure synthetic-supervised"):
        run_plan_c_stage(
            protocol,
            vocabulary,
            config,
            course_id="C1",
            stage="pretrain",
            seed=20260821,
            run_dir=tmp_path / "c1-pretrain",
            pretrain_manifest_paths=paths,
        )


def test_c1_pretrain_streams_role_pure_combined_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol, vocabulary, config_path = _stage_files(tmp_path)
    paths = _write_synthetic_stage_manifests(tmp_path, protocol)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["dataset_roots"].update(
        {
            "idmt-smt-chord-sequences": "idmt-audio",
            "jazznet": "jazznet-audio",
        }
    )
    _write_json(config_path, config)
    (tmp_path / "idmt-audio").mkdir()
    (tmp_path / "jazznet-audio").mkdir()
    loaded_dataset_sets: list[set[str]] = []

    def fake_loader(manifest, *args, **kwargs):
        loaded_dataset_sets.append(
            {track["dataset_id"] for track in manifest["tracks"]}
        )
        assert manifest["corpus_role"] == "synthetic-supervised"
        return (("synthetic",), (0.0,), object())

    def fake_training(config, train_batch, validation_batch, identity, run_dir, **kwargs):
        train_batch(0, 0)
        return {
            "schema_version": 1,
            "artifacts": {
                "checkpoint-best.pt": "e" * 64,
                "checkpoint-last.pt": "f" * 64,
            },
        }

    monkeypatch.setattr("museecho_ml.training.plan_c._load_manifest_batch", fake_loader)
    monkeypatch.setattr(
        "museecho_ml.training.plan_c.run_training_batches", fake_training
    )

    report = run_plan_c_stage(
        protocol,
        vocabulary,
        config_path,
        course_id="C1",
        stage="pretrain",
        seed=20260821,
        run_dir=tmp_path / "c1-pretrain",
        pretrain_manifest_paths=paths,
    )

    assert report["status"] == "completed"
    assert set.union(*loaded_dataset_sets) == {
        "idmt-smt-chord-sequences",
        "jazznet",
    }


def test_c1_finetune_binds_same_seed_pretrain_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol, vocabulary, config = _stage_files(tmp_path)
    _write_real_stage_manifests(tmp_path, protocol)
    checkpoint = _write_pretrain_checkpoint_provenance(
        tmp_path, protocol, vocabulary, config
    )
    received_initialization: list[tuple[Path, str]] = []

    def fake_loader(manifest, *args, **kwargs):
        return ((manifest["split"],), (0.0,), object())

    def fake_training(config, train_batch, validation_batch, identity, run_dir, **kwargs):
        received_initialization.append(kwargs["initialization_checkpoint"])
        train_batch(0, 0)
        return {
            "schema_version": 1,
            "artifacts": {
                "checkpoint-best.pt": "e" * 64,
                "checkpoint-last.pt": "f" * 64,
            },
        }

    monkeypatch.setattr("museecho_ml.training.plan_c._load_manifest_batch", fake_loader)
    monkeypatch.setattr(
        "museecho_ml.training.plan_c.run_training_batches", fake_training
    )

    report = run_plan_c_stage(
        protocol,
        vocabulary,
        config,
        course_id="C1",
        stage="finetune",
        seed=20260821,
        run_dir=tmp_path / "c1-finetune",
        initialization_checkpoint_path=checkpoint,
    )

    assert report["status"] == "completed"
    assert received_initialization == [(checkpoint.resolve(), file_sha256(checkpoint))]


def test_c1_finetune_rejects_different_seed_pretrain_before_loading_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol, vocabulary, config = _stage_files(tmp_path)
    _write_real_stage_manifests(tmp_path, protocol)
    checkpoint = _write_pretrain_checkpoint_provenance(
        tmp_path, protocol, vocabulary, config, seed=20260822
    )

    def forbidden_loader(*args, **kwargs):
        raise AssertionError("wrong-seed checkpoint must fail before audio")

    monkeypatch.setattr(
        "museecho_ml.training.plan_c._load_manifest_batch", forbidden_loader
    )

    with pytest.raises(ValueError, match="same-seed C1 pretrain"):
        run_plan_c_stage(
            protocol,
            vocabulary,
            config,
            course_id="C1",
            stage="finetune",
            seed=20260821,
            run_dir=tmp_path / "c1-finetune",
            initialization_checkpoint_path=checkpoint,
        )


def test_resume_identity_mismatch_fails_before_loading_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol, vocabulary, config = _stage_files(tmp_path)
    _write_real_stage_manifests(tmp_path, protocol)
    resume = tmp_path / "checkpoint-last.pt"
    torch.save(
        {
            "schema_version": 2,
            "checkpoint_version": "checkpoint-v2",
            "identity": {
                "run_config_sha256": "0" * 64,
                "train_manifest_sha256": "0" * 64,
                "validation_manifest_sha256": "0" * 64,
                "split_sha256": "0" * 64,
            },
        },
        resume,
    )

    def forbidden_loader(*args, **kwargs):
        raise AssertionError("identity mismatch must fail before audio")

    monkeypatch.setattr(
        "museecho_ml.training.plan_c._load_manifest_batch", forbidden_loader
    )

    with pytest.raises(ValueError, match="resume.*identity"):
        run_plan_c_stage(
            protocol,
            vocabulary,
            config,
            course_id="C0",
            stage="finetune",
            seed=20260821,
            run_dir=tmp_path / "c0",
            resume_path=resume,
        )


def test_score_supervision_cannot_enter_finetune_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol, vocabulary, config = _stage_files(tmp_path)
    _write_real_stage_manifests(tmp_path, protocol)
    validation_path = tmp_path / "validation.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    validation["corpus_role"] = "real-score-supervised"
    _write_json(validation_path, validation)
    frozen = json.loads(protocol.read_text(encoding="utf-8"))
    frozen.pop("protocol_sha256")
    frozen["real_splits"]["validation"]["manifest_sha256"] = canonical_sha256(
        validation
    )
    frozen["protocol_sha256"] = canonical_sha256(frozen)
    _write_json(protocol, frozen)

    def forbidden_loader(*args, **kwargs):
        raise AssertionError("score validation must fail before audio")

    monkeypatch.setattr(
        "museecho_ml.training.plan_c._load_manifest_batch", forbidden_loader
    )

    with pytest.raises(ValueError, match="role-pure real-gold"):
        run_plan_c_stage(
            protocol,
            vocabulary,
            config,
            course_id="C0",
            stage="finetune",
            seed=20260821,
            run_dir=tmp_path / "c0",
        )


def test_ready_c2_pretrain_accepts_only_score_supervision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol, vocabulary, config_path = _stage_files(tmp_path)
    score_manifest = {
        "schema_version": 1,
        "dataset_id": "maestro-score",
        "corpus_role": "real-score-supervised",
        "tracks": [
            {
                "track_id": "maestro-score:track-001",
                "audio_path": "track.wav",
                "intervals": [
                    {
                        "start_seconds": 0.0,
                        "end_seconds": 2.0,
                        "root": "C",
                        "quality": "maj",
                        "bass": "1",
                        "mapping_reason": None,
                    }
                ],
            }
        ],
    }
    score_path = _write_json(tmp_path / "maestro-score.json", score_manifest)
    frozen = json.loads(protocol.read_text(encoding="utf-8"))
    frozen.pop("protocol_sha256")
    frozen["courses"]["C2"] = {
        "status": "ready",
        "pretrain": {
            "dataset_id": "maestro-score",
            "corpus_role": "real-score-supervised",
            "manifest_sha256": canonical_sha256(score_manifest),
        },
    }
    frozen["protocol_sha256"] = canonical_sha256(frozen)
    _write_json(protocol, frozen)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["dataset_roots"]["maestro-score"] = "score-audio"
    _write_json(config_path, config)
    (tmp_path / "score-audio").mkdir()
    loaded_roles: list[str] = []

    def fake_loader(manifest, *args, **kwargs):
        loaded_roles.append(manifest["corpus_role"])
        return (("score",), (0.0,), object())

    def fake_training(config, train_batch, validation_batch, identity, run_dir, **kwargs):
        train_batch(0, 0)
        return {
            "schema_version": 1,
            "artifacts": {
                "checkpoint-best.pt": "e" * 64,
                "checkpoint-last.pt": "f" * 64,
            },
        }

    monkeypatch.setattr("museecho_ml.training.plan_c._load_manifest_batch", fake_loader)
    monkeypatch.setattr(
        "museecho_ml.training.plan_c.run_training_batches", fake_training
    )

    report = run_plan_c_stage(
        protocol,
        vocabulary,
        config_path,
        course_id="C2",
        stage="pretrain",
        seed=20260821,
        run_dir=tmp_path / "c2-pretrain",
        pretrain_manifest_paths={"maestro-score": score_path},
    )

    assert report["status"] == "completed"
    assert set(loaded_roles) == {"real-score-supervised"}
