from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any

import pytest

from museecho_ml.data.gates import evaluate_data_gates
from museecho_ml.data.registry import (
    DatasetRecord,
    DatasetRegistry,
    LicenseStatus,
)

SPLITS = ("train", "calibration", "validation", "test")
SPLIT_SHA256 = "a" * 64


def _approved_registry() -> DatasetRegistry:
    return DatasetRegistry(
        (
            DatasetRecord(
                dataset_id="fixture",
                name="Fixture",
                version="1",
                source_url="https://example.invalid/fixture",
                status=LicenseStatus.APPROVED,
                annotation_license="fixture-approved",
                audio_license="fixture-approved",
                training_allowed=True,
                weights_distribution_allowed=None,
                citation="Fixture citation",
                reviewed_at="2026-08-21",
                review_evidence=("fixture-review",),
            ),
        )
    )


def _approved_registry_with_domain_augmentation() -> DatasetRegistry:
    fixture = _approved_registry().records[0]
    augmentation = DatasetRecord(
        dataset_id="domain-augmentation",
        name="Domain augmentation",
        version="1",
        source_url="https://example.invalid/domain-augmentation",
        status=LicenseStatus.APPROVED,
        annotation_license="fixture-approved",
        audio_license="fixture-approved",
        training_allowed=True,
        weights_distribution_allowed=None,
        citation="Domain augmentation citation",
        reviewed_at="2026-08-21",
        review_evidence=("fixture-review",),
    )
    return DatasetRegistry((fixture, augmentation))


def _manifest(split: str, start: int, count: int = 31) -> dict[str, Any]:
    tracks = []
    for index in range(start, start + count):
        tracks.append(
            {
                "dataset_id": "fixture",
                "track_id": f"fixture:track-{index:03d}",
                "work_id": f"fixture:work-{index:03d}",
                "cover_group_id": f"fixture:cover-{index:03d}",
                "intervals": [
                    {
                        "start_seconds": 0.0,
                        "end_seconds": 1.0,
                        "root": "C",
                        "quality": "maj",
                        "bass": "1",
                    }
                ],
            }
        )
    return {
        "schema_version": 1,
        "corpus_role": "real-gold",
        "dataset_id": "combined-real-gold",
        "split": split,
        "split_sha256": SPLIT_SHA256,
        "tracks": tracks,
    }


def _four_real_gold_manifests() -> dict[str, dict[str, Any]]:
    return {
        split: _manifest(split, split_index * 31)
        for split_index, split in enumerate(SPLITS)
    }


def _manifest_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _passed_split_audit(
    manifests: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "split_sha256": SPLIT_SHA256,
        "split_manifest_sha256s": {
            split: _manifest_sha256(manifests[split]) for split in SPLITS
        },
        "near_duplicate_audit": {"status": "passed"},
    }


def test_audited_small_data_passes_g1a_but_not_g1b() -> None:
    manifests = _four_real_gold_manifests()

    status = evaluate_data_gates(
        _approved_registry(), manifests, _passed_split_audit(manifests)
    )

    assert status["g1a"]["status"] == "passed"
    assert status["g1b"]["status"] == "not-met"
    assert status["g1b"]["observed"]["work_count"] == 124
    assert status["g1b"]["observed"]["annotated_seconds"] == 124.0
    assert status["g1b"]["required"]["work_count"] == 500
    assert status["g1b"]["required"]["annotated_seconds"] == 288_000.0
    assert status["g1b"]["reason_codes"] == [
        "real-gold-work-count-below-target",
        "real-gold-duration-below-target",
    ]


def test_g1b_explicitly_excludes_domain_augmentation_without_hiding_it_from_g1a() -> None:
    manifests = _four_real_gold_manifests()
    augmentation = copy.deepcopy(manifests["train"]["tracks"][0])
    augmentation.update(
        {
            "dataset_id": "domain-augmentation",
            "track_id": "domain-augmentation:track-001",
            "work_id": "domain-augmentation:work-001",
            "cover_group_id": "domain-augmentation:cover-001",
        }
    )
    manifests["train"]["tracks"].append(augmentation)

    status = evaluate_data_gates(
        _approved_registry_with_domain_augmentation(),
        manifests,
        _passed_split_audit(manifests),
        production_scale_exclusions={
            "domain-augmentation": "lead-sheet-domain-augmentation"
        },
    )

    assert status["g1a"]["dataset_ids"] == ["domain-augmentation", "fixture"]
    assert status["g1b"]["observed"]["work_count"] == 124
    assert status["g1b"]["excluded_datasets"] == {
        "domain-augmentation": "lead-sheet-domain-augmentation"
    }


def test_g1a_rejects_non_gold_validation_before_counting() -> None:
    manifests = _four_real_gold_manifests()
    manifests["validation"]["corpus_role"] = "synthetic-supervised"
    audit = _passed_split_audit(manifests)

    with pytest.raises(ValueError, match="validation.*real-gold"):
        evaluate_data_gates(_approved_registry(), manifests, audit)


def test_g1a_rejects_failed_near_duplicate_audit() -> None:
    manifests = _four_real_gold_manifests()
    audit = _passed_split_audit(manifests)
    audit["near_duplicate_audit"] = {"status": "failed"}

    with pytest.raises(ValueError, match="near-duplicate"):
        evaluate_data_gates(_approved_registry(), manifests, audit)


def test_g1a_rejects_work_crossing_frozen_splits() -> None:
    manifests = _four_real_gold_manifests()
    manifests["test"]["tracks"][0]["work_id"] = manifests["train"]["tracks"][0][
        "work_id"
    ]
    audit = _passed_split_audit(manifests)

    with pytest.raises(ValueError, match="work.*multiple splits"):
        evaluate_data_gates(_approved_registry(), manifests, audit)


def test_g1a_rejects_manifest_hash_drift() -> None:
    manifests = _four_real_gold_manifests()
    audit = copy.deepcopy(_passed_split_audit(manifests))
    audit["split_manifest_sha256s"]["train"] = "f" * 64

    with pytest.raises(ValueError, match="train.*SHA-256"):
        evaluate_data_gates(_approved_registry(), manifests, audit)
