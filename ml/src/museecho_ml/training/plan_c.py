from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

import torch

from museecho_ml.artifacts import canonical_sha256, file_sha256, write_immutable_json
from museecho_ml.training.checkpoint import CheckpointIdentity
from museecho_ml.training.train import (
    _config_base,
    _load_manifest_batch,
    _resolve_relative,
    load_train_config,
    run_training_batches,
)
from museecho_ml.vocabulary import ChordVocabulary

_ALLOWED_STAGES = {
    "C0": ("finetune",),
    "C1": ("pretrain", "finetune"),
    "C2": ("pretrain", "finetune"),
}


def build_plan_c_stage_identity(
    *,
    base_config_sha256: str,
    protocol_sha256: str,
    vocabulary_sha256: str,
    course_id: str,
    stage: str,
    seed: int,
    train_manifest_sha256: str,
    validation_manifest_sha256: str,
    initialization_checkpoint_sha256: str | None,
) -> CheckpointIdentity:
    stage_inputs = {
        "base_config_sha256": base_config_sha256,
        "protocol_sha256": protocol_sha256,
        "vocabulary_sha256": vocabulary_sha256,
        "course_id": course_id,
        "stage": stage,
        "seed": seed,
        "train_manifest_sha256": train_manifest_sha256,
        "validation_manifest_sha256": validation_manifest_sha256,
        "initialization_checkpoint_sha256": initialization_checkpoint_sha256,
    }
    split_identity = {
        "train_manifest_sha256": train_manifest_sha256,
        "validation_manifest_sha256": validation_manifest_sha256,
    }
    return CheckpointIdentity(
        run_config_sha256=canonical_sha256(stage_inputs),
        train_manifest_sha256=train_manifest_sha256,
        validation_manifest_sha256=validation_manifest_sha256,
        split_sha256=canonical_sha256(split_identity),
    )


def deterministic_manifest_batch_indices(
    track_count: int,
    *,
    seed: int,
    batch_index: int,
    batch_size: int,
) -> tuple[int, ...]:
    if type(track_count) is not int or track_count <= 0:
        raise ValueError("manifest track count must be a positive integer")
    if type(seed) is not int or seed < 0:
        raise ValueError("manifest batch seed must be a non-negative integer")
    if type(batch_index) is not int or batch_index < 0:
        raise ValueError("manifest batch index must be a non-negative integer")
    if type(batch_size) is not int or batch_size <= 0:
        raise ValueError("manifest batch size must be a positive integer")

    start = batch_index * batch_size
    cycle, offset = divmod(start, track_count)
    selected: list[int] = []
    while len(selected) < batch_size:
        permutation = _manifest_permutation(track_count, seed, cycle)
        take = min(batch_size - len(selected), track_count - offset)
        selected.extend(permutation[offset : offset + take])
        cycle += 1
        offset = 0
    return tuple(selected)


