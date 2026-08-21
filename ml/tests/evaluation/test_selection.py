from __future__ import annotations

from copy import deepcopy

import pytest

from museecho_ml.artifacts import canonical_json_bytes, canonical_sha256
from museecho_ml.evaluation.selection import (
    select_plan_c_candidate,
    summarize_course_runs,
)

SEEDS = (20260821, 20260822, 20260823)
VALIDATION_SHA256 = "a" * 64
VOCABULARY_SHA256 = "b" * 64
TEST_MANIFEST_SHA256 = "c" * 64
TEST_SPLIT_SHA256 = "d" * 64


def _protocol(*, c2_status: str = "skipped") -> dict:
    c2 = (
        {"status": "skipped", "reason_code": "score-supervision-not-approved"}
        if c2_status == "skipped"
        else {"status": "ready", "pretrain": {"dataset_id": "score"}}
    )
    body = {
        "schema_version": 1,
        "plan_version": "plan-c-v1",
        "g1a_status": "passed",
        "vocabulary_sha256": VOCABULARY_SHA256,
        "seeds": list(SEEDS),
        "real_splits": {
            "validation": {
                "corpus_role": "real-gold",
                "manifest_sha256": VALIDATION_SHA256,
            },
            "test": {
                "corpus_role": "real-gold",
                "manifest_sha256": TEST_MANIFEST_SHA256,
                "split_sha256": TEST_SPLIT_SHA256,
            },
        },
        "courses": {
            "C0": {"status": "ready", "pretrain": None},
            "C1": {"status": "ready", "pretrain": []},
            "C2": c2,
        },
        "selection_metrics": [
            "exact_vocabulary_wcsr",
            "public_quality_macro_f1",
            "published_known_precision",
            "coverage",
            "five_minute_cpu_wall_seconds",
        ],
        "course_tie_order": ["C0", "C1", "C2"],
    }
    return {**body, "protocol_sha256": canonical_sha256(body)}


def _report(
    course_id: str,
    seed: int,
    exact: float,
    *,
    macro_f1: float = 0.6,
    precision: float = 0.9,
    coverage: float = 0.8,
    cpu_seconds: float = 20.0,
) -> dict:
    return {
        "schema_version": 1,
        "report_version": "plan-c-validation-v1",
        "split": "validation",
        "corpus_role": "real-gold",
        "course_id": course_id,
        "seed": seed,
        "protocol_sha256": _protocol()["protocol_sha256"],
        "vocabulary_sha256": VOCABULARY_SHA256,
        "validation_manifest_sha256": VALIDATION_SHA256,
        "checkpoint_sha256": canonical_sha256([course_id, seed, "checkpoint"]),
        "calibration_sha256": canonical_sha256([course_id, seed, "calibration"]),
        "threshold_sha256": canonical_sha256([course_id, seed, "threshold"]),
        "metrics_source": "unrounded-validation",
        "metrics": {
            "exact_vocabulary_wcsr": exact,
            "public_quality_macro_f1": macro_f1,
            "published_known_precision": precision,
            "coverage": coverage,
            "five_minute_cpu_wall_seconds": cpu_seconds,
        },
    }


def _reports_where_c1_has_one_outlier() -> dict[str, list[dict]]:
    return {
        "C0": [
            _report("C0", 20260821, 0.60),
            _report("C0", 20260822, 0.70),
            _report("C0", 20260823, 0.80),
        ],
        "C1": [
            _report("C1", 20260821, 0.99),
            _report("C1", 20260822, 0.10),
            _report("C1", 20260823, 0.10),
        ],
    }


def test_course_selection_uses_three_seed_median_not_best_seed() -> None:
    selected = select_plan_c_candidate(
        _protocol(), _reports_where_c1_has_one_outlier()
    )

    assert selected["winning_course"] == "C0"
    assert selected["winning_seed"] == 20260822
    assert selected["courses"]["C0"]["metrics"]["exact_vocabulary_wcsr"] == {
        "median": 0.70,
        "minimum": 0.60,
        "maximum": 0.80,
    }


def test_frozen_selection_carries_test_binding_without_reading_test_data() -> None:
    selected = select_plan_c_candidate(
        _protocol(), _reports_where_c1_has_one_outlier()
    )

    assert selected["test_manifest_sha256"] == TEST_MANIFEST_SHA256
    assert selected["test_split_sha256"] == TEST_SPLIT_SHA256


