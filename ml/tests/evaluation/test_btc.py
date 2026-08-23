from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from museecho_ml.artifacts import canonical_sha256
from museecho_ml.candidates.btc_inference import (
    BtcEvent,
    BtcInferenceResult,
)
from museecho_ml.evaluation.btc import (
    decide_btc_continuation,
    load_btc_validation_manifest,
    run_btc_validation_experiment,
)
from museecho_ml.evaluation.report import EvaluationConfig
from museecho_ml.labels import CanonicalChord


@pytest.mark.parametrize("split", ["train", "calibration", "test"])
def test_btc_runner_rejects_every_non_validation_split_before_artifact_or_audio(
    tmp_path: Path, split: str
) -> None:
    manifest = tmp_path / f"{split}.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "corpus_role": "real-gold",
                "split": split,
                "tracks": [{"track_id": "must-not-be-opened"}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(PermissionError, match="validation only"):
        load_btc_validation_manifest(manifest)


def test_btc_collection_checks_split_before_roots_or_recognizer_creation(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "test.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "corpus_role": "real-gold",
                "split": "test",
                "tracks": [{"track_id": "must-not-be-opened"}],
            }
        ),
        encoding="utf-8",
    )
    created = False

    def create_recognizer():
        nonlocal created
        created = True
        raise AssertionError("recognizer must not be created")

    with pytest.raises(PermissionError, match="validation only"):
        run_btc_validation_experiment(
            manifest_path=manifest,
            dataset_roots={"guitarset": tmp_path / "missing"},
            config=EvaluationConfig(),
            btc_recognizer_factory=create_recognizer,
            legacy_recognize=lambda *_args: (),
            audio_loader=lambda _path: (_ for _ in ()).throw(
                AssertionError("audio must not be loaded")
            ),
            peak_rss_reader=lambda: 1,
            checkpoint_security_passed=True,
            artifact_identity_passed=True,
            deterministic_replay=True,
        )

    assert created is False


def _track(index: int, dataset_id: str, root: str, quality: str) -> dict[str, object]:
    return {
        "track_id": f"track-{index}",
        "dataset_id": dataset_id,
        "cover_group_id": f"{dataset_id}:group-{index}",
        "audio_path": f"track-{index}.raw",
        "duration_seconds": 1.0,
        "intervals": [
            {
                "start_seconds": 0.0,
                "end_seconds": 1.0,
                "root": root,
                "quality": quality,
                "bass": "1",
                "mapping_reason": None,
            }
        ],
    }


class _FakeBtcRecognizer:
    def recognize(self, samples: np.ndarray, sample_rate: int) -> BtcInferenceResult:
        index = int(samples[0])
        predicted = (
            CanonicalChord("C", "maj", "1"),
            CanonicalChord("D", "min", "1"),
            CanonicalChord("G", "maj", "1"),
        )[index]
        return BtcInferenceResult(
            events=(BtcEvent(0.0, samples.size / sample_rate, predicted, 0.9),),
            cpu_seconds=0.1,
            wall_seconds=0.2,
            frame_count=2,
        )


