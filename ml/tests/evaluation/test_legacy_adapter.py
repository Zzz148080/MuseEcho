from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from museecho_ml.evaluation.legacy_adapter import (
    evaluate_legacy_manifest,
    load_evaluation_config,
    replay_legacy_protocol,
    run_legacy_protocol,
)
from museecho_ml.evaluation.report import EvaluationConfig


@dataclass(frozen=True)
class _LegacyEvent:
    symbol: str | None
    start_seconds: float
    end_seconds: float
    confidence: float | None
    algorithm: str = "chroma-triad-viterbi-v1"


ML_ROOT = Path(__file__).resolve().parents[2]


def _manifest(split: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "dataset_id": "real-gold-combined",
        "corpus_role": "real-gold",
        "split": split,
        "split_sha256": "split-sha",
        "policy_sha256": "policy-sha",
        "tracks": [
            {
                "dataset_id": "fixture",
                "source_track_id": "track-a",
                "track_id": "fixture:track-a",
                "work_id": "fixture:work-a",
                "cover_group_id": "fixture:group-a",
                "artist_id": "fixture:artist-a",
                "audio_path": "audio/track-a.wav",
                "annotation_path": "annotations/track-a.json",
                "duration_seconds": 2.0,
                "audio_sha256": "audio-sha",
                "annotation_sha256": "annotation-sha",
                "intervals": [
                    {
                        "start_seconds": 0.5,
                        "end_seconds": 1.0,
                        "root": "C",
                        "quality": "maj",
                        "bass": "1",
                        "mapping_reason": None,
                    },
                    {
                        "start_seconds": 1.0,
                        "end_seconds": 2.0,
                        "root": "G",
                        "quality": "7",
                        "bass": "1",
                        "mapping_reason": None,
                    },
                ],
            }
        ],
    }


def test_evaluate_legacy_manifest_builds_replayable_path_free_report(
    tmp_path: Path,
) -> None:
    dataset_root = tmp_path / "fixture"
    audio_path = dataset_root / "audio" / "track-a.wav"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"fixture-audio")

    def load_audio(path: Path) -> tuple[np.ndarray, int]:
        assert path.read_bytes() == b"fixture-audio"
        return np.zeros(20, dtype=np.float32), 10

    def recognize(samples: np.ndarray, sample_rate: int) -> tuple[_LegacyEvent, ...]:
        assert samples.shape == (20,)
        assert sample_rate == 10
        return (
            _LegacyEvent(None, 0.0, 0.5, None),
            _LegacyEvent("C", 0.5, 1.0, 0.9),
            _LegacyEvent("G", 1.0, 2.0, 0.9),
        )

    result = evaluate_legacy_manifest(
        _manifest("validation"),
        dataset_roots={"fixture": dataset_root},
        config=EvaluationConfig(publication_threshold=0.85),
        recognize=recognize,
        audio_loader=load_audio,
    )

    assert result["report"]["algorithm_version"] == "chroma-triad-viterbi-v1"
    assert result["report"]["manifest_split"] == "validation"
    assert result["report"]["evaluation"]["aggregate"]["weighted_scores"] == {
        "root": 0.75,
        "majmin": 1.0,
        "triads": 1.0,
        "sevenths": pytest.approx(1 / 3),
        "exact_quality": 0.25,
    }
    assert len(result["report"]["predictions_sha256"]) == 64
    assert result["predictions"][0]["events"][0]["quality"] == "X"
    assert "audio_path" not in json.dumps(result["report"])


def test_evaluate_legacy_manifest_refuses_training_split(tmp_path: Path) -> None:
    with pytest.raises(PermissionError, match="train"):
        evaluate_legacy_manifest(
            _manifest("train"),
            dataset_roots={"fixture": tmp_path},
            config=EvaluationConfig(),
            recognize=lambda _samples, _sample_rate: (),
            audio_loader=lambda _path: (np.zeros(1, dtype=np.float32), 1),
        )


