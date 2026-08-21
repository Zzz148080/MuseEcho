from __future__ import annotations

import json
from pathlib import Path

from museecho_ml.artifacts import canonical_sha256

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PLAN_C_DOCS = REPOSITORY_ROOT / "docs" / "ml" / "plan-c"


def _read(name: str) -> dict:
    return json.loads((PLAN_C_DOCS / name).read_text(encoding="utf-8"))


def test_committed_plan_c_artifacts_recompute_their_hashes() -> None:
    hash_fields = {
        "g1-status-v1.json": "g1_report_sha256",
        "vocabulary-v1.json": "vocabulary_sha256",
        "protocol-v1.json": "protocol_sha256",
    }

    for name, hash_field in hash_fields.items():
        payload = _read(name)
        body = dict(payload)
        embedded_hash = body.pop(hash_field)
        assert canonical_sha256(body) == embedded_hash


def test_protocol_keeps_route_a_and_c2_skip_as_separate_facts() -> None:
    protocol = _read("protocol-v1.json")

    assert protocol["historical_route"] == "A"
    assert protocol["courses"]["C1"]["status"] == "ready"
    assert protocol["courses"]["C2"] == {
        "status": "skipped",
        "reason_code": "score-supervision-not-approved",
    }


def test_public_g1_reports_g1a_and_g1b_independently() -> None:
    report = _read("g1-status-v1.json")

    assert report["g1a"]["status"] == "passed"
    assert report["g1b"]["status"] == "not-met"
