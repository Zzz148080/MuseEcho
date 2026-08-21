from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from museecho_ml.artifacts import canonical_json_bytes, canonical_sha256

PLAN_C_TEST_MANIFEST_SHA256 = (
    "06b92ce1bd46a1c432cefb9fe32f641095cfb081ac998e7772a66c20a686cddc"
)
_DEVELOPMENT_SPLITS = frozenset({"train", "calibration", "validation"})


def load_plan_d_protocol(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Plan D protocol is unreadable strict JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("Plan D protocol must contain an object")
    if "test" in canonical_json_bytes(payload).decode("utf-8"):
        raise ValueError("Plan D protocol forbids test identity")
    if (
        payload.get("schema_version") != 1
        or payload.get("protocol_version") != "plan-d-protocol-v1"
    ):
        raise ValueError("Plan D protocol version is unsupported")
    if set(payload.get("development_splits", {})) != _DEVELOPMENT_SPLITS:
        raise ValueError("Plan D protocol development splits are invalid")
    body = dict(payload)
    embedded_hash = body.pop("protocol_sha256", None)
    if not isinstance(embedded_hash, str) or canonical_sha256(body) != embedded_hash:
        raise ValueError("Plan D protocol SHA-256 mismatch")
    return payload


def load_plan_d_development_manifest(
    path: Path,
    *,
    expected_split: str,
    expected_sha256: str,
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    if expected_split not in _DEVELOPMENT_SPLITS:
        raise ValueError("Plan D forbids test split")
    if expected_sha256 == PLAN_C_TEST_MANIFEST_SHA256:
        raise ValueError("Plan D forbids the Plan C test manifest")
    allowed = protocol["development_splits"][expected_split]["manifest_sha256"]
    if expected_sha256 != allowed:
        raise ValueError("Plan D development manifest identity drift")
    try:
        payload = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Plan D development manifest is unreadable strict JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("Plan D development manifest must contain an object")
    if canonical_sha256(payload) != expected_sha256:
        raise ValueError("Plan D development manifest SHA-256 mismatch")
    if payload.get("split") != expected_split:
        raise ValueError("Plan D development manifest split drift")
    return payload
