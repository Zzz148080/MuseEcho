from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from museecho_ml.artifacts import canonical_sha256
from museecho_ml.data.registry import (
    DatasetRecord,
    DatasetRegistry,
    LicenseStatus,
)
from museecho_ml.evaluation.promotion import (
    authorize_frozen_test,
    consume_frozen_test,
    decide_model_promotion,
    open_frozen_test_session,
)


def _test_manifest() -> dict:
    return {
        "schema_version": 1,
        "corpus_role": "real-gold",
        "split": "test",
        "split_sha256": "a" * 64,
        "tracks": [{"track_id": "fixture:test"}],
    }


def _selection() -> dict:
    test_sha256 = canonical_sha256(_test_manifest())
    body = {
        "schema_version": 1,
        "selection_version": "plan-c-selection-v1",
        "status": "frozen",
        "protocol_sha256": "b" * 64,
        "vocabulary_sha256": "c" * 64,
        "validation_manifest_sha256": "d" * 64,
        "test_manifest_sha256": test_sha256,
        "test_split_sha256": "a" * 64,
        "calibration_sha256": "e" * 64,
        "threshold_sha256": "f" * 64,
        "checkpoint_sha256": "1" * 64,
        "winning_course": "C1",
        "winning_seed": 20260821,
    }
    return {**body, "selection_sha256": canonical_sha256(body)}


def _record(dataset_id: str, *, distribution: bool | None = True) -> DatasetRecord:
    return DatasetRecord(
        dataset_id=dataset_id,
        name=dataset_id,
        version="1",
        source_url=f"https://example.invalid/{dataset_id}",
        status=LicenseStatus.APPROVED,
        annotation_license="fixture-approved",
        audio_license="fixture-approved",
        training_allowed=True,
        weights_distribution_allowed=distribution,
        citation=f"{dataset_id} citation",
        reviewed_at="2026-08-21",
        review_evidence=("fixture-review",),
    )


def _registry(*, distribution: bool | None = True) -> DatasetRegistry:
    return DatasetRegistry(
        tuple(
            _record(dataset_id, distribution=distribution)
            for dataset_id in ("guitarset", "rwc-popular", "schubert-winterreise")
        )
    )


def _candidate() -> dict:
    selection = _selection()
    return {
        "test_manifest_sha256": selection["test_manifest_sha256"],
        "vocabulary_sha256": selection["vocabulary_sha256"],
        "calibration_sha256": selection["calibration_sha256"],
        "threshold_sha256": selection["threshold_sha256"],
        "checkpoint_sha256": selection["checkpoint_sha256"],
        "training_dataset_ids": [
            "guitarset",
            "rwc-popular",
            "schubert-winterreise",
        ],
        "metrics": {
            "majmin_wcsr": 0.80,
            "exact_vocabulary_wcsr": 0.70,
            "seventh_quality_macro_f1": 0.55,
            "published_known_precision": 0.85,
            "coverage": 0.65,
            "ece": 0.08,
        },
    }


def _legacy() -> dict:
    return {
        "test_manifest_sha256": _selection()["test_manifest_sha256"],
        "metrics": {
            "majmin_wcsr": 0.80,
            "exact_vocabulary_wcsr": 0.60,
        },
    }


def _operational() -> dict:
    return {
        "deterministic_events": True,
        "onnx_max_abs_probability_error": 1e-4,
        "onnx_events_identical": True,
        "chord_five_minute_wall_seconds": 30.0,
        "chord_peak_rss_bytes": 2 * 1024**3,
        "full_five_minute_wall_seconds": 90.0,
        "full_peak_rss_bytes": 4 * 1024**3,
    }


def test_test_authorization_binds_every_frozen_identity() -> None:
    receipt = authorize_frozen_test(
        _selection(), _test_manifest(), existing_receipt=None
    )

    assert receipt["status"] == "authorized"
    assert receipt["selection_sha256"] == _selection()["selection_sha256"]
    assert receipt["test_manifest_sha256"] == canonical_sha256(_test_manifest())
    assert receipt["checkpoint_sha256"] == _selection()["checkpoint_sha256"]


