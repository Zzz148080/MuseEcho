from __future__ import annotations

import json
import math
import wave
from copy import deepcopy
from pathlib import Path

import pytest

from museecho_ml.data.split import (
    SplitAuditRequired,
    SplitPolicy,
    freeze_real_gold_splits,
)
from museecho_ml.data.split_freeze import freeze_split_files, load_training_manifest


def _track(track_id: str, *, audio_sha256: str) -> dict[str, object]:
    return {
        "track_id": track_id,
        "work_id": "shared-work",
        "cover_group_id": "shared-group",
        "artist_id": "shared-artist",
        "audio_path": f"audio/{track_id}.wav",
        "annotation_path": f"annotations/{track_id}.json",
        "duration_seconds": 10.0,
        "audio_sha256": audio_sha256,
        "annotation_sha256": f"annotation-{audio_sha256}",
        "intervals": [
            {
                "start_seconds": 0.0,
                "end_seconds": 10.0,
                "root": "C",
                "quality": "maj",
                "bass": "1",
                "mapping_reason": None,
            }
        ],
    }


def _manifest(dataset_id: str, hashes: list[str]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "dataset_version": "fixture-v1",
        "corpus_role": "real-gold",
        "tracks": [
            _track(f"track-{index}", audio_sha256=audio_hash)
            for index, audio_hash in enumerate(hashes)
        ],
    }


def _write_tone(
    path: Path,
    *,
    frequency_hz: float,
    duration_seconds: float,
    sample_rate: int = 8000,
    start_seconds: float = 0.0,
) -> None:
    frames = bytearray()
    for index in range(round(duration_seconds * sample_rate)):
        time_seconds = start_seconds + index / sample_rate
        sample = round(12000 * math.sin(2 * math.pi * frequency_hz * time_seconds))
        frames.extend(int(sample).to_bytes(2, "little", signed=True))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(bytes(frames))


def test_freeze_real_gold_splits_is_deterministic_and_namespaces_dataset_ids() -> None:
    alpha = _manifest("alpha", [f"alpha-{index}" for index in range(8)])
    beta = _manifest("beta", [f"beta-{index}" for index in range(8)])
    policy = SplitPolicy(train=0.5, calibration=0.125, validation=0.125, test=0.25)

    first = freeze_real_gold_splits([alpha, beta], policy, seed=20260818)
    second = freeze_real_gold_splits(
        [deepcopy(beta), deepcopy(alpha)], policy, seed=20260818
    )

    assert first == second
    assert set(first["manifests"]) == {"train", "calibration", "validation", "test"}
    assert first["audit"]["source_dataset_ids"] == ["alpha", "beta"]
    assert len(first["audit"]["combined_manifest_sha256"]) == 64
    assert len(first["audit"]["split_sha256"]) == 64
    assert sum(
        statistics["track_count"]
        for statistics in first["audit"]["splits"].values()
    ) == 16
    assert sum(
        statistics["qualities"].get("maj", {}).get("interval_count", 0)
        for statistics in first["audit"]["splits"].values()
    ) == 16
    assert sum(
        statistics["total_audio_seconds"]
        for statistics in first["audit"]["splits"].values()
    ) == 160.0

    frozen_tracks = [
        track
        for split_name in ("train", "calibration", "validation", "test")
        for track in first["manifests"][split_name]["tracks"]
    ]
    assert len(frozen_tracks) == 16
    assert len({track["track_id"] for track in frozen_tracks}) == 16
    assert {track["dataset_id"] for track in frozen_tracks} == {"alpha", "beta"}
    assert {track["source_track_id"] for track in frozen_tracks} == {
        f"track-{index}" for index in range(8)
    }
    assert all(
        manifest["corpus_role"] == "real-gold"
        and manifest["split"] == split_name
        and manifest["split_sha256"] == first["audit"]["split_sha256"]
        for split_name, manifest in first["manifests"].items()
    )


def test_freeze_real_gold_splits_rejects_non_real_gold_input() -> None:
    synthetic = _manifest("synthetic", ["synthetic-audio"])
    synthetic["corpus_role"] = "synthetic-supervised"

    with pytest.raises(ValueError, match="real-gold"):
        freeze_real_gold_splits([synthetic], SplitPolicy(), seed=20260818)


