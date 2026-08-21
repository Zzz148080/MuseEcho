from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from museecho_ml.artifacts import canonical_json_bytes, canonical_sha256
from museecho_ml.evaluation.deep_adapter import RawTrackPrediction
from museecho_ml.evaluation.metrics import ScoredChordInterval
from museecho_ml.evaluation.plan_d import (
    PlanDDevelopmentGates,
    collect_plan_d_deep_predictions,
    collect_plan_d_legacy_predictions,
    decide_plan_d_development,
    evaluate_plan_d_replay,
    load_plan_d_raw_predictions,
    write_plan_d_raw_predictions,
)
from museecho_ml.labels import parse_annotation

GATES = PlanDDevelopmentGates()
DATASETS = ("guitarset", "rwc-popular", "schubert-winterreise")
ML_ROOT = Path(__file__).resolve().parents[2]


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


def test_plan_d_collection_rejects_test_before_reading_inputs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="forbids test split"):
        collect_plan_d_deep_predictions(
            protocol_path=tmp_path / "missing-protocol.json",
            split="test",
            manifest_path=tmp_path / "missing-manifest.json",
            checkpoint_path=tmp_path / "missing-checkpoint.pt",
            seed=20260821,
            output_path=tmp_path / "raw.npz",
        )
    with pytest.raises(ValueError, match="forbids test split"):
        collect_plan_d_legacy_predictions(
            protocol_path=tmp_path / "missing-protocol.json",
            split="test",
            manifest_path=tmp_path / "missing-manifest.json",
            output_path=tmp_path / "legacy.json",
        )


def test_plan_d_raw_prediction_npz_round_trip_is_pickle_free(tmp_path: Path) -> None:
    prediction = RawTrackPrediction(
        track_id="fixture",
        dataset_id="guitarset",
        cover_group_id="group-a",
        split="validation",
        duration_seconds=1.0,
        frame_times=np.array([0.0, 0.5], dtype=np.float64),
        valid_mask=np.array([True, True]),
        root_logits=np.zeros((2, 14), dtype=np.float64),
        quality_logits=np.zeros((2, 10), dtype=np.float64),
        bass_logits=np.zeros((2, 14), dtype=np.float64),
        boundary_logits=np.zeros(2, dtype=np.float64),
        reference=(
            ScoredChordInterval(0.0, 1.0, parse_annotation("C:maj")),
        ),
        inference_wall_seconds=0.25,
    )
    output = tmp_path / "raw.npz"

    write_plan_d_raw_predictions(
        output,
        (prediction,),
        seed=20260821,
        manifest_sha256="a" * 64,
        checkpoint_sha256="b" * 64,
        vocabulary_sha256="c" * 64,
    )
    loaded, identity = load_plan_d_raw_predictions(output)

    assert identity == {
        "checkpoint_sha256": "b" * 64,
        "manifest_sha256": "a" * 64,
        "seed": 20260821,
        "split": "validation",
        "vocabulary_sha256": "c" * 64,
    }
    assert loaded[0].track_id == prediction.track_id
    assert loaded[0].reference == prediction.reference
    np.testing.assert_array_equal(loaded[0].root_logits, prediction.root_logits)


def test_plan_d_collect_deep_cli_rejects_test_before_missing_files(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "museecho_ml.evaluation.plan_d",
            "collect-deep",
            "--protocol",
            str(tmp_path / "missing-protocol.json"),
            "--split",
            "test",
            "--manifest",
            str(tmp_path / "missing-manifest.json"),
            "--checkpoint",
            str(tmp_path / "missing-checkpoint.pt"),
            "--seed",
            "20260821",
            "--output",
            str(tmp_path / "raw.npz"),
        ],
        cwd=ML_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "forbids test split" in completed.stderr
