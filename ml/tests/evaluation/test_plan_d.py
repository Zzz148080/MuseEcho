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
    build_plan_d_seed_replay_artifact,
    collect_plan_d_deep_predictions,
    collect_plan_d_legacy_predictions,
    decide_plan_d_development,
    decide_plan_d_replay_reports,
    evaluate_plan_d_replay,
    fit_plan_d_hybrid_calibration,
    load_plan_d_raw_predictions,
    replay_plan_d_seed,
    validate_plan_d_replay_identity,
    write_plan_d_raw_predictions,
)
from museecho_ml.labels import parse_annotation
from museecho_ml.postprocess.hybrid import HybridDecodeConfig
from museecho_ml.postprocess.hybrid_calibration import HybridCalibrationParameters
from museecho_ml.vocabulary import ChordVocabulary

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


def test_plan_d_replay_event_ratio_uses_reference_events() -> None:
    vocabulary = ChordVocabulary.default()
    root = np.full((2, len(vocabulary.root_labels)), -10.0, dtype=np.float64)
    quality = np.full(
        (2, len(vocabulary.quality_labels)), -10.0, dtype=np.float64
    )
    bass = np.full((2, len(vocabulary.bass_labels)), -10.0, dtype=np.float64)
    root[:, vocabulary.root_labels.index("C")] = 10.0
    quality[:, vocabulary.quality_labels.index("maj")] = 10.0
    bass[:, vocabulary.bass_labels.index("1")] = 10.0
    raw = RawTrackPrediction(
        track_id="fixture",
        dataset_id="guitarset",
        cover_group_id="group-a",
        split="validation",
        duration_seconds=1.0,
        frame_times=np.array([0.0, 0.5], dtype=np.float64),
        valid_mask=np.array([True, True]),
        root_logits=root,
        quality_logits=quality,
        bass_logits=bass,
        boundary_logits=np.full(2, -10.0, dtype=np.float64),
        reference=(
            ScoredChordInterval(0.0, 0.5, parse_annotation("C:maj")),
            ScoredChordInterval(0.5, 1.0, parse_annotation("D:min")),
        ),
        inference_wall_seconds=0.1,
    )
    calibration = HybridCalibrationParameters(
        global_quality_threshold=0.5,
        quality_thresholds=(("maj", 0.5),),
        quality_threshold_sources=(("maj", "quality-specific"),),
        known_threshold=0.5,
        bass_threshold=0.5,
        minimum_support_fraction=0.5,
    )
    config = HybridDecodeConfig(
        known_threshold=0.5,
        quality_thresholds=(),
        bass_threshold=0.5,
        minimum_support_fraction=0.5,
        minimum_event_seconds=0.0,
        hysteresis_frames=1,
        maximum_event_ratio=1.5,
    )

    second = replace(raw, track_id="fixture-2", cover_group_id="group-b")
    legacy = (
        ScoredChordInterval(0.0, 1.0, parse_annotation("C:maj"), confidence=0.6),
    )
    report = evaluate_plan_d_replay(
        (raw, second),
        legacy_by_track={
            "fixture": legacy,
            "fixture-2": legacy,
        },
        vocabulary=vocabulary,
        calibration=calibration,
        config=config,
    )

    assert report["event_ratio"] == 0.5
    assert report["aggregate"]["published"]["coverage"] == 1.0


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


def test_plan_d_replay_requires_same_manifest_vocabulary_and_checkpoint() -> None:
    protocol = {
        "development_splits": {
            "calibration": {"manifest_sha256": "a" * 64},
            "validation": {"manifest_sha256": "b" * 64},
        },
        "plan_c": {"vocabulary_sha256": "c" * 64},
        "legacy_algorithm": {"version": "chroma-triad-viterbi-v1"},
    }
    calibration = {
        "checkpoint_sha256": "d" * 64,
        "manifest_sha256": "a" * 64,
        "seed": 20260821,
        "split": "calibration",
        "vocabulary_sha256": "c" * 64,
    }
    validation = {
        **calibration,
        "manifest_sha256": "b" * 64,
        "split": "validation",
    }
    legacy = {
        "algorithm_version": "chroma-triad-viterbi-v1",
        "manifest_sha256": "b" * 64,
        "split": "validation",
    }

    identity = validate_plan_d_replay_identity(
        protocol=protocol,
        seed=20260821,
        expected_checkpoint_sha256="d" * 64,
        deep_calibration_identity=calibration,
        deep_validation_identity=validation,
        legacy_identity=legacy,
    )

    assert identity["manifest_sha256"] == "b" * 64
    assert identity["checkpoint_sha256"] == "d" * 64
    with pytest.raises(ValueError, match="replay identity drift"):
        validate_plan_d_replay_identity(
            protocol=protocol,
            seed=20260821,
            expected_checkpoint_sha256="d" * 64,
            deep_calibration_identity=calibration,
            deep_validation_identity={**validation, "manifest_sha256": "e" * 64},
            legacy_identity=legacy,
        )