def test_evaluate_legacy_manifest_ignores_subnanosecond_annotation_tail(
    tmp_path: Path,
) -> None:
    manifest = _manifest("validation")
    first = manifest["tracks"][0]
    first["duration_seconds"] = 250.0
    first["intervals"] = [
        {
            "start_seconds": 0.0,
            "end_seconds": 250.0,
            "root": "C",
            "quality": "maj",
            "bass": "1",
            "mapping_reason": None,
        }
    ]
    second = json.loads(json.dumps(first))
    second.update(
        {
            "source_track_id": "track-b",
            "track_id": "fixture:track-b",
            "work_id": "fixture:work-b",
            "cover_group_id": "fixture:group-b",
            "audio_path": "audio/track-b.wav",
            "duration_seconds": 14.4,
            "intervals": [
                {
                    "start_seconds": 0.0,
                    "end_seconds": 14.399999999999977,
                    "root": "C",
                    "quality": "maj",
                    "bass": "1",
                    "mapping_reason": None,
                }
            ],
        }
    )
    manifest["tracks"].append(second)
    dataset_root = tmp_path / "fixture"
    audio_dir = dataset_root / "audio"
    audio_dir.mkdir(parents=True)
    (audio_dir / "track-a.wav").write_bytes(b"a")
    (audio_dir / "track-b.wav").write_bytes(b"b")

    def load_audio(path: Path) -> tuple[np.ndarray, int]:
        size = 2500 if path.name == "track-a.wav" else 144
        return np.zeros(size, dtype=np.float32), 10

    def recognize(samples: np.ndarray, sample_rate: int) -> tuple[_LegacyEvent, ...]:
        return (_LegacyEvent("C", 0.0, samples.size / sample_rate, 0.9),)

    result = evaluate_legacy_manifest(
        manifest,
        dataset_roots={"fixture": dataset_root},
        config=EvaluationConfig(),
        recognize=recognize,
        audio_loader=load_audio,
    )

    assert result["report"]["evaluation"]["track_count"] == 2
    assert result["report"]["evaluation"]["aggregate"]["weighted_scores"][
        "exact_quality"
    ] == pytest.approx(1.0)


def test_run_legacy_protocol_writes_immutable_commit_bound_artifacts(
    tmp_path: Path,
) -> None:
    dataset_root = tmp_path / "fixture"
    audio_path = dataset_root / "audio" / "track-a.wav"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"fixture-audio")

    def load_audio(path: Path) -> tuple[np.ndarray, int]:
        path.read_bytes()
        return np.zeros(20, dtype=np.float32), 10

    def recognize(_samples: np.ndarray, _sample_rate: int) -> tuple[_LegacyEvent, ...]:
        return (
            _LegacyEvent(None, 0.0, 0.5, None),
            _LegacyEvent("C", 0.5, 1.0, 0.9),
            _LegacyEvent("G", 1.0, 2.0, 0.9),
        )

    predictions_path = tmp_path / "legacy-predictions.jsonl"
    report_path = tmp_path / "legacy-baseline-v1.json"
    markdown_path = tmp_path / "legacy-baseline-v1.md"
    manifests = {split: _manifest(split) for split in ("validation", "test")}

    first = run_legacy_protocol(
        manifests,
        dataset_roots={"fixture": dataset_root},
        config=EvaluationConfig(publication_threshold=0.85),
        source_commit="abc123",
        environment={"python": "fixture-python"},
        recognize=recognize,
        audio_loader=load_audio,
        predictions_output=predictions_path,
        report_output=report_path,
        markdown_output=markdown_path,
    )
    second = run_legacy_protocol(
        dict(reversed(list(manifests.items()))),
        dataset_roots={"fixture": dataset_root},
        config=EvaluationConfig(publication_threshold=0.85),
        source_commit="abc123",
        environment={"python": "fixture-python"},
        recognize=recognize,
        audio_loader=load_audio,
        predictions_output=predictions_path,
        report_output=report_path,
        markdown_output=markdown_path,
    )

    assert first == second == json.loads(report_path.read_text(encoding="utf-8"))
    assert first["source_commit"] == "abc123"
    assert first["algorithm_version"] == "chroma-triad-viterbi-v1"
    assert "public_quality_labels" not in first["evaluation_config"]
    assert set(first["splits"]) == {"validation", "test"}
    assert len(first["predictions_sha256"]) == 64
    assert len(predictions_path.read_text(encoding="utf-8").splitlines()) == 2
    assert "fixture-python" in report_path.read_text(encoding="utf-8")
    assert "Legacy baseline v1" in markdown_path.read_text(encoding="utf-8")
    assert "audio_path" not in report_path.read_text(encoding="utf-8")
    replay = replay_legacy_protocol(
        manifests,
        predictions_path=predictions_path,
        config=EvaluationConfig(publication_threshold=0.85),
    )
    assert replay["predictions_sha256"] == first["predictions_sha256"]
    assert replay["splits"] == {
        split: first["splits"][split]["evaluation"]
        for split in ("validation", "test")
    }

    with pytest.raises(FileExistsError, match="baseline artifact"):
        run_legacy_protocol(
            manifests,
            dataset_roots={"fixture": dataset_root},
            config=EvaluationConfig(publication_threshold=0.85),
            source_commit="different-commit",
            environment={"python": "fixture-python"},
            recognize=recognize,
            audio_loader=load_audio,
            predictions_output=predictions_path,
            report_output=report_path,
            markdown_output=markdown_path,
        )


def test_load_evaluation_config_uses_every_versioned_field() -> None:
    config = load_evaluation_config(ML_ROOT / "configs" / "evaluation-v1.json")

    assert config == EvaluationConfig(
        boundary_tolerance_seconds=0.05,
        ece_bin_count=15,
        publication_threshold=0.85,
        exact_match_includes_bass=False,
    )
