from __future__ import annotations

import json
from pathlib import Path

import pytest

from museecho_ml.artifacts import canonical_json_bytes, canonical_sha256
from museecho_ml.data.plan_d import (
    PLAN_C_TEST_MANIFEST_SHA256,
    load_plan_d_development_manifest,
    load_plan_d_protocol,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PLAN_D_DOCS = REPOSITORY_ROOT / "docs" / "ml" / "plan-d"
PLAN_D_CONFIG = REPOSITORY_ROOT / "ml" / "configs" / "plan-d-v1.json"


def _protocol_fixture() -> dict:
    return {
        "development_splits": {
            "train": {"manifest_sha256": "a" * 64},
            "calibration": {"manifest_sha256": "b" * 64},
            "validation": {"manifest_sha256": "c" * 64},
        }
    }


def test_plan_d_rejects_test_identity_before_manifest_read(tmp_path: Path) -> None:
    unreadable = tmp_path / "must-not-read.json"
    unreadable.write_text("not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="Plan D forbids test split"):
        load_plan_d_development_manifest(
            unreadable,
            expected_split="test",
            expected_sha256=PLAN_C_TEST_MANIFEST_SHA256,
            protocol=_protocol_fixture(),
        )


def test_plan_d_rejects_plan_c_test_sha_before_manifest_read(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.json"

    with pytest.raises(ValueError, match="Plan D forbids the Plan C test manifest"):
        load_plan_d_development_manifest(
            missing,
            expected_split="train",
            expected_sha256=PLAN_C_TEST_MANIFEST_SHA256,
            protocol=_protocol_fixture(),
        )


def test_plan_d_manifest_uses_canonical_identity_and_checks_split(
    tmp_path: Path,
) -> None:
    manifest = {"schema_version": 1, "split": "train", "tracks": []}
    path = tmp_path / "formatted.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    identity = canonical_sha256(manifest)
    protocol = _protocol_fixture()
    protocol["development_splits"]["train"]["manifest_sha256"] = identity

    assert load_plan_d_development_manifest(
        path,
        expected_split="train",
        expected_sha256=identity,
        protocol=protocol,
    ) == manifest

    manifest["split"] = "validation"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    changed_identity = canonical_sha256(manifest)
    protocol["development_splits"]["train"]["manifest_sha256"] = changed_identity
    with pytest.raises(ValueError, match="split drift"):
        load_plan_d_development_manifest(
            path,
            expected_split="train",
            expected_sha256=changed_identity,
            protocol=protocol,
        )


def test_plan_d_protocol_excludes_test_and_binds_plan_c() -> None:
    payload = load_plan_d_protocol(PLAN_D_DOCS / "protocol-v1.json")

    assert set(payload["development_splits"]) == {
        "train",
        "calibration",
        "validation",
    }
    assert "test" not in canonical_json_bytes(payload).decode("utf-8")
    assert payload["plan_c"] == {
        "protocol_sha256": "f9e2c39367a21e3cf467e9bfbd5b72dfb5f6db49a34572abbd719bb2ea60a568",
        "selection_sha256": "5bb7ad3bc46e251756ac7f9e8c1de1a2280976912a3cc9a1fd17dc664f2bf262",
        "vocabulary_sha256": "11a4b33e627d04bf11c3691de702b051f6bda648c5d75a0b86f0b1cad04fa1bf",
        "selected_checkpoint_sha256": (
            "b5b89e53a2571f05567eaf7947bf9afc37bba2b05b60d8fababbedae9803eb34"
        ),
        "selected_course": "C1",
        "selected_seed": 20260821,
    }
    assert payload["legacy_algorithm"] == {
        "source_sha256": "1e60141a9d0f2deb6cef8376536d0288aab9294cd080f7a5f9183dfa15764c49",
        "version": "chroma-triad-viterbi-v1",
    }

    body = dict(payload)
    embedded = body.pop("protocol_sha256")
    assert canonical_sha256(body) == embedded


def test_plan_d_config_freezes_replay_and_development_gates() -> None:
    config = json.loads(PLAN_D_CONFIG.read_text(encoding="utf-8"))

    assert config["seeds"] == [20260821, 20260822, 20260823]
    assert config["bootstrap"] == {
        "resamples": 10000,
        "seed": 20260821,
        "unit": "cover_group_id",
    }
    assert config["development_splits"] == {
        "calibration": "25dae88fb315ec8fd25d07f80d353aa07ad6e3077fcc8dacd4faec87847d7d54",
        "train": "ac495aa86de00e8ed5a3f67fc8289a55395e85a133ba2c338e91aaa4fe232f5c",
        "validation": "4e0522bcc9b0765ac8fdd7f2728994edecdf186e63ff2238af2854afd94c4106",
    }
    assert config["replay_continuation_gate"] == {
        "maximum_dataset_regression": 0.05,
        "maximum_event_ratio": 1.5,
        "minimum_coverage": 0.1,
        "minimum_event_ratio": 0.75,
        "minimum_exact_gain_over_deep": 0.01,
        "minimum_exact_gain_over_legacy": 0.01,
        "minimum_known_precision": 0.4,
    }
    assert config["development_gate"] == {
        "maximum_cpu_seconds": 15.0,
        "maximum_dataset_regression": 0.02,
        "maximum_event_ratio": 1.5,
        "maximum_seed_span": 0.05,
        "minimum_coverage": 0.2,
        "minimum_event_ratio": 0.75,
        "minimum_exact": 0.3,
        "minimum_exact_gain_over_deep": 0.03,
        "minimum_exact_gain_over_legacy": 0.03,
        "minimum_known_precision": 0.6,
    }
