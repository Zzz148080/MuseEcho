from __future__ import annotations

import json
from pathlib import Path

from museecho_ml.artifacts import canonical_sha256

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PLAN_C_DOCS = REPOSITORY_ROOT / "docs" / "ml" / "plan-c"
PLAN_D_DOCS = REPOSITORY_ROOT / "docs" / "ml" / "plan-d"
EXPERIMENTS = REPOSITORY_ROOT / "docs" / "ml" / "experiments"


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


def test_completed_plan_c_decisions_recompute_their_hashes() -> None:
    for name, hash_field in (
        ("selection-v1.json", "selection_sha256"),
        ("test-receipt-v1.json", "receipt_sha256"),
        ("promotion-v1.json", "promotion_sha256"),
    ):
        payload = _read(name)
        body = dict(payload)
        embedded_hash = body.pop(hash_field)
        assert canonical_sha256(body) == embedded_hash

    assert _read("test-receipt-v1.json")["status"] == "consumed"
    promotion = _read("promotion-v1.json")
    assert promotion["status"] == "rejected"
    assert promotion["default_algorithm"] == "chroma-triad-viterbi-v1"


def test_plan_c_run_evidence_covers_six_runs_and_c2_skip() -> None:
    run_names = [
        f"plan-c-{course}-seed-{seed}.json"
        for course in ("C0", "C1")
        for seed in (20260821, 20260822, 20260823)
    ]
    for name in run_names:
        payload = json.loads((EXPERIMENTS / name).read_text(encoding="utf-8"))
        body = dict(payload)
        embedded_hash = body.pop("experiment_sha256")
        assert payload["status"] == "completed"
        assert canonical_sha256(body) == embedded_hash

    c2 = json.loads(
        (EXPERIMENTS / "plan-c-C2-seed-20260821.json").read_text(encoding="utf-8")
    )
    body = dict(c2)
    embedded_hash = body.pop("experiment_sha256")
    assert c2["status"] == "skipped"
    assert c2["reason_code"] == "score-supervision-not-approved"
    assert canonical_sha256(body) == embedded_hash

    frozen_test = json.loads(
        (EXPERIMENTS / "plan-c-frozen-test-v1.json").read_text(encoding="utf-8")
    )
    body = dict(frozen_test)
    embedded_hash = body.pop("experiment_sha256")
    assert canonical_sha256(body) == embedded_hash


def test_plan_d_protocol_does_not_change_plan_c_frozen_outcome() -> None:
    protocol = json.loads(
        (PLAN_D_DOCS / "protocol-v1.json").read_text(encoding="utf-8")
    )
    receipt = _read("test-receipt-v1.json")
    promotion = _read("promotion-v1.json")

    assert protocol["plan_c"]["selection_sha256"] == _read("selection-v1.json")[
        "selection_sha256"
    ]
    assert receipt["status"] == "consumed"
    assert promotion["status"] == "rejected"
    assert promotion["default_algorithm"] == "chroma-triad-viterbi-v1"
