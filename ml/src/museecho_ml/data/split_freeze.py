from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from museecho_ml.data.fingerprint import find_near_duplicates, fingerprint_wav
from museecho_ml.data.split import (
    SplitAuditRequired,
    SplitPolicy,
    freeze_real_gold_splits,
)

_SPLIT_NAMES = ("train", "calibration", "validation", "test")


def freeze_split_files(
    manifest_paths: list[Path],
    *,
    config_path: Path,
    output_dir: Path,
    audit_output: Path,
    source_root: Path | None = None,
    dataset_roots: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    """Freeze four local manifests and a path-free public audit without overwriting drift."""

    config = _read_json(config_path)
    policy, seed, policy_version = _load_policy(config)
    manifests = [_read_json(path) for path in manifest_paths]
    if source_root is not None and dataset_roots is not None:
        raise ValueError("use either source_root or dataset_roots, not both")
    fingerprint_audit = (
        _audit_audio_fingerprints(
            manifests,
            source_root=source_root,
            dataset_roots=dataset_roots,
            threshold=policy.near_duplicate_threshold,
        )
        if source_root is not None or dataset_roots is not None
        else {"status": "not-run"}
    )
    frozen = freeze_real_gold_splits(manifests, policy, seed=seed)
    split_manifest_hashes = {
        name: _sha256(frozen["manifests"][name]) for name in _SPLIT_NAMES
    }
    audit = dict(frozen["audit"])
    audit.update(
        {
            "policy_version": policy_version,
            "split_manifest_sha256s": split_manifest_hashes,
            "near_duplicate_audit": fingerprint_audit,
        }
    )
    artifacts = {
        output_dir / f"real-gold-{name}.manifest.json": frozen["manifests"][name]
        for name in _SPLIT_NAMES
    }
    artifacts[audit_output] = audit
    _write_immutable_artifacts(artifacts)
    return audit


def load_training_manifest(path: Path) -> dict[str, Any]:
    """Load only the frozen train split, before exposing any track paths."""

    manifest = _read_json(path)
    split_name = manifest.get("split")
    if split_name != "train":
        raise PermissionError(f"{split_name or 'unknown'} split is not available to training")
    if manifest.get("corpus_role") != "real-gold":
        raise ValueError("training split must contain real-gold tracks")
    tracks = manifest.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        raise ValueError("training split must contain tracks")
    return manifest


def _audit_audio_fingerprints(
    manifests: list[dict[str, Any]],
    *,
    source_root: Path | None,
    dataset_roots: Mapping[str, Path] | None,
    threshold: float,
) -> dict[str, Any]:
    shared_root = source_root.resolve(strict=True) if source_root is not None else None
    resolved_roots = (
        {dataset_id: path.resolve(strict=True) for dataset_id, path in dataset_roots.items()}
        if dataset_roots is not None
        else {}
    )
    fingerprints = {}
    cover_groups: dict[str, str] = {}
    for manifest in manifests:
        dataset_id = manifest.get("dataset_id")
        tracks = manifest.get("tracks")
        if not isinstance(dataset_id, str) or not isinstance(tracks, list):
            raise ValueError("audio fingerprint audit requires dataset manifests")
        root = resolved_roots.get(dataset_id, shared_root)
        if root is None:
            raise ValueError(f"audio fingerprint audit is missing root for {dataset_id}")
        for track in tracks:
            if not isinstance(track, dict):
                raise ValueError("audio fingerprint audit tracks must be objects")
            track_id = track.get("track_id")
            cover_group_id = track.get("cover_group_id")
            audio_path = track.get("audio_path")
            if any(
                not isinstance(value, str) or not value.strip()
                for value in (track_id, cover_group_id, audio_path)
            ):
                raise ValueError("audio fingerprint audit requires track, group, and path")
            global_track_id = f"{dataset_id}:{track_id}"
            resolved_audio = (root / audio_path).resolve(strict=True)
            try:
                resolved_audio.relative_to(root)
            except ValueError:
                raise ValueError("audio fingerprint path must remain inside source root") from None
            fingerprints[global_track_id] = fingerprint_wav(resolved_audio)
            cover_groups[global_track_id] = f"{dataset_id}:{cover_group_id}"
    candidates = find_near_duplicates(fingerprints, threshold=threshold)
    cross_group = [
        candidate
        for candidate in candidates
        if cover_groups[candidate.left_track_id] != cover_groups[candidate.right_track_id]
    ]
    if cross_group:
        first = cross_group[0]
        raise SplitAuditRequired(
            "cross-group near-duplicate requires manual audit: "
            f"{first.left_track_id} vs {first.right_track_id} ({first.score})"
        )
    return {
        "status": "passed",
        "fingerprinted_track_count": len(fingerprints),
        "threshold": threshold,
        "candidate_count": len(candidates),
        "cross_group_candidate_count": 0,
        "same_group_candidates": [
            {
                "left_track_id": candidate.left_track_id,
                "right_track_id": candidate.right_track_id,
                "score": candidate.score,
            }
            for candidate in candidates
        ],
    }


def _load_policy(config: dict[str, Any]) -> tuple[SplitPolicy, int, str]:
    if config.get("schema_version") != 1:
        raise ValueError("split config schema_version must be 1")
    policy_version = config.get("policy_version")
    ratios = config.get("ratios")
    seed = config.get("seed")
    if not isinstance(policy_version, str) or not policy_version.strip():
        raise ValueError("split config policy_version must be a non-empty string")
    if not isinstance(ratios, dict):
        raise ValueError("split config ratios must be an object")
    if type(seed) is not int:
        raise ValueError("split config seed must be an integer")
    try:
        policy = SplitPolicy(
            train=ratios["train"],
            calibration=ratios["calibration"],
            validation=ratios["validation"],
            test=ratios["test"],
            artist_disjoint=config["artist_disjoint"],
            near_duplicate_threshold=config["near_duplicate_threshold"],
        )
    except KeyError as error:
        raise ValueError(f"split config missing field: {error.args[0]}") from None
    return policy, seed, policy_version


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON artifact {path}: {error}") from None
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must contain an object: {path}")
    return value


def _write_immutable_artifacts(artifacts: dict[Path, dict[str, Any]]) -> None:
    payloads = {path: _json_bytes(value) for path, value in artifacts.items()}
    for path, payload in payloads.items():
        if path.exists() and path.read_bytes() != payload:
            raise FileExistsError(f"frozen artifact already exists with different content: {path}")
    for path, payload in payloads.items():
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_name, path)
        finally:
            temporary_path = Path(temporary_name)
            if temporary_path.exists():
                temporary_path.unlink()


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _parse_dataset_roots(values: list[str]) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for value in values:
        dataset_id, separator, raw_path = value.partition("=")
        if not separator or not dataset_id.strip() or not raw_path.strip():
            raise ValueError("dataset roots must use DATASET_ID=PATH")
        if dataset_id in roots:
            raise ValueError(f"dataset root supplied more than once: {dataset_id}")
        roots[dataset_id] = Path(raw_path)
    return roots


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze leakage-resistant real-gold splits")
    parser.add_argument("--manifest", action="append", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    root_group = parser.add_mutually_exclusive_group(required=True)
    root_group.add_argument("--source-root", type=Path)
    root_group.add_argument("--dataset-root", action="append", default=[])
    args = parser.parse_args()
    audit = freeze_split_files(
        args.manifest,
        config_path=args.config,
        output_dir=args.output_dir,
        audit_output=args.audit_output,
        source_root=args.source_root,
        dataset_roots=_parse_dataset_roots(args.dataset_root) if args.dataset_root else None,
    )
    print(json.dumps(audit, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
