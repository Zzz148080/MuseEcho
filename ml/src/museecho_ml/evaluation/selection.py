from __future__ import annotations

import math
import re
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

from museecho_ml.artifacts import canonical_sha256

_HIGHER_IS_BETTER = (
    "exact_vocabulary_wcsr",
    "public_quality_macro_f1",
    "published_known_precision",
    "coverage",
)
_CPU_METRIC = "five_minute_cpu_wall_seconds"
_METRICS = (*_HIGHER_IS_BETTER, _CPU_METRIC)
_IDENTITY_FIELDS = (
    "protocol_sha256",
    "vocabulary_sha256",
    "validation_manifest_sha256",
)
_ARTIFACT_FIELDS = (
    "checkpoint_sha256",
    "calibration_sha256",
    "threshold_sha256",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def summarize_course_runs(
    reports: Sequence[Mapping[str, Any]],
    *,
    expected_seeds: Sequence[int],
) -> dict[str, Any]:
    seeds = _validated_expected_seeds(expected_seeds)
    if not isinstance(reports, Sequence) or isinstance(reports, (str, bytes)):
        raise ValueError("course reports must be a sequence")
    by_seed: dict[int, Mapping[str, Any]] = {}
    course_id: str | None = None
    common_identities: dict[str, str] | None = None
    for report in reports:
        validated = _validated_report(report)
        seed = validated["seed"]
        if seed in by_seed:
            raise ValueError("course requires exactly one report per expected seed")
        by_seed[seed] = validated
        if course_id is None:
            course_id = validated["course_id"]
        elif course_id != validated["course_id"]:
            raise ValueError("course reports contain different course IDs")
        identities = {field: validated[field] for field in _IDENTITY_FIELDS}
        if common_identities is None:
            common_identities = identities
        elif common_identities != identities:
            raise ValueError("course reports contain split or hash mismatches")
    if set(by_seed) != set(seeds):
        raise ValueError("course requires exactly one report per expected seed")
    ordered = [by_seed[seed] for seed in seeds]
    return {
        "course_id": course_id,
        "seeds": list(seeds),
        "metrics": {
            metric: {
                "median": statistics.median(
                    report["metrics"][metric] for report in ordered
                ),
                "minimum": min(report["metrics"][metric] for report in ordered),
                "maximum": max(report["metrics"][metric] for report in ordered),
            }
            for metric in _METRICS
        },
        "runs": [
            {
                "seed": report["seed"],
                "checkpoint_sha256": report["checkpoint_sha256"],
                "calibration_sha256": report["calibration_sha256"],
                "threshold_sha256": report["threshold_sha256"],
                "metrics": dict(report["metrics"]),
            }
            for report in ordered
        ],
    }


def select_plan_c_candidate(
    protocol: Mapping[str, Any],
    reports_by_course: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    frozen_protocol = _validated_protocol(protocol)
    if not isinstance(reports_by_course, Mapping):
        raise ValueError("Plan C reports must map courses to validation reports")
    course_order = frozen_protocol["course_tie_order"]
    ready_courses = [
        course_id
        for course_id in course_order
        if frozen_protocol["courses"][course_id].get("status") == "ready"
    ]
    if set(reports_by_course) != set(ready_courses):
        raise ValueError("Plan C reports must match exactly the ready courses")
    validation_sha256 = frozen_protocol["real_splits"]["validation"][
        "manifest_sha256"
    ]
    test_binding = frozen_protocol["real_splits"]["test"]
    summaries: dict[str, dict[str, Any]] = {}
    for course_id in ready_courses:
        reports = reports_by_course[course_id]
        for report in reports:
            if not isinstance(report, Mapping):
                raise ValueError("Plan C validation report must be an object")
            if report.get("course_id") != course_id:
                raise ValueError("Plan C report course ID does not match")
            if report.get("split") != "validation":
                raise PermissionError("Plan C selection may read validation reports only")
            if report.get("corpus_role") != "real-gold":
                raise ValueError("Plan C validation reports must contain real-gold")
            if report.get("protocol_sha256") != frozen_protocol["protocol_sha256"]:
                raise ValueError("Plan C report protocol SHA-256 does not match")
            if report.get("vocabulary_sha256") != frozen_protocol[
                "vocabulary_sha256"
            ]:
                raise ValueError("Plan C report vocabulary SHA-256 does not match")
            if report.get("validation_manifest_sha256") != validation_sha256:
                raise ValueError("Plan C report validation manifest SHA-256 does not match")
        summaries[course_id] = summarize_course_runs(
            reports, expected_seeds=frozen_protocol["seeds"]
        )
    tie_index = {course_id: index for index, course_id in enumerate(course_order)}
    winning_course = min(
        ready_courses,
        key=lambda course_id: _course_rank(summaries[course_id], tie_index[course_id]),
    )
    winning_summary = summaries[winning_course]
    median_exact = winning_summary["metrics"]["exact_vocabulary_wcsr"]["median"]
    winning_run = min(
        winning_summary["runs"],
        key=lambda report: (
            abs(report["metrics"]["exact_vocabulary_wcsr"] - median_exact),
            report["seed"],
        ),
    )
    body = {
        "schema_version": 1,
        "selection_version": "plan-c-selection-v1",
        "status": "frozen",
        "protocol_sha256": frozen_protocol["protocol_sha256"],
        "vocabulary_sha256": frozen_protocol["vocabulary_sha256"],
        "validation_manifest_sha256": validation_sha256,
        "test_manifest_sha256": test_binding["manifest_sha256"],
        "test_split_sha256": test_binding["split_sha256"],
        "expected_seeds": list(frozen_protocol["seeds"]),
        "metric_order": list(_METRICS),
        "course_tie_order": list(course_order),
        "courses": {course_id: summaries[course_id] for course_id in ready_courses},
        "winning_course": winning_course,
        "winning_seed": winning_run["seed"],
        "checkpoint_sha256": winning_run["checkpoint_sha256"],
        "calibration_sha256": winning_run["calibration_sha256"],
        "threshold_sha256": winning_run["threshold_sha256"],
    }
    return {**body, "selection_sha256": canonical_sha256(body)}


def _validated_expected_seeds(values: Sequence[int]) -> tuple[int, ...]:
    if (
        not isinstance(values, Sequence)
        or isinstance(values, (str, bytes))
        or not values
        or any(type(seed) is not int or seed < 0 for seed in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError("expected seeds must be unique non-negative integers")
    return tuple(sorted(values))


def _validated_report(report: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(report, Mapping):
        raise ValueError("validation report must be an object")
    if report.get("split") != "validation":
        raise PermissionError("course summary may read validation reports only")
    if report.get("metrics_source") != "unrounded-validation":
        raise ValueError("course summary requires unrounded validation metrics")
    if not isinstance(report.get("course_id"), str) or not report["course_id"]:
        raise ValueError("validation report course ID is invalid")
    if type(report.get("seed")) is not int or report["seed"] < 0:
        raise ValueError("validation report seed is invalid")
    for field in (*_IDENTITY_FIELDS, *_ARTIFACT_FIELDS):
        if not isinstance(report.get(field), str) or _SHA256.fullmatch(report[field]) is None:
            raise ValueError(f"validation report {field} is invalid")
    metrics = report.get("metrics")
    if not isinstance(metrics, Mapping) or set(metrics) != set(_METRICS):
        raise ValueError("validation report metrics are invalid")
    if any(
        isinstance(metrics[metric], bool)
        or not isinstance(metrics[metric], (int, float))
        or not math.isfinite(metrics[metric])
        for metric in _METRICS
    ):
        raise ValueError("validation report metrics must be finite")
    return report


def _validated_protocol(protocol: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(protocol, Mapping):
        raise ValueError("Plan C protocol must be an object")
    body = dict(protocol)
    embedded_hash = body.pop("protocol_sha256", None)
    if not isinstance(embedded_hash, str) or canonical_sha256(body) != embedded_hash:
        raise ValueError("Plan C protocol SHA-256 does not match")
    if protocol.get("g1a_status") != "passed":
        raise PermissionError("Plan C selection requires G1a PASS")
    if protocol.get("selection_metrics") != list(_METRICS):
        raise ValueError("Plan C selection metric order is invalid")
    course_order = protocol.get("course_tie_order")
    courses = protocol.get("courses")
    if course_order != ["C0", "C1", "C2"] or not isinstance(courses, Mapping):
        raise ValueError("Plan C course tie order is invalid")
    if set(courses) != set(course_order):
        raise ValueError("Plan C protocol courses are invalid")
    if (
        not all(isinstance(courses[course_id], Mapping) for course_id in course_order)
        or courses["C0"].get("status") != "ready"
        or courses["C1"].get("status") != "ready"
        or courses["C2"].get("status") not in {"ready", "skipped"}
    ):
        raise ValueError("Plan C course status is invalid")
    seeds = _validated_expected_seeds(protocol.get("seeds", ()))
    if list(seeds) != protocol.get("seeds"):
        raise ValueError("Plan C protocol seeds must be sorted")
    real = protocol.get("real_splits")
    if (
        not isinstance(real, Mapping)
        or not isinstance(real.get("validation"), Mapping)
        or not isinstance(real.get("test"), Mapping)
    ):
        if isinstance(real, Mapping) and isinstance(real.get("validation"), Mapping):
            raise ValueError("Plan C test binding is missing")
        raise ValueError("Plan C validation binding is missing")
    validation = real["validation"]
    if validation.get("corpus_role") != "real-gold" or _SHA256.fullmatch(
        str(validation.get("manifest_sha256"))
    ) is None:
        raise ValueError("Plan C validation binding is invalid")
    test = real["test"]
    if (
        test.get("corpus_role") != "real-gold"
        or _SHA256.fullmatch(str(test.get("manifest_sha256"))) is None
        or _SHA256.fullmatch(str(test.get("split_sha256"))) is None
    ):
        raise ValueError("Plan C test binding is invalid")
    if _SHA256.fullmatch(str(protocol.get("vocabulary_sha256"))) is None:
        raise ValueError("Plan C vocabulary SHA-256 is invalid")
    return protocol


def _course_rank(summary: Mapping[str, Any], tie_index: int) -> tuple[Any, ...]:
    medians = summary["metrics"]
    return (
        *(-medians[metric]["median"] for metric in _HIGHER_IS_BETTER),
        medians[_CPU_METRIC]["median"],
        tie_index,
    )
