from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TypeVar

from museecho_ml.artifacts import canonical_sha256
from museecho_ml.data.registry import DatasetRegistry

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SELECTION_IDENTITIES = (
    "protocol_sha256",
    "vocabulary_sha256",
    "calibration_sha256",
    "threshold_sha256",
    "checkpoint_sha256",
    "test_manifest_sha256",
)
_ResultT = TypeVar("_ResultT")


class FrozenTestSession:
    __slots__ = ("receipt", "_manifest", "_accessed")

    receipt: dict[str, Any]
    _manifest: dict[str, Any]
    _accessed: bool

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("use open_frozen_test_session to create a frozen test session")

    @classmethod
    def _create(
        cls, *, receipt: dict[str, Any], manifest: dict[str, Any]
    ) -> FrozenTestSession:
        session = object.__new__(cls)
        session.receipt = receipt
        session._manifest = manifest
        session._accessed = False
        return session

    def evaluate_once(
        self, evaluator: Callable[[Mapping[str, Any]], _ResultT]
    ) -> _ResultT:
        if self._accessed:
            raise PermissionError("frozen test is already accessed")
        self._accessed = True
        return evaluator(self._manifest)


def open_frozen_test_session(
    *,
    selection: Mapping[str, Any],
    manifest_path: Path,
    access_marker_path: Path,
) -> FrozenTestSession:
    frozen = _validated_selection(selection)
    marker = access_marker_path.resolve()
    try:
        descriptor = os.open(
            marker,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError as error:
        raise PermissionError("frozen test is already accessed") from error
    except OSError as error:
        raise ValueError("frozen test access marker cannot be created") from error
    with os.fdopen(descriptor, "wb") as target:
        target.write(b"plan-c-frozen-test-access-started-v1\n")
        target.flush()
        os.fsync(target.fileno())
    try:
        manifest = json.loads(
            manifest_path.resolve(strict=True).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("frozen test manifest is unreadable") from error
    receipt = authorize_frozen_test(frozen, manifest, existing_receipt=None)
    return FrozenTestSession._create(receipt=receipt, manifest=manifest)


def authorize_frozen_test(
    selection: Mapping[str, Any],
    test_manifest: Mapping[str, Any],
    *,
    existing_receipt: Mapping[str, Any] | None,
) -> dict[str, Any]:
    frozen = _validated_selection(selection)
    if existing_receipt is not None:
        raise PermissionError("frozen test receipt is already consumed")
    if not isinstance(test_manifest, Mapping):
        raise ValueError("frozen test manifest must be an object")
    if test_manifest.get("split") != "test":
        raise PermissionError("frozen test authorization requires the test split")
    if test_manifest.get("corpus_role") != "real-gold":
        raise ValueError("frozen test manifest must contain real-gold")
    manifest_sha256 = canonical_sha256(test_manifest)
    if (
        manifest_sha256 != frozen["test_manifest_sha256"]
        or test_manifest.get("split_sha256") != frozen.get("test_split_sha256")
    ):
        raise ValueError("frozen test manifest identity does not match selection")
    body = {
        "schema_version": 1,
        "receipt_version": "plan-c-test-receipt-v1",
        "status": "authorized",
        "selection_sha256": frozen["selection_sha256"],
        "test_manifest_sha256": manifest_sha256,
        "test_split_sha256": frozen["test_split_sha256"],
        **{field: frozen[field] for field in _SELECTION_IDENTITIES[:-1]},
    }
    return {**body, "receipt_sha256": canonical_sha256(body)}


def consume_frozen_test(
    receipt: Mapping[str, Any],
    *,
    candidate_report_sha256: str,
    legacy_report_sha256: str,
) -> dict[str, Any]:
    frozen = _validated_receipt(receipt)
    if frozen.get("status") != "authorized":
        raise PermissionError("frozen test receipt is already consumed")
    for value in (candidate_report_sha256, legacy_report_sha256):
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise ValueError("frozen test report SHA-256 is invalid")
    body = dict(frozen)
    body.pop("receipt_sha256")
    body["status"] = "consumed"
    body["candidate_report_sha256"] = candidate_report_sha256
    body["legacy_report_sha256"] = legacy_report_sha256
    return {**body, "receipt_sha256": canonical_sha256(body)}


def decide_model_promotion(
    *,
    selection: Mapping[str, Any],
    candidate: Mapping[str, Any],
    legacy: Mapping[str, Any],
    operational: Mapping[str, Any],
    registry: DatasetRegistry,
) -> dict[str, Any]:
    frozen = _validated_selection(selection)
    if not isinstance(candidate, Mapping) or not isinstance(legacy, Mapping):
        raise ValueError("promotion reports must be objects")
    if not isinstance(operational, Mapping):
        raise ValueError("promotion operational evidence must be an object")
    for field in (
        "test_manifest_sha256",
        "vocabulary_sha256",
        "calibration_sha256",
        "threshold_sha256",
        "checkpoint_sha256",
    ):
        if candidate.get(field) != frozen[field]:
            name = field.removesuffix("_sha256").replace("_", " ")
            raise ValueError(f"candidate {name} identity does not match selection")
    if legacy.get("test_manifest_sha256") != frozen["test_manifest_sha256"]:
        raise ValueError("legacy test manifest identity does not match selection")
    candidate_metrics = _finite_metrics(
        candidate.get("metrics"),
        (
            "majmin_wcsr",
            "exact_vocabulary_wcsr",
            "seventh_quality_macro_f1",
            "published_known_precision",
            "coverage",
            "ece",
        ),
        "candidate",
    )
    legacy_metrics = _finite_metrics(
        legacy.get("metrics"),
        ("majmin_wcsr", "exact_vocabulary_wcsr"),
        "legacy",
    )
    numeric_operational = _finite_metrics(
        operational,
        (
            "onnx_max_abs_probability_error",
            "chord_five_minute_wall_seconds",
            "chord_peak_rss_bytes",
            "full_five_minute_wall_seconds",
            "full_peak_rss_bytes",
        ),
        "operational",
    )
    for field in ("deterministic_events", "onnx_events_identical"):
        if type(operational.get(field)) is not bool:
            raise ValueError(f"operational {field} must be boolean")
    checks = {
        "majmin-not-below-legacy": (
            candidate_metrics["majmin_wcsr"] >= legacy_metrics["majmin_wcsr"]
        ),
        "exact-strictly-above-legacy": (
            candidate_metrics["exact_vocabulary_wcsr"]
            > legacy_metrics["exact_vocabulary_wcsr"]
        ),
        "seventh-macro-f1": candidate_metrics["seventh_quality_macro_f1"] >= 0.55,
        "published-known-precision": (
            candidate_metrics["published_known_precision"] >= 0.85
        ),
        "coverage": candidate_metrics["coverage"] >= 0.65,
        "ece": candidate_metrics["ece"] <= 0.08,
        "deterministic-events": operational["deterministic_events"] is True,
        "onnx-probability-parity": (
            numeric_operational["onnx_max_abs_probability_error"] <= 1e-4
        ),
        "onnx-event-parity": operational["onnx_events_identical"] is True,
        "chord-cpu-wall": (
            numeric_operational["chord_five_minute_wall_seconds"] <= 30.0
        ),
        "chord-peak-rss": (
            numeric_operational["chord_peak_rss_bytes"] <= 2 * 1024**3
        ),
        "full-analysis-wall": (
            numeric_operational["full_five_minute_wall_seconds"] <= 90.0
        ),
        "full-analysis-peak-rss": (
            numeric_operational["full_peak_rss_bytes"] <= 4 * 1024**3
        ),
    }
    dataset_ids = candidate.get("training_dataset_ids")
    if (
        not isinstance(dataset_ids, list)
        or not dataset_ids
        or any(not isinstance(value, str) or not value for value in dataset_ids)
        or len(set(dataset_ids)) != len(dataset_ids)
    ):
        raise ValueError("candidate training dataset IDs are invalid")
    license_checks: dict[str, bool] = {}
    for dataset_id in sorted(dataset_ids):
        try:
            registry.require_weights_distribution_approval(dataset_id)
        except (KeyError, PermissionError):
            license_checks[dataset_id] = False
        else:
            license_checks[dataset_id] = True
    checks.update(
        {
            f"weights-distribution:{dataset_id}": passed
            for dataset_id, passed in license_checks.items()
        }
    )
    failed = [name for name, passed in checks.items() if not passed]
    if not all(license_checks.values()):
        failed.append("weights-distribution-not-approved")
    status = "passed" if not failed else "rejected"
    body = {
        "schema_version": 1,
        "promotion_version": "plan-c-promotion-v1",
        "status": status,
        "selection_sha256": frozen["selection_sha256"],
        "checks": checks,
        "license_checks": license_checks,
        "failed_reason_codes": failed,
        "strong_result_target_met": (
            candidate_metrics["exact_vocabulary_wcsr"]
            - legacy_metrics["exact_vocabulary_wcsr"]
            >= 0.08
        ),
        "default_algorithm": (
            "deep-chord-plan-c-v1"
            if status == "passed"
            else "chroma-triad-viterbi-v1"
        ),
    }
    return {**body, "promotion_sha256": canonical_sha256(body)}


def _validated_selection(selection: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(selection, Mapping) or selection.get("status") != "frozen":
        raise ValueError("Plan C selection must be frozen")
    body = dict(selection)
    embedded_hash = body.pop("selection_sha256", None)
    if not isinstance(embedded_hash, str) or canonical_sha256(body) != embedded_hash:
        raise ValueError("Plan C selection SHA-256 does not match")
    for field in _SELECTION_IDENTITIES:
        if not isinstance(selection.get(field), str) or _SHA256.fullmatch(
            selection[field]
        ) is None:
            raise ValueError(f"Plan C selection {field} is invalid")
    if not isinstance(selection.get("test_split_sha256"), str) or _SHA256.fullmatch(
        selection["test_split_sha256"]
    ) is None:
        raise ValueError("Plan C selection test split SHA-256 is invalid")
    return selection


def _validated_receipt(receipt: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(receipt, Mapping):
        raise ValueError("frozen test receipt must be an object")
    body = dict(receipt)
    embedded_hash = body.pop("receipt_sha256", None)
    if not isinstance(embedded_hash, str) or canonical_sha256(body) != embedded_hash:
        raise ValueError("frozen test receipt SHA-256 does not match")
    return receipt


def _finite_metrics(
    value: Any, fields: tuple[str, ...], name: str
) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} metrics must be an object")
    result: dict[str, float] = {}
    for field in fields:
        item = value.get(field)
        if (
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(item)
        ):
            raise ValueError(f"{name} metrics must be finite")
        result[field] = float(item)
    return result
