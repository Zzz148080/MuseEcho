from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from museecho_ml.artifacts import canonical_json_bytes, canonical_sha256
from museecho_ml.evaluation.plan_d import (
    PlanDDevelopmentGates,
    decide_plan_d_development,
    evaluate_plan_d_replay,
)

GATES = PlanDDevelopmentGates()
DATASETS = ("guitarset", "rwc-popular", "schubert-winterreise")


def _report(
    *,
    variant: str,
    exact: float,
    seed: int | None = None,
    precision: float = 0.6,
    coverage: float = 0.2,
    event_ratio: float = 1.0,
    cpu: float = 10.0,
    dataset_delta: float = 0.0,
) -> dict:
    return {
        "split": "validation",
        "variant": variant,
        "seed": seed,
        "manifest_sha256": "a" * 64,
        "vocabulary_sha256": "b" * 64,
        "metrics": {
            "exact_vocabulary_wcsr": exact,
            "known_precision": precision,
            "coverage": coverage,
            "event_ratio": event_ratio,
            "five_minute_cpu_wall_seconds": cpu,
        },
        "datasets": {
            dataset: {"exact_vocabulary_wcsr": 0.27 + dataset_delta}
            for dataset in DATASETS
        },
    }


def _three_seed_reports(
    variant: str,
    exact: tuple[float, float, float],
    **overrides: float,
) -> tuple[dict, ...]:
    return tuple(
        _report(variant=variant, exact=value, seed=seed, **overrides)
        for seed, value in zip((20260821, 20260822, 20260823), exact, strict=True)
    )


def test_development_gate_passes_only_at_all_exact_boundaries() -> None:
    decision = decide_plan_d_development(
        legacy=_report(variant="legacy", exact=0.27),
        deep_by_seed=_three_seed_reports("deep-only", (0.24, 0.25, 0.26)),
        hybrid_by_seed=_three_seed_reports("hybrid", (0.30, 0.32, 0.35)),
        gates=GATES,
    )

    assert decision["status"] == "development-candidate-frozen"
    assert all(decision["checks"].values())
    body = dict(decision)
    embedded = body.pop("decision_sha256")
    assert canonical_sha256(body) == embedded


@pytest.mark.parametrize(
    ("field", "hybrid", "gates"),
    (
        ("minimum-exact", (0.29, 0.29, 0.29), GATES),
        ("legacy-gain", (0.30, 0.30, 0.30), GATES),
        ("deep-gain", (0.30, 0.30, 0.30), GATES),
        ("known-precision", (0.30, 0.32, 0.35), replace(GATES, minimum_known_precision=0.61)),
        ("coverage", (0.30, 0.32, 0.35), replace(GATES, minimum_coverage=0.21)),
        ("seed-span", (0.30, 0.32, 0.36), GATES),
        ("cpu", (0.30, 0.32, 0.35), replace(GATES, maximum_cpu_seconds=9.0)),
    ),
)
def test_each_failed_gate_prevents_candidate_freeze(
    field: str, hybrid: tuple[float, float, float], gates: PlanDDevelopmentGates
) -> None:
    deep = (0.28, 0.29, 0.30) if field == "deep-gain" else (0.24, 0.25, 0.26)
    decision = decide_plan_d_development(
        legacy=_report(variant="legacy", exact=0.29 if field == "legacy-gain" else 0.27),
        deep_by_seed=_three_seed_reports("deep-only", deep),
        hybrid_by_seed=_three_seed_reports("hybrid", hybrid),
        gates=gates,
    )

    assert decision["status"] != "development-candidate-frozen"


def test_decision_uses_explicit_retraining_and_data_first_states() -> None:
    legacy = _report(variant="legacy", exact=0.27)
    deep = _three_seed_reports("deep-only", (0.25, 0.25, 0.25))
    retrain = _three_seed_reports(
        "hybrid", (0.28, 0.28, 0.28), precision=0.4, coverage=0.1
    )
    data_first = _three_seed_reports(
        "hybrid", (0.25, 0.25, 0.25), precision=0.39, coverage=0.09
    )

    assert decide_plan_d_development(
        legacy=legacy, deep_by_seed=deep, hybrid_by_seed=retrain, gates=GATES
    )["status"] == "advance-to-retraining"
    assert decide_plan_d_development(
        legacy=legacy, deep_by_seed=deep, hybrid_by_seed=data_first, gates=GATES
    )["status"] == "data-first-required"


def test_decision_is_order_independent_and_rejects_identity_drift() -> None:
    legacy = _report(variant="legacy", exact=0.27)
    deep = _three_seed_reports("deep-only", (0.24, 0.25, 0.26))
    hybrid = _three_seed_reports("hybrid", (0.30, 0.32, 0.35))
    first = decide_plan_d_development(
        legacy=legacy, deep_by_seed=deep, hybrid_by_seed=hybrid, gates=GATES
    )
    second = decide_plan_d_development(
        legacy=legacy,
        deep_by_seed=tuple(reversed(deep)),
        hybrid_by_seed=tuple(reversed(hybrid)),
        gates=GATES,
    )
    assert canonical_json_bytes(first) == canonical_json_bytes(second)

    drifted = dict(hybrid[0])
    drifted["manifest_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="identity drift"):
        decide_plan_d_development(
            legacy=legacy,
            deep_by_seed=deep,
            hybrid_by_seed=(drifted, *hybrid[1:]),
            gates=GATES,
        )


def test_plan_d_replay_rejects_test_track_before_other_inputs() -> None:
    with pytest.raises(ValueError, match="forbids test split"):
        evaluate_plan_d_replay(
            (SimpleNamespace(split="test"),),
            legacy_by_track={},
            vocabulary=None,
            calibration=None,
            config=None,
        )