def test_plan_d_hybrid_calibration_uses_calibration_groups() -> None:
    vocabulary = ChordVocabulary.default()
    root = np.full((2, len(vocabulary.root_labels)), -10.0, dtype=np.float64)
    quality = np.full(
        (2, len(vocabulary.quality_labels)), -10.0, dtype=np.float64
    )
    bass = np.full((2, len(vocabulary.bass_labels)), -10.0, dtype=np.float64)
    root[:, vocabulary.root_labels.index("C")] = 10.0
    quality[:, vocabulary.quality_labels.index("maj")] = 10.0
    bass[:, vocabulary.bass_labels.index("1")] = 10.0
    raw = RawTrackPrediction(
        track_id="fixture-1",
        dataset_id="guitarset",
        cover_group_id="group-1",
        split="calibration",
        duration_seconds=1.0,
        frame_times=np.array([0.0, 0.5], dtype=np.float64),
        valid_mask=np.array([True, True]),
        root_logits=root,
        quality_logits=quality,
        bass_logits=bass,
        boundary_logits=np.full(2, -10.0, dtype=np.float64),
        reference=(ScoredChordInterval(0.0, 1.0, parse_annotation("C:maj")),),
        inference_wall_seconds=0.1,
    )
    predictions = tuple(
        replace(raw, track_id=f"fixture-{index}", cover_group_id=f"group-{index}")
        for index in range(1, 4)
    )

    result = fit_plan_d_hybrid_calibration(
        predictions,
        vocabulary=vocabulary,
        minimum_precision=0.6,
        minimum_coverage=0.2,
        minimum_quality_groups=3,
    )

    assert result.source_for("maj") == "quality-specific"
    assert result.threshold_for("maj") > 0.99
    assert HybridCalibrationParameters.from_dict(result.to_dict()) == result


def test_seed_replay_artifact_is_hashed_path_free_and_binds_all_variants() -> None:
    calibration = HybridCalibrationParameters(
        global_quality_threshold=0.7,
        quality_thresholds=(("maj", 0.8),),
        quality_threshold_sources=(("maj", "quality-specific"),),
        known_threshold=0.7,
        bass_threshold=0.7,
        minimum_support_fraction=0.6,
    )
    legacy = _report(variant="legacy", exact=0.27)
    deep = _report(variant="deep-only", exact=0.25, seed=20260821)
    hybrid = _report(variant="hybrid", exact=0.31, seed=20260821)

    artifact = build_plan_d_seed_replay_artifact(
        protocol_sha256="f" * 64,
        seed=20260821,
        identity={
            "checkpoint_sha256": "d" * 64,
            "manifest_sha256": "a" * 64,
            "vocabulary_sha256": "b" * 64,
        },
        calibration=calibration,
        legacy=legacy,
        deep=deep,
        hybrid=hybrid,
    )

    assert artifact["status"] == "completed"
    assert set(artifact["reports"]) == {"deep-only", "hybrid", "legacy"}
    assert "path" not in str(artifact).lower()
    body = dict(artifact)
    embedded = body.pop("experiment_sha256")
    assert canonical_sha256(body) == embedded


def test_replay_decision_consumes_three_seed_artifacts_order_independently() -> None:
    calibration = HybridCalibrationParameters(
        global_quality_threshold=0.7,
        quality_thresholds=(),
        quality_threshold_sources=(),
        known_threshold=0.7,
        bass_threshold=0.7,
        minimum_support_fraction=0.6,
    )
    legacy = _report(variant="legacy", exact=0.27)
    artifacts = tuple(
        build_plan_d_seed_replay_artifact(
            protocol_sha256="f" * 64,
            seed=seed,
            identity={
                "checkpoint_sha256": str(index) * 64,
                "manifest_sha256": "a" * 64,
                "vocabulary_sha256": "b" * 64,
            },
            calibration=calibration,
            legacy=legacy,
            deep=_report(variant="deep-only", exact=0.25, seed=seed),
            hybrid=_report(variant="hybrid", exact=0.31, seed=seed),
        )
        for index, seed in enumerate((20260821, 20260822, 20260823), start=1)
    )

    first = decide_plan_d_replay_reports(
        tuple(reversed(artifacts)), gates=GATES, protocol_sha256="f" * 64
    )
    second = decide_plan_d_replay_reports(
        artifacts, gates=GATES, protocol_sha256="f" * 64
    )

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert first["status"] == "development-candidate-frozen"
    body = dict(first)
    embedded = body.pop("decision_sha256")
    assert canonical_sha256(body) == embedded


def test_replay_file_runner_rejects_old_test_identity_before_file_reads(
    tmp_path: Path,
) -> None:
    old_test_sha256 = (
        "06b92ce1bd46a1c432cefb9fe32f641095cfb081ac998e7772a66c20a686cddc"
    )

    with pytest.raises(ValueError, match="forbids the Plan C test manifest"):
        replay_plan_d_seed(
            protocol_path=tmp_path / "missing-protocol.json",
            seed=20260821,
            deep_calibration_path=tmp_path / "missing-calibration.npz",
            deep_validation_path=tmp_path / f"{old_test_sha256}.npz",
            legacy_validation_path=tmp_path / "missing-legacy.json",
            run_output_path=tmp_path / "run.json",
            public_output_path=tmp_path / "public.json",
        )


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