def run_plan_c_stage(
    protocol_path: Path,
    vocabulary_path: Path,
    base_config_path: Path,
    *,
    course_id: str,
    stage: str,
    seed: int,
    run_dir: Path,
    pretrain_manifest_paths: dict[str, Path] | None = None,
    initialization_checkpoint_path: Path | None = None,
    resume_path: Path | None = None,
    epoch_limit: int | None = None,
) -> dict[str, Any]:
    protocol = _read_frozen_json(
        protocol_path, embedded_hash_field="protocol_sha256", name="protocol"
    )
    vocabulary_payload = _read_frozen_json(
        vocabulary_path,
        embedded_hash_field="vocabulary_sha256",
        name="vocabulary",
    )
    vocabulary = ChordVocabulary.from_dict(vocabulary_payload)
    config = load_train_config(base_config_path.resolve(strict=True))
    if config.purpose != "formal":
        raise ValueError("Plan C requires a formal training config")
    if protocol.get("g1a_status") != "passed":
        raise PermissionError("Plan C stage requires G1a PASS")
    if protocol.get("vocabulary_sha256") != vocabulary_payload.get(
        "vocabulary_sha256"
    ):
        raise ValueError("Plan C protocol and vocabulary do not match")
    if course_id not in _ALLOWED_STAGES or stage not in _ALLOWED_STAGES[course_id]:
        raise ValueError("Plan C course and stage combination is unsupported")
    seeds = protocol.get("seeds")
    if not isinstance(seeds, list) or seed not in seeds:
        raise ValueError("Plan C seed is outside the frozen protocol")
    courses = protocol.get("courses")
    if not isinstance(courses, dict) or not isinstance(courses.get(course_id), dict):
        raise ValueError("Plan C course is missing from the frozen protocol")
    course = courses[course_id]
    if course.get("status") == "skipped":
        return {
            "schema_version": 1,
            "plan_version": "plan-c-v1",
            "course_id": course_id,
            "status": "skipped",
            "reason_code": course.get("reason_code"),
        }
    if course.get("status") != "ready":
        raise ValueError("Plan C course status is invalid")
    if course_id == "C0" and initialization_checkpoint_path is not None:
        raise ValueError("C0 does not accept an initialization checkpoint")
    if stage == "pretrain" and initialization_checkpoint_path is not None:
        raise ValueError("Plan C pretrain does not accept an initialization checkpoint")
    if course_id in {"C1", "C2"} and stage == "finetune":
        if initialization_checkpoint_path is None:
            raise ValueError("Plan C finetune requires an initialization checkpoint")
    _validate_model_vocabulary(config, vocabulary)
    source_config_path = base_config_path.resolve(strict=True)
    base = _config_base(source_config_path)
    initialization: tuple[Path, str] | None = None
    if initialization_checkpoint_path is not None:
        initialization = _verify_initialization_provenance(
            initialization_checkpoint_path,
            course_id=course_id,
            seed=seed,
            base_config_sha256=file_sha256(source_config_path),
            protocol_sha256=protocol["protocol_sha256"],
            vocabulary_sha256=vocabulary_payload["vocabulary_sha256"],
        )
    if stage == "pretrain":
        expected_pretrain_role = (
            "synthetic-supervised"
            if course_id == "C1"
            else "real-score-supervised"
        )
        train_manifest, train_manifest_sha256 = _combined_pretrain_manifest(
            course,
            pretrain_manifest_paths,
            expected_role=expected_pretrain_role,
        )
        validation_manifest = train_manifest
        validation_manifest_sha256 = canonical_sha256(
            {
                "pretrain_manifest_sha256": train_manifest_sha256,
                "selection": "deterministic-pretrain-audit-v1",
            }
        )
    else:
        train_binding, validation_binding = _real_stage_bindings(protocol)
        train_path = _resolve_relative(base, config.train_manifest, must_exist=True)
        validation_path = _resolve_relative(
            base, config.validation_manifest, must_exist=True
        )
        train_manifest = _read_bound_manifest(
            train_path,
            expected_role="real-gold",
            expected_split="train",
            expected_sha256=train_binding["manifest_sha256"],
        )
        validation_manifest = _read_bound_manifest(
            validation_path,
            expected_role="real-gold",
            expected_split="validation",
            expected_sha256=validation_binding["manifest_sha256"],
        )
        train_manifest_sha256 = train_binding["manifest_sha256"]
        validation_manifest_sha256 = validation_binding["manifest_sha256"]
    dataset_ids = {
        str(track["dataset_id"]) for track in train_manifest["tracks"]
    } | {str(track["dataset_id"]) for track in validation_manifest["tracks"]}
    roots = {
        dataset_id: _resolve_relative(
            base, _dataset_root(config.dataset_roots, dataset_id), must_exist=True
        )
        for dataset_id in sorted(dataset_ids)
    }
    batch_size = config.track_limit
    if type(batch_size) is not int or batch_size <= 0:
        raise ValueError("Plan C requires a positive track_limit batch size")
    stage_config = replace(config, seed=seed)
    identity = build_plan_c_stage_identity(
        base_config_sha256=file_sha256(source_config_path),
        protocol_sha256=protocol["protocol_sha256"],
        vocabulary_sha256=vocabulary_payload["vocabulary_sha256"],
        course_id=course_id,
        stage=stage,
        seed=seed,
        train_manifest_sha256=train_manifest_sha256,
        validation_manifest_sha256=validation_manifest_sha256,
        initialization_checkpoint_sha256=(
            None if initialization is None else initialization[1]
        ),
    )
    if resume_path is not None:
        _require_resume_identity(resume_path, identity)

    def train_batch_at(epoch: int, step: int):
        indices = deterministic_manifest_batch_indices(
            len(train_manifest["tracks"]),
            seed=seed,
            batch_index=epoch * stage_config.steps_per_epoch + step,
            batch_size=batch_size,
        )
        return _load_manifest_batch(
            train_manifest,
            roots,
            limit=None,
            track_indices=indices,
            segment_seconds=stage_config.segment_seconds,
            segment_start_policy=stage_config.segment_start_policy,
            feature_config=stage_config.feature_config,
            vocabulary=vocabulary,
        )[2]

    validation_indices = deterministic_manifest_batch_indices(
        len(validation_manifest["tracks"]),
        seed=20260821,
        batch_index=0,
        batch_size=batch_size,
    )
    validation_batch = _load_manifest_batch(
        validation_manifest,
        roots,
        limit=None,
        track_indices=validation_indices,
        segment_seconds=stage_config.segment_seconds,
        segment_start_policy=stage_config.segment_start_policy,
        feature_config=stage_config.feature_config,
        vocabulary=vocabulary,
    )[2]
    destination = run_dir.resolve(strict=False)
    stage_identity = {
        "schema_version": 1,
        "plan_version": "plan-c-v1",
        "course_id": course_id,
        "stage": stage,
        "seed": seed,
        "base_config_sha256": file_sha256(source_config_path),
        "protocol_sha256": protocol["protocol_sha256"],
        "vocabulary_sha256": vocabulary_payload["vocabulary_sha256"],
        "initialization_checkpoint_sha256": (
            None if initialization is None else initialization[1]
        ),
        "checkpoint_identity": asdict(identity),
    }
    write_immutable_json(destination / "stage-identity.json", stage_identity)
    training_report = run_training_batches(
        stage_config,
        train_batch_at,
        validation_batch,
        identity,
        destination,
        vocabulary=vocabulary,
        initialization_checkpoint=(
            initialization if resume_path is None else None
        ),
        resume_path=resume_path,
        epoch_limit=epoch_limit,
    )
    stage_status = (
        "interrupted"
        if training_report.get("stop_reason") == "operational_limit"
        else "completed"
    )
    report = {
        **training_report,
        "status": stage_status,
        "plan_version": "plan-c-v1",
        "course_id": course_id,
        "stage": stage,
        "seed": seed,
        "stage_identity_sha256": canonical_sha256(stage_identity),
    }
    if stage_status == "completed":
        write_immutable_json(destination / "stage-report.json", report)
    return report


