from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from museecho_ml.artifacts import canonical_sha256
from museecho_ml.diagnostics.plan_d import (
    PlanDAuditTrack,
    audit_frame_alignment,
    build_plan_d_failure_audit,
    build_plan_d_stage_0_audit,
    run_plan_d_audit,
)
from museecho_ml.evaluation.deep_adapter import RawTrackPrediction
from museecho_ml.evaluation.metrics import ScoredChordInterval
from museecho_ml.labels import CanonicalChord, parse_annotation
from museecho_ml.postprocess.calibration import CalibrationParameters
from museecho_ml.vocabulary import ChordVocabulary

ML_ROOT = Path(__file__).resolve().parents[2]


def _interval(start: float, end: float, symbol: str, confidence: float = 1.0):
    return ScoredChordInterval(start, end, parse_annotation(symbol), confidence)


def _audit_track(
    *,
    track_id: str = "fixture",
    dataset_id: str = "dataset-a",
    group: str = "g1",
    seed: int | None = 20260821,
    split: str = "validation",
    frame_times: np.ndarray | None = None,
    reference: tuple[ScoredChordInterval, ...] | None = None,
    prediction: tuple[ScoredChordInterval, ...] | None = None,
) -> PlanDAuditTrack:
    return PlanDAuditTrack(
        track_id=track_id,
        dataset_id=dataset_id,
        cover_group_id=group,
        split=split,
        duration_seconds=2.0,
        frame_times=(
            np.asarray(frame_times, dtype=np.float64)
            if frame_times is not None
            else np.array([0.0, 0.5, 1.0, 1.5], dtype=np.float64)
        ),
        reference=reference
        or (_interval(0.0, 1.0, "C:maj"), _interval(1.0, 2.0, "D:min")),
        prediction=prediction
        or (_interval(0.0, 1.0, "C:maj"), _interval(1.0, 2.0, "D:min")),
        seed=seed,
    )


def test_audit_finds_boundary_offset_and_duration_weighted_quality_confusion() -> None:
    track = _audit_track(
        prediction=(
            _interval(0.0, 1.5, "C:maj", 0.8),
            _interval(1.5, 2.0, "D:maj", 0.6),
        )
    )

    report = build_plan_d_failure_audit(
        (track,), supported_qualities=("maj", "min")
    )

    assert report["alignment"]["maximum_boundary_frame_error_seconds"] == 0.0
    assert report["quality_confusion_seconds"]["min"]["maj"] == 0.5
    assert report["event_counts"] == {
        "prediction": 2,
        "reference": 2,
        "ratio": 1.0,
    }
    assert report["confidence_curve"]["duration_seconds"] == 2.0
    body = dict(report)
    embedded = body.pop("audit_sha256")
    assert canonical_sha256(body) == embedded


def test_alignment_infers_terminal_frame_edge_and_reports_real_offset() -> None:
    aligned = audit_frame_alignment(
        np.array([0.0, 0.5, 1.0, 1.5]),
        (_interval(0.0, 1.0, "C:maj"), _interval(1.0, 2.0, "D:min")),
    )
    shifted = audit_frame_alignment(
        np.array([0.1, 0.6, 1.1, 1.6]),
        (_interval(0.0, 1.0, "C:maj"), _interval(1.0, 2.0, "D:min")),
    )

    assert aligned == {
        "maximum_boundary_frame_error_seconds": 0.0,
        "mean_boundary_frame_error_seconds": 0.0,
    }
    assert shifted["maximum_boundary_frame_error_seconds"] == pytest.approx(0.1)


def test_audit_counts_independent_groups_and_stratifies_dataset_and_seed() -> None:
    first = _audit_track(group="g1", seed=20260821)
    second = _audit_track(
        track_id="fixture-2", dataset_id="dataset-b", group="g2", seed=20260822
    )

    report = build_plan_d_failure_audit(
        (second, first), supported_qualities=("maj", "min")
    )

    assert report["quality_support"]["min"]["cover_groups"] == 2
    assert list(report["datasets"]) == ["dataset-a", "dataset-b"]
    assert list(report["seeds"]) == ["20260821", "20260822"]
    assert report["cover_group_count"] == 2


def test_audit_rejects_test_overlap_missing_group_and_illegal_chord_state() -> None:
    base = _audit_track()
    with pytest.raises(ValueError, match="forbids test split"):
        build_plan_d_failure_audit(
            (replace(base, split="test"),), supported_qualities=("maj", "min")
        )
    with pytest.raises(ValueError, match="cover group"):
        build_plan_d_failure_audit(
            (replace(base, cover_group_id=""),), supported_qualities=("maj", "min")
        )

    overlap = (
        _interval(0.0, 1.5, "C:maj"),
        _interval(1.0, 2.0, "D:min"),
    )
    with pytest.raises(ValueError, match="overlap"):
        build_plan_d_failure_audit(
            (replace(base, prediction=overlap),), supported_qualities=("maj", "min")
        )

    illegal = ScoredChordInterval(
        0.0,
        2.0,
        CanonicalChord("C", "N", "1"),
    )
    with pytest.raises(ValueError, match="illegal chord state"):
        build_plan_d_failure_audit(
            (replace(base, prediction=(illegal,)),), supported_qualities=("maj", "min")
        )


