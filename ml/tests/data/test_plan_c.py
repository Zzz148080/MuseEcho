from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from museecho_ml.artifacts import canonical_json_bytes, canonical_sha256
from museecho_ml.data.plan_c import freeze_plan_c_protocol
from museecho_ml.data.registry import (
    DatasetRecord,
    DatasetRegistry,
    LicenseStatus,
)
from museecho_ml.labels import BASS_INTERVALS, PITCH_NAMES

ML_ROOT = Path(__file__).resolve().parents[2]
SPLITS = ("train", "calibration", "validation", "test")
SPLIT_SHA256 = "a" * 64


def _record(dataset_id: str) -> DatasetRecord:
    return DatasetRecord(
        dataset_id=dataset_id,
        name=dataset_id,
        version="1",
        source_url=f"https://example.invalid/{dataset_id}",
        status=LicenseStatus.APPROVED,
        annotation_license="fixture-approved",
        audio_license="fixture-approved",
        training_allowed=True,
        weights_distribution_allowed=True,
        citation=f"{dataset_id} citation",
        reviewed_at="2026-08-21",
        review_evidence=("fixture-review",),
    )


def _registry() -> DatasetRegistry:
    return DatasetRegistry(
        tuple(
            _record(dataset_id)
            for dataset_id in (
                "fixture-real",
                "idmt-smt-chord-sequences",
                "jazznet",
                "maestro-score",
            )
        )
    )


def _write(path: Path, value: dict[str, Any]) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _real_paths(root: Path) -> dict[str, Path]:
    result = {}
    for index, split in enumerate(SPLITS):
        result[split] = _write(
            root / f"real-{split}.json",
            {
                "schema_version": 1,
                "dataset_id": "real-gold-combined",
                "corpus_role": "real-gold",
                "split": split,
                "split_sha256": SPLIT_SHA256,
                "tracks": [
                    {
                        "dataset_id": "fixture-real",
                        "track_id": f"fixture-real:{split}-{index}",
                        "work_id": f"fixture-real:work-{index}",
                        "cover_group_id": f"fixture-real:cover-{index}",
                    }
                ],
            },
        )
    return result


def _synthetic_path(
    root: Path,
    dataset_id: str,
    *,
    role: str = "synthetic-supervised",
    track_role: str | None = None,
) -> Path:
    track: dict[str, Any] = {
        "dataset_id": dataset_id,
        "track_id": f"{dataset_id}:track-001",
        "work_id": f"{dataset_id}:work-001",
        "cover_group_id": f"{dataset_id}:cover-001",
    }
    if track_role is not None:
        track["corpus_role"] = track_role
    return _write(
        root / f"{dataset_id}.json",
        {
            "schema_version": 1,
            "dataset_id": dataset_id,
            "corpus_role": role,
            "tracks": [track],
        },
    )


def _g1a_pass() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "gate_version": "plan-c-g1-v1",
        "g1a": {"status": "passed"},
        "g1b": {"status": "not-met"},
    }


def _vocabulary() -> dict[str, Any]:
    body = {
        "schema_version": 1,
        "vocabulary_version": "plan-c-v1",
        "source_corpus_role": "real-gold",
        "source_split": "train",
        "source_split_sha256": SPLIT_SHA256,
        "minimum_group_count": 20,
        "quality_group_counts": {"maj": 20},
        "root_labels": [*PITCH_NAMES, "N", "X"],
        "quality_labels": ["maj", "N", "X"],
        "bass_labels": [*BASS_INTERVALS, "N", "X"],
        "mapped_to_x": ["7", "dim", "hdim7", "maj7", "min", "min7", "sus2", "sus4"],
    }
    return {**body, "vocabulary_sha256": canonical_sha256(body)}


def _route_a() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "route": "A",
        "usable_synthetic_hours": 41.487981,
        "usable_synthetic_seconds": 149356.733333,
        "threshold_hours": 60.0,
        "threshold_seconds": 216000.0,
        "included_datasets": ["idmt-smt-chord-sequences", "jazznet"],
        "excluded_datasets": [],
    }


def _config() -> dict[str, Any]:
    return json.loads((ML_ROOT / "configs" / "plan-c-v1.json").read_text(encoding="utf-8"))


