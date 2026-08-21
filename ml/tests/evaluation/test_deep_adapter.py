from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from museecho_ml.artifacts import canonical_sha256
from museecho_ml.evaluation.deep_adapter import (
    RawTrackPrediction,
    collect_authorized_test_predictions,
    collect_checkpoint_predictions,
    evaluate_authorized_test_predictions,
    evaluate_deep_predictions,
    fit_deep_calibration,
    load_deep_evaluation_manifest,
    manifest_reference_intervals,
)
from museecho_ml.evaluation.metrics import ScoredChordInterval
from museecho_ml.evaluation.promotion import open_frozen_test_session
from museecho_ml.labels import BASS_INTERVALS, PITCH_NAMES, CanonicalChord
from museecho_ml.vocabulary import ChordVocabulary

VOCABULARY = ChordVocabulary(
    (*PITCH_NAMES, "N", "X"),
    ("maj", "min", "7", "maj7", "min7", "dim", "hdim7", "sus4", "N", "X"),
    (*BASS_INTERVALS, "N", "X"),
)


def test_deep_evaluation_rejects_test_manifest_before_audio_access(tmp_path: Path) -> None:
    manifest = tmp_path / "test.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "split": "test",
                "corpus_role": "real-gold",
                "tracks": [
                    {
                        "track_id": "unreadable",
                        "audio_path": "does-not-exist.wav",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(PermissionError, match="calibration or validation"):
        load_deep_evaluation_manifest(manifest)


def test_deep_collection_rejects_manifest_hash_before_checkpoint_or_audio(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "validation.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "split": "validation",
                "corpus_role": "real-gold",
                "tracks": [
                    {
                        "track_id": "unreadable",
                        "audio_path": "does-not-exist.wav",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="manifest SHA-256"):
        collect_checkpoint_predictions(
            checkpoint_path=tmp_path / "does-not-exist.pt",
            manifest_path=manifest,
            config_path=tmp_path / "does-not-exist.json",
            vocabulary_path=tmp_path / "does-not-exist-vocabulary.json",
            expected_manifest_sha256="0" * 64,
        )


def test_authorized_test_collection_rejects_reused_session_before_checkpoint(
    tmp_path: Path,
) -> None:
    manifest = {
        "schema_version": 1,
        "split": "test",
        "corpus_role": "real-gold",
        "split_sha256": "c" * 64,
        "tracks": [{"track_id": "must-not-be-opened"}],
    }
    manifest_path = tmp_path / "test.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    selection_body = {
        "status": "frozen",
        "protocol_sha256": "1" * 64,
        "vocabulary_sha256": "2" * 64,
        "calibration_sha256": "3" * 64,
        "threshold_sha256": "4" * 64,
        "checkpoint_sha256": "a" * 64,
        "test_manifest_sha256": canonical_sha256(manifest),
        "test_split_sha256": "c" * 64,
    }
    selection = {
        **selection_body,
        "selection_sha256": canonical_sha256(selection_body),
    }
    session = open_frozen_test_session(
        selection=selection,
        manifest_path=manifest_path,
        access_marker_path=tmp_path / "test-access.marker",
    )
    session.evaluate_once(lambda _: None)

    with pytest.raises(PermissionError, match="already accessed"):
        collect_authorized_test_predictions(
            session=session,
            checkpoint_path=tmp_path / "does-not-exist.pt",
            config_path=tmp_path / "does-not-exist.json",
            vocabulary_path=tmp_path / "does-not-exist-vocabulary.json",
        )


def test_reference_fills_unannotated_gaps_and_maps_sus2_to_x() -> None:
    reference = manifest_reference_intervals(
        {
            "duration_seconds": 4.0,
            "intervals": [
                {
                    "start_seconds": 1.0,
                    "end_seconds": 2.0,
                    "root": "C",
                    "quality": "sus2",
                    "bass": "1",
                },
                {
                    "start_seconds": 2.0,
                    "end_seconds": 3.0,
                    "root": "G",
                    "quality": "7",
                    "bass": "1",
                },
            ],
        },
        VOCABULARY,
    )

    assert [
        (item.start_seconds, item.end_seconds, item.chord.root, item.chord.quality)
        for item in reference
    ] == [
        (0.0, 1.0, "N", "N"),
        (1.0, 2.0, "X", "X"),
        (2.0, 3.0, "G", "7"),
        (3.0, 4.0, "N", "N"),
    ]


def test_reference_normalizes_floating_point_tail_instead_of_creating_micro_gap() -> None:
    reference = manifest_reference_intervals(
        {
            "duration_seconds": 14.4,
            "intervals": [
                {
                    "start_seconds": 0.0,
                    "end_seconds": 14.399999999999977,
                    "root": "C",
                    "quality": "maj",
                    "bass": "1",
                }
            ],
        },
        VOCABULARY,
    )

    assert reference == (
        ScoredChordInterval(0.0, 14.4, CanonicalChord("C", "maj", "1")),
    )


def _logits(labels: tuple[str, ...], values: tuple[str, ...]) -> np.ndarray:
    result = np.full((len(values), len(labels)), -4.0, dtype=np.float64)
    for index, value in enumerate(values):
        result[index, labels.index(value)] = 4.0
    return result


def _raw_prediction(
    track_id: str, dataset_id: str, group_id: str, *, split: str
) -> RawTrackPrediction:
    reference = (
        ScoredChordInterval(0.0, 1.0, CanonicalChord("C", "maj", "1")),
        ScoredChordInterval(1.0, 2.0, CanonicalChord("G", "7", "1")),
    )
    return RawTrackPrediction(
        track_id=track_id,
        dataset_id=dataset_id,
        cover_group_id=group_id,
        split=split,
        duration_seconds=2.0,
        frame_times=np.asarray([0.0, 1.0]),
        valid_mask=np.asarray([True, True]),
        root_logits=_logits(VOCABULARY.root_labels, ("C", "G")),
        quality_logits=_logits(VOCABULARY.quality_labels, ("maj", "7")),
        bass_logits=_logits(VOCABULARY.bass_labels, ("1", "1")),
        boundary_logits=np.asarray([-4.0, 4.0]),
        reference=reference,
        inference_wall_seconds=0.02,
    )


def test_calibration_and_validation_reports_are_derived_from_raw_predictions() -> None:
    calibration_tracks = (
        _raw_prediction("cal-a", "guitarset", "cal-group-a", split="calibration"),
        _raw_prediction(
            "cal-b", "rwc-popular", "cal-group-b", split="calibration"
        ),
    )
    validation_tracks = (
        _raw_prediction("val-a", "guitarset", "val-group-a", split="validation"),
        _raw_prediction(
            "val-b", "rwc-popular", "val-group-b", split="validation"
        ),
    )

    calibration = fit_deep_calibration(calibration_tracks, VOCABULARY)
    report = evaluate_deep_predictions(
        validation_tracks,
        VOCABULARY,
        calibration.parameters,
    )

    assert calibration.status == "passed"
    assert calibration.precision == 1.0
    assert calibration.coverage == 1.0
    assert report["selection_metrics"]["exact_vocabulary_wcsr"] == 1.0
    assert report["selection_metrics"]["published_known_precision"] == 1.0
    assert report["selection_metrics"]["coverage"] == 1.0


def test_authorized_test_predictions_use_test_only_evaluation_path() -> None:
    test_tracks = (
        _raw_prediction("test-a", "guitarset", "test-group-a", split="test"),
        _raw_prediction(
            "test-b", "rwc-popular", "test-group-b", split="test"
        ),
    )
    calibration_tracks = (
        _raw_prediction("cal-a", "guitarset", "cal-group-a", split="calibration"),
        _raw_prediction(
            "cal-b", "rwc-popular", "cal-group-b", split="calibration"
        ),
    )
    calibration = fit_deep_calibration(calibration_tracks, VOCABULARY)

    with pytest.raises(ValueError, match="validation"):
        evaluate_deep_predictions(
            test_tracks,
            VOCABULARY,
            calibration.parameters,
        )

    report = evaluate_authorized_test_predictions(
        test_tracks,
        VOCABULARY,
        calibration.parameters,
    )

    assert report["selection_metrics"]["exact_vocabulary_wcsr"] == 1.0