def test_validation_collection_pairs_candidates_on_identical_tracks(
    tmp_path: Path,
) -> None:
    datasets = ("guitarset", "rwc-popular", "schubert-winterreise")
    tracks = (
        _track(0, datasets[0], "C", "maj"),
        _track(1, datasets[1], "D", "min"),
        _track(2, datasets[2], "E", "maj"),
    )
    manifest_value = {
        "schema_version": 1,
        "corpus_role": "real-gold",
        "split": "validation",
        "tracks": list(tracks),
    }
    manifest = tmp_path / "validation.manifest.json"
    manifest.write_text(json.dumps(manifest_value), encoding="utf-8")
    roots: dict[str, Path] = {}
    for dataset_id in datasets:
        root = tmp_path / dataset_id
        root.mkdir()
        roots[dataset_id] = root
    for index, track in enumerate(tracks):
        (roots[str(track["dataset_id"])] / f"track-{index}.raw").write_bytes(b"audio")

    def audio_loader(path: Path) -> tuple[np.ndarray, int]:
        index = int(path.stem.split("-")[-1])
        return np.full(10, index, dtype=np.float32), 10

    def legacy_recognize(samples: np.ndarray, sample_rate: int):
        index = int(samples[0])
        predicted = (
            "A:maj",
            "F:maj",
            "G:min",
        )[index]
        return (
            SimpleNamespace(
                start_seconds=0.0,
                end_seconds=samples.size / sample_rate,
                symbol=predicted,
                confidence=0.8,
                algorithm="chroma-triad-viterbi-v1",
            ),
        )

    result = run_btc_validation_experiment(
        manifest_path=manifest,
        dataset_roots=roots,
        config=EvaluationConfig(),
        btc_recognizer_factory=_FakeBtcRecognizer,
        legacy_recognize=legacy_recognize,
        audio_loader=audio_loader,
        peak_rss_reader=lambda: 123_456,
        checkpoint_security_passed=True,
        artifact_identity_passed=True,
        deterministic_replay=True,
        bootstrap_resamples=100,
    )
    report = result["report"]

    assert report["manifest_sha256"] == canonical_sha256(manifest_value)
    assert report["track_count"] == 3
    assert report["dataset_track_counts"] == {
        "guitarset": 1,
        "rwc-popular": 1,
        "schubert-winterreise": 1,
    }
    assert report["candidates"]["btc"]["manifest_sha256"] == report["manifest_sha256"]
    assert report["candidates"]["legacy"]["manifest_sha256"] == report["manifest_sha256"]
    assert report["candidates"]["btc"]["track_ids"] == [
        "track-0",
        "track-1",
        "track-2",
    ]
    assert report["candidates"]["btc"]["duration_seconds"] == pytest.approx(3.0)
    for candidate in ("btc", "legacy"):
        evaluation = report["candidates"][candidate]["evaluation"]
        assert set(evaluation["datasets"]) == set(datasets)
        assert "exact_quality" in evaluation["aggregate"]["weighted_scores"]
        assert "root" in evaluation["aggregate"]["weighted_scores"]
        assert "f1" in evaluation["aggregate"]["boundary"]
    assert report["candidates"]["btc"]["unsupported_quality_seconds"] == 0.0
    assert report["candidates"]["btc"]["event_ratio"] == pytest.approx(1.0)
    assert report["candidates"]["btc"]["operational"]["cpu_seconds"] == pytest.approx(
        0.3
    )
    assert report["candidates"]["btc"]["operational"][
        "five_minute_cpu_seconds"
    ] == pytest.approx(30.0)
    assert report["operational"]["peak_rss_bytes"] == 123_456
    assert report["comparison"]["dataset_exact_wins"] == 2
    assert report["comparison"]["track_identity_match"] is True
    assert report["comparison"]["paired_bootstrap"]["group_count"] == 3
    assert report["comparison"]["paired_bootstrap"]["seed"] == 20260823
    assert len(result["prediction_rows"]) == 3


def _passing_report() -> dict[str, object]:
    evaluation = {
        "aggregate": {
            "weighted_scores": {"exact_quality": 0.5, "root": 0.7},
            "boundary": {"f1": 0.8},
        }
    }
    return {
        "confidence_status": "uncalibrated-diagnostic-only",
        "calibration": {"calibrated": False},
        "candidates": {
            "btc": {
                "evaluation": deepcopy(evaluation),
                "operational": {
                    "cpu_seconds": 1.0,
                    "five_minute_cpu_seconds": 2.0,
                },
            },
            "legacy": {
                "evaluation": {
                    "aggregate": {
                        "weighted_scores": {"exact_quality": 0.2, "root": 0.6},
                        "boundary": {"f1": 0.7},
                    }
                }
            },
        },
        "comparison": {
            "dataset_exact_wins": 2,
            "deterministic_prediction_replay": True,
            "track_identity_match": True,
        },
        "security": {
            "checkpoint_security_passed": True,
            "artifact_identity_passed": True,
        },
    }


def test_btc_gate_requires_two_dataset_wins_and_no_root_or_boundary_regression() -> None:
    decision = decide_btc_continuation(_passing_report())
    assert decision["status"] == "continue-btc-research"

    one_dataset = _passing_report()
    one_dataset["comparison"]["dataset_exact_wins"] = 1  # type: ignore[index]
    decision = decide_btc_continuation(one_dataset)
    assert decision["status"] == "btc-not-selected"
    assert "at_least_two_dataset_exact_wins" in decision["failed_predicates"]

    root_regression = _passing_report()
    root_regression["candidates"]["btc"]["evaluation"]["aggregate"][  # type: ignore[index]
        "weighted_scores"
    ]["root"] = 0.5
    assert decide_btc_continuation(root_regression)["status"] == "btc-not-selected"


@pytest.mark.parametrize("mutation", ["nan", "missing", "calibrated", "tracks"])
def test_btc_gate_rejects_malformed_or_non_diagnostic_reports(mutation: str) -> None:
    report = _passing_report()
    if mutation == "nan":
        report["candidates"]["btc"]["evaluation"]["aggregate"][  # type: ignore[index]
            "weighted_scores"
        ]["exact_quality"] = float("nan")
    elif mutation == "missing":
        del report["security"]
    elif mutation == "calibrated":
        report["calibration"]["calibrated"] = True  # type: ignore[index]
    else:
        report["comparison"]["track_identity_match"] = False  # type: ignore[index]

    with pytest.raises(ValueError, match="BTC continuation report"):
        decide_btc_continuation(report)