@lru_cache(maxsize=64)
def _manifest_permutation(track_count: int, seed: int, cycle: int) -> tuple[int, ...]:
    def key(index: int) -> bytes:
        return hashlib.sha256(f"{seed}:{cycle}:{index}".encode("ascii")).digest()

    return tuple(sorted(range(track_count), key=key))


def _read_frozen_json(
    path: Path, *, embedded_hash_field: str, name: str
) -> dict[str, Any]:
    try:
        payload = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Plan C {name} is unreadable strict JSON") from error
    if not isinstance(payload, dict):
        raise ValueError(f"Plan C {name} must contain an object")
    body = dict(payload)
    embedded_hash = body.pop(embedded_hash_field, None)
    if not isinstance(embedded_hash, str) or canonical_sha256(body) != embedded_hash:
        raise ValueError(f"Plan C {name} SHA-256 does not match")
    return payload


def _real_stage_bindings(
    protocol: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    real = protocol.get("real_splits")
    if not isinstance(real, dict):
        raise ValueError("Plan C real split bindings are invalid")
    train = real.get("train")
    validation = real.get("validation")
    if not isinstance(train, dict) or not isinstance(validation, dict):
        raise ValueError("Plan C real train and validation bindings are required")
    if train.get("corpus_role") != "real-gold" or validation.get(
        "corpus_role"
    ) != "real-gold":
        raise ValueError("Plan C real stage bindings must contain real-gold")
    if train.get("split_sha256") != validation.get("split_sha256"):
        raise ValueError("Plan C real stage bindings use different frozen splits")
    return train, validation


def _read_bound_manifest(
    path: Path,
    *,
    expected_role: str,
    expected_split: str | None,
    expected_sha256: str,
) -> dict[str, Any]:
    try:
        manifest = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Plan C stage manifest is unreadable strict JSON") from error
    if not isinstance(manifest, dict):
        raise ValueError("Plan C stage manifest must contain an object")
    if canonical_sha256(manifest) != expected_sha256:
        raise ValueError("Plan C stage manifest SHA-256 does not match protocol")
    if manifest.get("corpus_role") != expected_role:
        raise ValueError(f"Plan C stage manifest must be role-pure {expected_role}")
    if expected_split is not None and manifest.get("split") != expected_split:
        raise PermissionError("Plan C stage manifest split is not authorized")
    tracks = manifest.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        raise ValueError("Plan C stage manifest must contain tracks")
    for track in tracks:
        if not isinstance(track, dict):
            raise ValueError("Plan C stage manifest track must be an object")
        track_role = track.get("corpus_role")
        if track_role is not None and track_role != expected_role:
            raise ValueError(f"Plan C stage manifest must be role-pure {expected_role}")
    return manifest


def _combined_pretrain_manifest(
    course: dict[str, Any],
    paths: dict[str, Path] | None,
    *,
    expected_role: str,
) -> tuple[dict[str, Any], str]:
    bindings = course.get("pretrain")
    if isinstance(bindings, dict):
        bindings = [bindings]
    if not isinstance(bindings, list) or not bindings:
        raise ValueError("Plan C pretrain bindings are invalid")
    by_dataset: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        if not isinstance(binding, dict):
            raise ValueError("Plan C pretrain binding must be an object")
        dataset_id = binding.get("dataset_id")
        if not isinstance(dataset_id, str) or not dataset_id:
            raise ValueError("Plan C pretrain dataset ID is invalid")
        if binding.get("corpus_role") != expected_role:
            raise ValueError(f"Plan C pretrain binding must be {expected_role}")
        by_dataset[dataset_id] = binding
    if paths is None or set(paths) != set(by_dataset):
        raise ValueError("Plan C required synthetic manifests are incomplete")
    tracks: list[dict[str, Any]] = []
    for dataset_id in sorted(by_dataset):
        binding = by_dataset[dataset_id]
        manifest = _read_bound_manifest(
            paths[dataset_id],
            expected_role=expected_role,
            expected_split=None,
            expected_sha256=binding["manifest_sha256"],
        )
        if manifest.get("dataset_id") != dataset_id:
            raise ValueError("Plan C pretrain manifest dataset ID does not match")
        for track in manifest["tracks"]:
            track_dataset_id = track.get("dataset_id")
            if track_dataset_id is not None and track_dataset_id != dataset_id:
                raise ValueError("Plan C pretrain track dataset ID does not match")
            tracks.append({**track, "dataset_id": dataset_id})
    logical_identity = canonical_sha256(
        {"pretrain": [by_dataset[key] for key in sorted(by_dataset)]}
    )
    return {
        "schema_version": 1,
        "corpus_role": expected_role,
        "tracks": tracks,
    }, logical_identity


def _dataset_root(roots: dict[str, str], dataset_id: str) -> str:
    value = roots.get(dataset_id)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Plan C training config has no dataset root for {dataset_id}")
    return value


def _validate_model_vocabulary(config: Any, vocabulary: ChordVocabulary) -> None:
    dimensions = (
        (config.model_config.root_classes, len(vocabulary.root_labels), "root"),
        (
            config.model_config.quality_classes,
            len(vocabulary.quality_labels),
            "quality",
        ),
        (config.model_config.bass_classes, len(vocabulary.bass_labels), "bass"),
    )
    for configured, frozen, head in dimensions:
        if configured != frozen:
            raise ValueError(f"model {head} classes do not match frozen vocabulary")


def _verify_initialization_provenance(
    path: Path,
    *,
    course_id: str,
    seed: int,
    base_config_sha256: str,
    protocol_sha256: str,
    vocabulary_sha256: str,
) -> tuple[Path, str]:
    source = path.resolve(strict=True)
    try:
        stage_identity = json.loads(
            (source.parent / "stage-identity.json").read_text(encoding="utf-8")
        )
        artifact_index = json.loads(
            (source.parent / "artifact-index.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("initialization checkpoint provenance is unreadable") from error
    expected = {
        "course_id": course_id,
        "stage": "pretrain",
        "seed": seed,
        "base_config_sha256": base_config_sha256,
        "protocol_sha256": protocol_sha256,
        "vocabulary_sha256": vocabulary_sha256,
    }
    if not isinstance(stage_identity, dict) or any(
        stage_identity.get(field) != value for field, value in expected.items()
    ):
        raise ValueError(
            f"initialization checkpoint is not same-seed {course_id} pretrain"
        )
    checkpoint_sha256 = file_sha256(source)
    if (
        not isinstance(artifact_index, dict)
        or not isinstance(artifact_index.get("artifacts"), dict)
        or artifact_index["artifacts"].get(source.name) != checkpoint_sha256
    ):
        raise ValueError("initialization checkpoint artifact hash does not match")
    return source, checkpoint_sha256


def _require_resume_identity(path: Path, identity: CheckpointIdentity) -> None:
    try:
        payload = torch.load(
            path.resolve(strict=True), map_location="cpu", weights_only=False
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise ValueError("Plan C resume checkpoint is unreadable") from error
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 2
        or payload.get("checkpoint_version") != "checkpoint-v2"
        or payload.get("identity") != asdict(identity)
    ):
        raise ValueError("Plan C resume checkpoint identity does not match stage")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run one identity-bound Plan C training stage"
    )
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--vocabulary", type=Path, required=True)
    parser.add_argument("--base-config", type=Path, required=True)
    parser.add_argument("--course", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--pretrain-manifest", action="append", default=[])
    parser.add_argument("--initial-checkpoint", type=Path)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--epoch-limit", type=int)
    args = parser.parse_args(argv)
    pretrain_paths = _parse_manifest_arguments(args.pretrain_manifest)
    report = run_plan_c_stage(
        args.protocol,
        args.vocabulary,
        args.base_config,
        course_id=args.course,
        stage=args.stage,
        seed=args.seed,
        run_dir=args.run_dir,
        pretrain_manifest_paths=pretrain_paths or None,
        initialization_checkpoint_path=args.initial_checkpoint,
        resume_path=args.resume,
        epoch_limit=args.epoch_limit,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


def _parse_manifest_arguments(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        dataset_id, separator, raw_path = value.partition("=")
        if not separator or not dataset_id or not raw_path or dataset_id in result:
            raise ValueError(
                "pretrain manifests must be unique DATASET_ID=PATH assignments"
            )
        result[dataset_id] = Path(raw_path)
    return result


if __name__ == "__main__":
    main()
