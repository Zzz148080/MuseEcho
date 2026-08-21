from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from museecho_ml.artifacts import (
    canonical_sha256,
    write_immutable_json,
)
from museecho_ml.data.course import CorpusRole
from museecho_ml.data.registry import DatasetRegistry
from museecho_ml.vocabulary import ChordVocabulary

_SPLITS = ("train", "calibration", "validation", "test")
_COURSES = ("C0", "C1", "C2")
_CONFIG_FIELDS = {
    "schema_version",
    "plan_version",
    "seeds",
    "minimum_quality_train_groups",
    "g1b_production_scale_exclusions",
    "bootstrap",
    "courses",
    "required_synthetic_datasets",
    "selection_metrics",
    "course_tie_order",
}


def freeze_plan_c_protocol(
    config: Mapping[str, Any],
    *,
    g1_report: Mapping[str, Any],
    vocabulary_report: Mapping[str, Any],
    real_manifests: Mapping[str, Path],
    synthetic_manifests: Sequence[Path],
    registry: DatasetRegistry,
    historical_route_report: Mapping[str, Any],
    score_manifest: Path | None = None,
    score_feasibility: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    frozen_config = _validated_config(config)
    if not isinstance(g1_report, Mapping) or not isinstance(
        g1_report.get("g1a"), Mapping
    ):
        raise ValueError("Plan C G1 report is invalid")
    if g1_report["g1a"].get("status") != "passed":
        raise PermissionError("Plan C requires G1a PASS")
    vocabulary = ChordVocabulary.from_dict(vocabulary_report)
    if not vocabulary.quality_labels:
        raise ValueError("Plan C vocabulary cannot be empty")

    real = _bind_real_splits(real_manifests, registry)
    if vocabulary_report.get("source_split_sha256") != real["train"]["split_sha256"]:
        raise ValueError("Plan C vocabulary and real train split do not match")
    synthetic = _bind_required_synthetic(
        synthetic_manifests,
        frozen_config["required_synthetic_datasets"],
        registry,
    )
    historical = _validated_historical_route(
        historical_route_report, frozen_config["required_synthetic_datasets"]
    )
    c2 = _freeze_c2_or_skip(
        score_manifest=score_manifest,
        score_feasibility=score_feasibility,
        registry=registry,
    )
    body = {
        "schema_version": 1,
        "plan_version": "plan-c-v1",
        "config_sha256": canonical_sha256(config),
        "g1_report_sha256": canonical_sha256(g1_report),
        "g1a_status": "passed",
        "vocabulary_sha256": vocabulary_report["vocabulary_sha256"],
        "g1b_production_scale_exclusions": frozen_config[
            "g1b_production_scale_exclusions"
        ],
        "historical_route": historical["route"],
        "historical_route_report_sha256": canonical_sha256(historical_route_report),
        "historical_usable_synthetic_hours": historical["usable_synthetic_hours"],
        "seeds": frozen_config["seeds"],
        "real_splits": real,
        "courses": {
            "C0": {"status": "ready", "pretrain": None},
            "C1": {"status": "ready", "pretrain": synthetic},
            "C2": c2,
        },
        "bootstrap": frozen_config["bootstrap"],
        "selection_metrics": frozen_config["selection_metrics"],
        "course_tie_order": frozen_config["course_tie_order"],
    }
    return {**body, "protocol_sha256": canonical_sha256(body)}


def write_frozen_protocol(path: Path, protocol: Mapping[str, Any]) -> None:
    body = dict(protocol)
    embedded_hash = body.pop("protocol_sha256", None)
    if not isinstance(embedded_hash, str) or canonical_sha256(body) != embedded_hash:
        raise ValueError("Plan C protocol SHA-256 does not match")
    write_immutable_json(path, protocol)


def _validated_config(config: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(config, Mapping) or set(config) != _CONFIG_FIELDS:
        raise ValueError("Plan C config fields are invalid")
    if config.get("schema_version") != 1 or config.get("plan_version") != "plan-c-v1":
        raise ValueError("Plan C config version is unsupported")
    seeds = config.get("seeds")
    if (
        not isinstance(seeds, list)
        or sorted(seeds) != [20260821, 20260822, 20260823]
        or any(type(seed) is not int for seed in seeds)
    ):
        raise ValueError("Plan C seeds do not match the frozen protocol")
    if config.get("minimum_quality_train_groups") != 20:
        raise ValueError("Plan C quality group threshold must be 20")
    courses = config.get("courses")
    tie_order = config.get("course_tie_order")
    if courses != list(_COURSES) or tie_order != list(_COURSES):
        raise ValueError("Plan C course order is invalid")
    required = config.get("required_synthetic_datasets")
    if not isinstance(required, list) or sorted(required) != [
        "idmt-smt-chord-sequences",
        "jazznet",
    ]:
        raise ValueError("Plan C required synthetic datasets are invalid")
    exclusions = config.get("g1b_production_scale_exclusions")
    if not isinstance(exclusions, dict) or exclusions != {
        "guitarset": "lead-sheet-domain-augmentation-not-independent-musical-works"
    }:
        raise ValueError("Plan C G1b exclusions are invalid")
    bootstrap = config.get("bootstrap")
    if bootstrap != {
        "resamples": 10000,
        "seed": 20260821,
        "unit": "cover_group_id",
    }:
        raise ValueError("Plan C bootstrap settings are invalid")
    metrics = config.get("selection_metrics")
    if metrics != [
        "exact_vocabulary_wcsr",
        "public_quality_macro_f1",
        "published_known_precision",
        "coverage",
        "five_minute_cpu_wall_seconds",
    ]:
        raise ValueError("Plan C selection metrics are invalid")
    value = dict(config)
    value["seeds"] = sorted(seeds)
    value["required_synthetic_datasets"] = sorted(required)
    return value


def _bind_real_splits(
    paths: Mapping[str, Path], registry: DatasetRegistry
) -> dict[str, dict[str, Any]]:
    if set(paths) != set(_SPLITS):
        raise ValueError("Plan C requires exactly four real manifests")
    bindings: dict[str, dict[str, Any]] = {}
    split_hash: str | None = None
    for split in _SPLITS:
        manifest = _read_json(paths[split], f"real {split} manifest")
        if manifest.get("split") != split:
            raise ValueError(f"Plan C real {split} manifest identity does not match")
        _require_role_pure(manifest, CorpusRole.REAL_GOLD)
        current_hash = manifest.get("split_sha256")
        if not isinstance(current_hash, str) or len(current_hash) != 64:
            raise ValueError(f"Plan C real {split} split SHA-256 is invalid")
        if split_hash is None:
            split_hash = current_hash
        elif split_hash != current_hash:
            raise ValueError("Plan C real manifests use different frozen splits")
        dataset_ids = _manifest_track_dataset_ids(manifest)
        for dataset_id in dataset_ids:
            registry.require_training_approval(dataset_id)
        bindings[split] = {
            "corpus_role": CorpusRole.REAL_GOLD.value,
            "dataset_ids": list(dataset_ids),
            "split_sha256": current_hash,
            "manifest_sha256": canonical_sha256(manifest),
        }
    return bindings


def _bind_required_synthetic(
    paths: Sequence[Path], required: Sequence[str], registry: DatasetRegistry
) -> list[dict[str, Any]]:
    bindings: dict[str, dict[str, Any]] = {}
    for path in paths:
        manifest = _read_json(path, "synthetic manifest")
        _require_role_pure(manifest, CorpusRole.SYNTHETIC_SUPERVISED)
        dataset_id = manifest.get("dataset_id")
        if not isinstance(dataset_id, str) or not dataset_id.strip():
            raise ValueError("Plan C synthetic manifest dataset_id is invalid")
        if dataset_id in bindings:
            raise ValueError("Plan C synthetic manifest dataset_id is duplicated")
        registry.require_training_approval(dataset_id)
        bindings[dataset_id] = {
            "dataset_id": dataset_id,
            "corpus_role": CorpusRole.SYNTHETIC_SUPERVISED.value,
            "manifest_sha256": canonical_sha256(manifest),
        }
    if set(bindings) != set(required):
        raise ValueError("Plan C required synthetic manifests are incomplete")
    return [bindings[dataset_id] for dataset_id in sorted(bindings)]


def _freeze_c2_or_skip(
    *,
    score_manifest: Path | None,
    score_feasibility: Mapping[str, Any] | None,
    registry: DatasetRegistry,
) -> dict[str, Any]:
    if (
        not isinstance(score_feasibility, Mapping)
        or score_feasibility.get("status") != "passed"
        or score_manifest is None
    ):
        return {
            "status": "skipped",
            "reason_code": "score-supervision-not-approved",
        }
    feasibility_sha256 = score_feasibility.get("feasibility_sha256")
    if not isinstance(feasibility_sha256, str) or len(feasibility_sha256) != 64:
        raise ValueError("Plan C score feasibility SHA-256 is invalid")
    manifest = _read_json(score_manifest, "score manifest")
    _require_role_pure(manifest, CorpusRole.REAL_SCORE_SUPERVISED)
    dataset_id = manifest.get("dataset_id")
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise ValueError("Plan C score manifest dataset_id is invalid")
    try:
        registry.require_training_approval(dataset_id)
    except (KeyError, PermissionError):
        return {
            "status": "skipped",
            "reason_code": "score-supervision-not-approved",
        }
    return {
        "status": "ready",
        "feasibility_sha256": feasibility_sha256,
        "pretrain": {
            "dataset_id": dataset_id,
            "corpus_role": CorpusRole.REAL_SCORE_SUPERVISED.value,
            "manifest_sha256": canonical_sha256(manifest),
        },
    }


def _validated_historical_route(
    value: Mapping[str, Any], required_synthetic: Sequence[str]
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("schema_version") != 1:
        raise ValueError("Plan C historical route report is invalid")
    if value.get("route") != "A":
        raise ValueError("Plan C historical route must remain A")
    hours = value.get("usable_synthetic_hours")
    if not isinstance(hours, (int, float)) or isinstance(hours, bool) or hours != 41.487981:
        raise ValueError("Plan C historical synthetic hours do not match")
    included = value.get("included_datasets")
    if not isinstance(included, list) or sorted(included) != sorted(required_synthetic):
        raise ValueError("Plan C historical route datasets do not match")
    return {"route": "A", "usable_synthetic_hours": float(hours)}


def _require_role_pure(manifest: Mapping[str, Any], role: CorpusRole) -> None:
    if manifest.get("corpus_role") != role.value:
        raise ValueError(f"Plan C manifest must be role-pure {role.value}")
    tracks = manifest.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        raise ValueError("Plan C role-pure manifest must contain tracks")
    for track in tracks:
        if not isinstance(track, Mapping):
            raise ValueError("Plan C role-pure manifest tracks must be objects")
        track_role = track.get("corpus_role")
        if track_role is not None and track_role != role.value:
            raise ValueError(f"Plan C manifest must be role-pure {role.value}")


def _manifest_track_dataset_ids(manifest: Mapping[str, Any]) -> tuple[str, ...]:
    dataset_ids: set[str] = set()
    for track in manifest["tracks"]:
        dataset_id = track.get("dataset_id")
        if not isinstance(dataset_id, str) or not dataset_id.strip():
            raise ValueError("Plan C manifest track dataset_id is invalid")
        dataset_ids.add(dataset_id)
    return tuple(sorted(dataset_ids))


def _read_json(path: Path, name: str) -> dict[str, Any]:
    try:
        value = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Plan C {name} is unreadable strict JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"Plan C {name} must contain an object")
    return value