def test_audit_cli_writes_path_free_immutable_report(tmp_path: Path) -> None:
    output = tmp_path / "audit.json"

    result = run_plan_d_audit(
        (_audit_track(),),
        supported_qualities=("maj", "min"),
        output_path=output,
    )

    assert result["status"] == "completed"
    assert "audio_path" not in output.read_text(encoding="utf-8")
    assert output.exists()
    body = dict(result)
    embedded = body.pop("audit_sha256")
    assert canonical_sha256(body) == embedded
    assert run_plan_d_audit(
        (_audit_track(),),
        supported_qualities=("maj", "min"),
        output_path=output,
    ) == result


def _raw_prediction(seed: int) -> RawTrackPrediction:
    vocabulary = ChordVocabulary.default()
    root = np.full((2, len(vocabulary.root_labels)), -10.0, dtype=np.float64)
    quality = np.full(
        (2, len(vocabulary.quality_labels)), -10.0, dtype=np.float64
    )
    bass = np.full((2, len(vocabulary.bass_labels)), -10.0, dtype=np.float64)
    root[:, vocabulary.root_labels.index("C")] = 10.0
    quality[:, vocabulary.quality_labels.index("maj")] = 10.0
    bass[:, vocabulary.bass_labels.index("1")] = 10.0
    return RawTrackPrediction(
        track_id="fixture",
        dataset_id="dataset-a",
        cover_group_id="g1",
        split="validation",
        duration_seconds=1.0,
        frame_times=np.array([0.0, 0.5], dtype=np.float64),
        valid_mask=np.array([True, True]),
        root_logits=root,
        quality_logits=quality,
        bass_logits=bass,
        boundary_logits=np.full(2, -10.0, dtype=np.float64),
        reference=(_interval(0.0, 1.0, "C:maj"),),
        inference_wall_seconds=float(seed - 20260820) / 10.0,
    )


def test_stage_0_audit_combines_legacy_and_three_deep_seeds_without_paths() -> None:
    seeds = (20260821, 20260822, 20260823)
    manifest_sha256 = "a" * 64
    vocabulary_sha256 = "b" * 64
    protocol = {
        "seeds": list(seeds),
        "development_splits": {
            "validation": {"manifest_sha256": manifest_sha256}
        },
        "plan_c": {"vocabulary_sha256": vocabulary_sha256},
        "legacy_algorithm": {"version": "chroma-triad-viterbi-v1"},
    }
    raw_by_seed = {seed: (_raw_prediction(seed),) for seed in seeds}
    identities = {
        seed: {
            "checkpoint_sha256": str(index) * 64,
            "manifest_sha256": manifest_sha256,
            "seed": seed,
            "split": "validation",
            "vocabulary_sha256": vocabulary_sha256,
        }
        for index, seed in enumerate(seeds, start=1)
    }
    calibration = CalibrationParameters(
        root_temperature=1.0,
        quality_temperature=1.0,
        bass_temperature=1.0,
        publication_threshold=0.5,
        boundary_threshold=0.5,
        minimum_event_seconds=0.0,
    )

    report = build_plan_d_stage_0_audit(
        protocol=protocol,
        vocabulary=ChordVocabulary.default(),
        split="validation",
        legacy_by_track={"fixture": (_interval(0.0, 1.0, "C:maj"),)},
        legacy_identity={
            "algorithm_version": "chroma-triad-viterbi-v1",
            "manifest_sha256": manifest_sha256,
            "split": "validation",
        },
        raw_by_seed=raw_by_seed,
        deep_identities=identities,
        calibration_by_seed={seed: calibration for seed in seeds},
    )

    assert report["status"] == "completed"
    assert all(report["checks"].values())
    assert set(report["variants"]) == {"deep-only", "legacy"}
    assert set(report["variants"]["deep-only"]["seeds"]) == {
        "20260821",
        "20260822",
        "20260823",
    }
    assert "path" not in str(report).lower()
    body = dict(report)
    embedded = body.pop("audit_sha256")
    assert canonical_sha256(body) == embedded


def test_stage_0_cli_rejects_test_before_opening_prediction_files(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "museecho_ml.diagnostics.plan_d",
            "--protocol",
            str(tmp_path / "missing-protocol.json"),
            "--vocabulary",
            str(tmp_path / "missing-vocabulary.json"),
            "--legacy-predictions",
            str(tmp_path / "missing-legacy.json"),
            "--deep-predictions",
            f"20260821={tmp_path / 'missing-1.npz'}",
            "--deep-predictions",
            f"20260822={tmp_path / 'missing-2.npz'}",
            "--deep-predictions",
            f"20260823={tmp_path / 'missing-3.npz'}",
            "--split",
            "test",
            "--output",
            str(tmp_path / "audit.json"),
        ],
        cwd=ML_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "forbids test split" in completed.stderr