def test_freeze_split_files_writes_immutable_manifests_and_public_audit(
    tmp_path: Path,
) -> None:
    manifest_paths: list[Path] = []
    for dataset_id in ("alpha", "beta"):
        path = tmp_path / f"{dataset_id}.json"
        path.write_text(
            json.dumps(
                _manifest(dataset_id, [f"{dataset_id}-{index}" for index in range(8)])
            ),
            encoding="utf-8",
        )
        manifest_paths.append(path)
    config_path = tmp_path / "split-v1.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "policy_version": "1.0.0",
                "ratios": {
                    "train": 0.5,
                    "calibration": 0.125,
                    "validation": 0.125,
                    "test": 0.25,
                },
                "artist_disjoint": False,
                "near_duplicate_threshold": 0.8,
                "seed": 20260818,
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "splits"
    audit_path = tmp_path / "split-audit-v1.json"

    first = freeze_split_files(
        manifest_paths,
        config_path=config_path,
        output_dir=output_dir,
        audit_output=audit_path,
    )
    second = freeze_split_files(
        list(reversed(manifest_paths)),
        config_path=config_path,
        output_dir=output_dir,
        audit_output=audit_path,
    )

    assert first == second == json.loads(audit_path.read_text(encoding="utf-8"))
    assert sorted(path.name for path in output_dir.iterdir()) == [
        "real-gold-calibration.manifest.json",
        "real-gold-test.manifest.json",
        "real-gold-train.manifest.json",
        "real-gold-validation.manifest.json",
    ]
    assert "audio_path" not in audit_path.read_text(encoding="utf-8")
    train_manifest = load_training_manifest(
        output_dir / "real-gold-train.manifest.json"
    )
    assert train_manifest["split"] == "train"
    with pytest.raises(PermissionError, match="test"):
        load_training_manifest(output_dir / "real-gold-test.manifest.json")

    changed = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
    changed["tracks"][0]["duration_seconds"] = 11.0
    manifest_paths[0].write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(FileExistsError, match="frozen artifact"):
        freeze_split_files(
            manifest_paths,
            config_path=config_path,
            output_dir=output_dir,
            audit_output=audit_path,
        )


def test_freeze_split_files_requires_audit_for_cross_group_near_duplicate(
    tmp_path: Path,
) -> None:
    _write_tone(tmp_path / "full.wav", frequency_hz=233.0, duration_seconds=6.0)
    _write_tone(
        tmp_path / "clip.wav",
        frequency_hz=233.0,
        duration_seconds=3.0,
        start_seconds=2.0,
    )
    manifest = _manifest("alpha", ["full-hash", "clip-hash"])
    manifest["tracks"][0]["audio_path"] = "full.wav"
    manifest["tracks"][1]["audio_path"] = "clip.wav"
    manifest["tracks"][1]["work_id"] = "other-work"
    manifest["tracks"][1]["cover_group_id"] = "other-group"
    manifest_path = tmp_path / "alpha.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    config_path = tmp_path / "split-v1.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "policy_version": "1.0.0",
                "ratios": {
                    "train": 0.7,
                    "calibration": 0.1,
                    "validation": 0.1,
                    "test": 0.1,
                },
                "artist_disjoint": False,
                "near_duplicate_threshold": 0.8,
                "seed": 20260818,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SplitAuditRequired, match="near-duplicate"):
        freeze_split_files(
            [manifest_path],
            config_path=config_path,
            output_dir=tmp_path / "splits",
            audit_output=tmp_path / "audit.json",
            source_root=tmp_path,
        )


def test_freeze_split_files_supports_explicit_dataset_roots(tmp_path: Path) -> None:
    manifest_paths: list[Path] = []
    dataset_roots: dict[str, Path] = {}
    for index, dataset_id in enumerate(("alpha", "beta")):
        dataset_root = tmp_path / f"{dataset_id}-root"
        dataset_root.mkdir()
        _write_tone(
            dataset_root / "track.wav",
            frequency_hz=233.0 + index * 101.0,
            duration_seconds=2.0,
        )
        manifest = _manifest(dataset_id, [f"{dataset_id}-hash"])
        manifest["tracks"][0]["audio_path"] = "track.wav"
        manifest_path = tmp_path / f"{dataset_id}.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        manifest_paths.append(manifest_path)
        dataset_roots[dataset_id] = dataset_root
    config_path = tmp_path / "split-v1.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "policy_version": "1.0.0",
                "ratios": {
                    "train": 0.7,
                    "calibration": 0.1,
                    "validation": 0.1,
                    "test": 0.1,
                },
                "artist_disjoint": False,
                "near_duplicate_threshold": 0.8,
                "seed": 20260818,
            }
        ),
        encoding="utf-8",
    )

    audit = freeze_split_files(
        manifest_paths,
        config_path=config_path,
        output_dir=tmp_path / "splits",
        audit_output=tmp_path / "audit.json",
        dataset_roots=dataset_roots,
    )

    assert audit["near_duplicate_audit"]["status"] == "passed"
    assert audit["near_duplicate_audit"]["fingerprinted_track_count"] == 2