def test_selection_rejects_protocol_without_frozen_test_binding() -> None:
    protocol = _protocol()
    protocol.pop("protocol_sha256")
    protocol["real_splits"].pop("test")
    protocol["protocol_sha256"] = canonical_sha256(protocol)
    reports = _reports_where_c1_has_one_outlier()
    for course_reports in reports.values():
        for report in course_reports:
            report["protocol_sha256"] = protocol["protocol_sha256"]

    with pytest.raises(ValueError, match="test binding"):
        select_plan_c_candidate(protocol, reports)


def test_report_and_seed_order_do_not_change_frozen_selection_bytes() -> None:
    reports = _reports_where_c1_has_one_outlier()
    reversed_reports = {
        course: list(reversed(items))
        for course, items in reversed(list(reports.items()))
    }

    first = select_plan_c_candidate(_protocol(), reports)
    second = select_plan_c_candidate(_protocol(), reversed_reports)

    assert canonical_json_bytes(first) == canonical_json_bytes(second)


def test_course_summary_rejects_missing_duplicate_and_non_finite_seed_metrics() -> None:
    reports = [_report("C0", seed, 0.5) for seed in SEEDS]

    with pytest.raises(ValueError, match="exactly one report per expected seed"):
        summarize_course_runs(reports[:-1], expected_seeds=SEEDS)
    with pytest.raises(ValueError, match="exactly one report per expected seed"):
        summarize_course_runs([*reports, reports[0]], expected_seeds=SEEDS)
    invalid = deepcopy(reports)
    invalid[0]["metrics"]["coverage"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        summarize_course_runs(invalid, expected_seeds=SEEDS)


def test_selection_rejects_test_or_rounded_display_metrics() -> None:
    reports = _reports_where_c1_has_one_outlier()
    reports["C0"][0]["split"] = "test"
    with pytest.raises(PermissionError, match="validation"):
        select_plan_c_candidate(_protocol(), reports)

    reports = _reports_where_c1_has_one_outlier()
    reports["C0"][0]["metrics_source"] = "rounded-display"
    with pytest.raises(ValueError, match="unrounded"):
        select_plan_c_candidate(_protocol(), reports)


def test_selection_rejects_validation_identity_drift() -> None:
    reports = _reports_where_c1_has_one_outlier()
    reports["C1"][1]["validation_manifest_sha256"] = "f" * 64

    with pytest.raises(ValueError, match="validation manifest"):
        select_plan_c_candidate(_protocol(), reports)


def test_ready_and_skipped_c2_require_exact_report_presence() -> None:
    reports = _reports_where_c1_has_one_outlier()
    with pytest.raises(ValueError, match="ready courses"):
        select_plan_c_candidate(_protocol(c2_status="ready"), reports)

    reports["C2"] = [_report("C2", seed, 0.5) for seed in SEEDS]
    with pytest.raises(ValueError, match="ready courses"):
        select_plan_c_candidate(_protocol(), reports)


def test_complete_metric_tie_uses_frozen_course_order() -> None:
    tied = {
        course: [_report(course, seed, 0.7) for seed in SEEDS]
        for course in ("C0", "C1")
    }

    selected = select_plan_c_candidate(_protocol(), tied)

    assert selected["winning_course"] == "C0"
    assert selected["winning_seed"] == 20260821
    assert selected["status"] == "frozen"
    body = dict(selected)
    embedded_hash = body.pop("selection_sha256")
    assert canonical_sha256(body) == embedded_hash


def test_selection_rejects_invalid_course_status_in_rehashed_protocol() -> None:
    protocol = _protocol()
    protocol.pop("protocol_sha256")
    protocol["courses"]["C1"]["status"] = "unknown"
    protocol["protocol_sha256"] = canonical_sha256(protocol)
    reports = {
        "C0": [_report("C0", seed, 0.7) for seed in SEEDS],
    }
    for report in reports["C0"]:
        report["protocol_sha256"] = protocol["protocol_sha256"]

    with pytest.raises(ValueError, match="course status"):
        select_plan_c_candidate(protocol, reports)