def test_plan_c_always_freezes_c0_and_c1_and_structurally_skips_c2(
    tmp_path: Path,
) -> None:
    protocol = freeze_plan_c_protocol(
        _config(),
        g1_report=_g1a_pass(),
        vocabulary_report=_vocabulary(),
        real_manifests=_real_paths(tmp_path),
        synthetic_manifests=[
            _synthetic_path(tmp_path, "idmt-smt-chord-sequences"),
            _synthetic_path(tmp_path, "jazznet"),
        ],
        registry=_registry(),
        historical_route_report=_route_a(),
        score_feasibility={"status": "not-approved"},
    )

    assert protocol["historical_route"] == "A"
    assert protocol["courses"]["C0"] == {"status": "ready", "pretrain": None}
    assert protocol["courses"]["C1"]["status"] == "ready"
    assert protocol["courses"]["C2"] == {
        "status": "skipped",
        "reason_code": "score-supervision-not-approved",
    }
    assert protocol["seeds"] == [20260821, 20260822, 20260823]
    assert len(protocol["protocol_sha256"]) == 64


def test_protocol_is_order_independent_and_shares_every_real_identity(
    tmp_path: Path,
) -> None:
    real = _real_paths(tmp_path)
    synthetic = [
        _synthetic_path(tmp_path, "idmt-smt-chord-sequences"),
        _synthetic_path(tmp_path, "jazznet"),
    ]
    first = freeze_plan_c_protocol(
        _config(),
        g1_report=_g1a_pass(),
        vocabulary_report=_vocabulary(),
        real_manifests=real,
        synthetic_manifests=synthetic,
        registry=_registry(),
        historical_route_report=_route_a(),
    )
    second = freeze_plan_c_protocol(
        _config(),
        g1_report=_g1a_pass(),
        vocabulary_report=_vocabulary(),
        real_manifests=dict(reversed(list(real.items()))),
        synthetic_manifests=list(reversed(synthetic)),
        registry=_registry(),
        historical_route_report=_route_a(),
    )

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert set(first["real_splits"]) == set(SPLITS)
    assert {
        binding["split_sha256"] for binding in first["real_splits"].values()
    } == {SPLIT_SHA256}


def test_plan_c_rejects_mixed_roles_before_protocol_freeze(tmp_path: Path) -> None:
    mixed = _synthetic_path(
        tmp_path,
        "idmt-smt-chord-sequences",
        track_role="real-gold",
    )

    with pytest.raises(ValueError, match="role-pure"):
        freeze_plan_c_protocol(
            _config(),
            g1_report=_g1a_pass(),
            vocabulary_report=_vocabulary(),
            real_manifests=_real_paths(tmp_path),
            synthetic_manifests=[mixed, _synthetic_path(tmp_path, "jazznet")],
            registry=_registry(),
            historical_route_report=_route_a(),
        )


def test_plan_c_requires_both_frozen_synthetic_manifests(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="required synthetic"):
        freeze_plan_c_protocol(
            _config(),
            g1_report=_g1a_pass(),
            vocabulary_report=_vocabulary(),
            real_manifests=_real_paths(tmp_path),
            synthetic_manifests=[_synthetic_path(tmp_path, "jazznet")],
            registry=_registry(),
            historical_route_report=_route_a(),
        )


def test_plan_c_freezes_ready_c2_only_with_passed_feasibility_and_score_manifest(
    tmp_path: Path,
) -> None:
    score = _synthetic_path(
        tmp_path,
        "maestro-score",
        role="real-score-supervised",
    )

    protocol = freeze_plan_c_protocol(
        _config(),
        g1_report=_g1a_pass(),
        vocabulary_report=_vocabulary(),
        real_manifests=_real_paths(tmp_path),
        synthetic_manifests=[
            _synthetic_path(tmp_path, "idmt-smt-chord-sequences"),
            _synthetic_path(tmp_path, "jazznet"),
        ],
        registry=_registry(),
        historical_route_report=_route_a(),
        score_manifest=score,
        score_feasibility={"status": "passed", "feasibility_sha256": "f" * 64},
    )

    assert protocol["courses"]["C2"]["status"] == "ready"
    assert protocol["courses"]["C2"]["pretrain"]["dataset_id"] == "maestro-score"


def test_plan_c_config_has_frozen_values() -> None:
    assert _config() == {
        "schema_version": 1,
        "plan_version": "plan-c-v1",
        "seeds": [20260821, 20260822, 20260823],
        "minimum_quality_train_groups": 20,
        "g1b_production_scale_exclusions": {
            "guitarset": "lead-sheet-domain-augmentation-not-independent-musical-works"
        },
        "bootstrap": {"resamples": 10000, "seed": 20260821, "unit": "cover_group_id"},
        "courses": ["C0", "C1", "C2"],
        "required_synthetic_datasets": ["idmt-smt-chord-sequences", "jazznet"],
        "selection_metrics": [
            "exact_vocabulary_wcsr",
            "public_quality_macro_f1",
            "published_known_precision",
            "coverage",
            "five_minute_cpu_wall_seconds",
        ],
        "course_tie_order": ["C0", "C1", "C2"],
    }