def test_frozen_test_session_reads_manifest_exactly_once(tmp_path: Path) -> None:
    manifest_path = tmp_path / "test.manifest.json"
    marker_path = tmp_path / "test-access.marker"
    manifest_path.write_text(json.dumps(_test_manifest()), encoding="utf-8")

    session = open_frozen_test_session(
        selection=_selection(),
        manifest_path=manifest_path,
        access_marker_path=marker_path,
    )

    assert marker_path.is_file()
    assert session.evaluate_once(lambda manifest: manifest["split"]) == "test"
    with pytest.raises(PermissionError, match="already accessed"):
        session.evaluate_once(lambda manifest: manifest["split"])
    with pytest.raises(PermissionError, match="already accessed"):
        open_frozen_test_session(
            selection=_selection(),
            manifest_path=manifest_path,
            access_marker_path=marker_path,
        )


def test_failed_test_open_burns_marker_before_manifest_parse(tmp_path: Path) -> None:
    manifest_path = tmp_path / "test.manifest.json"
    marker_path = tmp_path / "test-access.marker"
    manifest_path.write_text("not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="unreadable"):
        open_frozen_test_session(
            selection=_selection(),
            manifest_path=manifest_path,
            access_marker_path=marker_path,
        )

    manifest_path.write_text(json.dumps(_test_manifest()), encoding="utf-8")
    with pytest.raises(PermissionError, match="already accessed"):
        open_frozen_test_session(
            selection=_selection(),
            manifest_path=manifest_path,
            access_marker_path=marker_path,
        )


def test_existing_receipt_forbids_second_test_access_and_consumes_once() -> None:
    authorized = authorize_frozen_test(
        _selection(), _test_manifest(), existing_receipt=None
    )
    consumed = consume_frozen_test(
        authorized,
        candidate_report_sha256="2" * 64,
        legacy_report_sha256="3" * 64,
    )

    assert consumed["status"] == "consumed"
    assert consumed["candidate_report_sha256"] == "2" * 64
    with pytest.raises(PermissionError, match="already consumed"):
        authorize_frozen_test(
            _selection(), _test_manifest(), existing_receipt=consumed
        )
    with pytest.raises(PermissionError, match="already consumed"):
        consume_frozen_test(
            consumed,
            candidate_report_sha256="2" * 64,
            legacy_report_sha256="3" * 64,
        )


def test_test_authorization_rejects_identity_or_split_drift() -> None:
    manifest = _test_manifest()
    manifest["split"] = "validation"
    with pytest.raises(PermissionError, match="test split"):
        authorize_frozen_test(_selection(), manifest, existing_receipt=None)

    manifest = _test_manifest()
    manifest["split_sha256"] = "9" * 64
    with pytest.raises(ValueError, match="test manifest"):
        authorize_frozen_test(_selection(), manifest, existing_receipt=None)


def test_passing_candidate_promotes_at_exact_gate_boundaries() -> None:
    result = decide_model_promotion(
        selection=_selection(),
        candidate=_candidate(),
        legacy=_legacy(),
        operational=_operational(),
        registry=_registry(),
    )

    assert result["status"] == "passed"
    assert result["default_algorithm"] == "deep-chord-plan-c-v1"
    assert result["failed_reason_codes"] == []
    assert result["strong_result_target_met"] is True


def test_unapproved_weight_distribution_keeps_legacy_default() -> None:
    result = decide_model_promotion(
        selection=_selection(),
        candidate=_candidate(),
        legacy=_legacy(),
        operational=_operational(),
        registry=_registry(distribution=None),
    )

    assert result["status"] == "rejected"
    assert result["default_algorithm"] == "chroma-triad-viterbi-v1"
    assert "weights-distribution-not-approved" in result["failed_reason_codes"]


@pytest.mark.parametrize(
    ("status", "training_allowed", "distribution_allowed"),
    [
        (LicenseStatus.NEEDS_REVIEW, None, None),
        (LicenseStatus.BLOCKED, False, False),
        (LicenseStatus.APPROVED, True, None),
    ],
)
def test_non_approved_distribution_states_keep_legacy_default(
    status: LicenseStatus,
    training_allowed: bool | None,
    distribution_allowed: bool | None,
) -> None:
    blocked = replace(
        _record("rwc-popular"),
        status=status,
        training_allowed=training_allowed,
        weights_distribution_allowed=distribution_allowed,
    )
    registry = DatasetRegistry(
        (
            _record("guitarset"),
            blocked,
            _record("schubert-winterreise"),
        )
    )

    result = decide_model_promotion(
        selection=_selection(),
        candidate=_candidate(),
        legacy=_legacy(),
        operational=_operational(),
        registry=registry,
    )

    assert result["status"] == "rejected"
    assert result["license_checks"]["rwc-popular"] is False
    assert result["default_algorithm"] == "chroma-triad-viterbi-v1"


@pytest.mark.parametrize(
    ("target", "field", "value", "reason"),
    [
        ("candidate", "majmin_wcsr", 0.799, "majmin-not-below-legacy"),
        ("candidate", "exact_vocabulary_wcsr", 0.60, "exact-strictly-above-legacy"),
        ("candidate", "seventh_quality_macro_f1", 0.549, "seventh-macro-f1"),
        ("candidate", "published_known_precision", 0.849, "published-known-precision"),
        ("candidate", "coverage", 0.649, "coverage"),
        ("candidate", "ece", 0.081, "ece"),
        ("operational", "deterministic_events", False, "deterministic-events"),
        (
            "operational",
            "onnx_max_abs_probability_error",
            1.01e-4,
            "onnx-probability-parity",
        ),
        ("operational", "onnx_events_identical", False, "onnx-event-parity"),
        ("operational", "chord_five_minute_wall_seconds", 30.01, "chord-cpu-wall"),
        ("operational", "chord_peak_rss_bytes", 2 * 1024**3 + 1, "chord-peak-rss"),
        ("operational", "full_five_minute_wall_seconds", 90.01, "full-analysis-wall"),
        ("operational", "full_peak_rss_bytes", 4 * 1024**3 + 1, "full-analysis-peak-rss"),
    ],
)
def test_each_failed_promotion_predicate_keeps_legacy(
    target: str, field: str, value: object, reason: str
) -> None:
    candidate = _candidate()
    operational = _operational()
    if target == "candidate":
        candidate["metrics"][field] = value
    else:
        operational[field] = value

    result = decide_model_promotion(
        selection=_selection(),
        candidate=candidate,
        legacy=_legacy(),
        operational=operational,
        registry=_registry(),
    )

    assert result["status"] == "rejected"
    assert reason in result["failed_reason_codes"]
    assert result["default_algorithm"] == "chroma-triad-viterbi-v1"


def test_promotion_rejects_nan() -> None:
    candidate = _candidate()
    candidate["metrics"]["coverage"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        decide_model_promotion(
            selection=_selection(),
            candidate=candidate,
            legacy=_legacy(),
            operational=_operational(),
            registry=_registry(),
        )


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("test_manifest_sha256", "test manifest"),
        ("vocabulary_sha256", "vocabulary"),
        ("calibration_sha256", "calibration"),
    ],
)
def test_promotion_rejects_candidate_identity_drift(field: str, message: str) -> None:
    candidate = deepcopy(_candidate())
    candidate[field] = "9" * 64
    with pytest.raises(ValueError, match=message):
        decide_model_promotion(
            selection=_selection(),
            candidate=candidate,
            legacy=_legacy(),
            operational=_operational(),
            registry=_registry(),
        )
