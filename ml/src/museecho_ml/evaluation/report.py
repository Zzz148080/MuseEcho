from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from museecho_ml.evaluation.metrics import (
    ScoredChordInterval,
    boundary_f1,
    expected_calibration_error,
    precision_coverage,
    quality_f1_report,
    weighted_chord_scores,
)


@dataclass(frozen=True)
class EvaluationConfig:
    boundary_tolerance_seconds: float = 0.05
    ece_bin_count: int = 15
    publication_threshold: float = 0.85
    exact_match_includes_bass: bool = False

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.boundary_tolerance_seconds)
            or self.boundary_tolerance_seconds < 0
        ):
            raise ValueError("boundary tolerance must be finite and non-negative")
        if type(self.ece_bin_count) is not int or self.ece_bin_count <= 0:
            raise ValueError("ECE bin count must be a positive integer")
        if (
            not math.isfinite(self.publication_threshold)
            or not 0 <= self.publication_threshold <= 1
        ):
            raise ValueError("publication threshold must be within [0, 1]")
        if self.exact_match_includes_bass is not False:
            raise ValueError("evaluation v1 exact matching excludes bass inversion")


def evaluate_track(
    track_id: str,
    reference: Sequence[ScoredChordInterval],
    prediction: Sequence[ScoredChordInterval],
    config: EvaluationConfig,
) -> dict[str, object]:
    if not isinstance(track_id, str) or not track_id.strip():
        raise ValueError("evaluation track_id must be a non-empty string")
    weighted_scores = weighted_chord_scores(reference, prediction)
    quality_report = quality_f1_report(reference, prediction)
    boundary = boundary_f1(
        reference_boundaries=tuple(item.end_seconds for item in reference[:-1]),
        predicted_boundaries=tuple(item.end_seconds for item in prediction[:-1]),
        tolerance_seconds=config.boundary_tolerance_seconds,
    )
    calibration = expected_calibration_error(
        _calibration_samples(reference, prediction), bin_count=config.ece_bin_count
    )
    published = precision_coverage(
        reference, prediction, threshold=config.publication_threshold
    )
    return {
        "schema_version": 1,
        "evaluation_version": "1.0.0",
        "track_id": track_id,
        "weighted_scores": weighted_scores,
        "quality": quality_report,
        "boundary": boundary,
        "ece": calibration,
        "published": published,
        "segmentation": {
            "reference_events": len(reference),
            "predicted_events": len(prediction),
        },
    }


def evaluate_corpus(
    tracks: Mapping[
        str,
        tuple[Sequence[ScoredChordInterval], Sequence[ScoredChordInterval]],
    ],
    config: EvaluationConfig,
) -> dict[str, object]:
    """Pool track timelines by duration while excluding artificial track seams."""

    if not tracks:
        raise ValueError("evaluation corpus cannot be empty")
    track_reports: dict[str, dict[str, object]] = {}
    combined_reference: list[ScoredChordInterval] = []
    combined_prediction: list[ScoredChordInterval] = []
    reference_boundaries: list[float] = []
    predicted_boundaries: list[float] = []
    offset = 0.0
    reference_events = 0
    predicted_events = 0
    for track_id in sorted(tracks):
        reference, prediction = tracks[track_id]
        track_reports[track_id] = evaluate_track(track_id, reference, prediction, config)
        duration = reference[-1].end_seconds - reference[0].start_seconds
        combined_reference.extend(_shifted(reference, offset - reference[0].start_seconds))
        combined_prediction.extend(_shifted(prediction, offset - prediction[0].start_seconds))
        reference_boundaries.extend(
            offset + item.end_seconds - reference[0].start_seconds
            for item in reference[:-1]
        )
        predicted_boundaries.extend(
            offset + item.end_seconds - prediction[0].start_seconds
            for item in prediction[:-1]
        )
        offset += duration
        reference_events += len(reference)
        predicted_events += len(prediction)
    aggregate = {
        "weighted_scores": weighted_chord_scores(
            combined_reference, combined_prediction
        ),
        "quality": quality_f1_report(combined_reference, combined_prediction),
        "boundary": boundary_f1(
            reference_boundaries=reference_boundaries,
            predicted_boundaries=predicted_boundaries,
            tolerance_seconds=config.boundary_tolerance_seconds,
        ),
        "ece": expected_calibration_error(
            _calibration_samples(combined_reference, combined_prediction),
            bin_count=config.ece_bin_count,
        ),
        "published": precision_coverage(
            combined_reference,
            combined_prediction,
            threshold=config.publication_threshold,
        ),
        "segmentation": {
            "reference_events": reference_events,
            "predicted_events": predicted_events,
        },
    }
    return {
        "schema_version": 1,
        "evaluation_version": "1.0.0",
        "track_count": len(track_reports),
        "duration_seconds": offset,
        "aggregate": aggregate,
        "tracks": track_reports,
    }


def _shifted(
    intervals: Sequence[ScoredChordInterval], offset: float
) -> tuple[ScoredChordInterval, ...]:
    return tuple(
        ScoredChordInterval(
            start_seconds=item.start_seconds + offset,
            end_seconds=item.end_seconds + offset,
            chord=item.chord,
            confidence=item.confidence,
        )
        for item in intervals
    )


def _calibration_samples(
    reference: Sequence[ScoredChordInterval], prediction: Sequence[ScoredChordInterval]
) -> Iterable[tuple[float, bool, float]]:
    reference_index = 0
    prediction_index = 0
    while reference_index < len(reference) and prediction_index < len(prediction):
        reference_item = reference[reference_index]
        predicted_item = prediction[prediction_index]
        start = max(reference_item.start_seconds, predicted_item.start_seconds)
        end = min(reference_item.end_seconds, predicted_item.end_seconds)
        if start < end:
            correct = (
                reference_item.chord.root == predicted_item.chord.root
                and reference_item.chord.quality == predicted_item.chord.quality
            )
            yield predicted_item.confidence, correct, end - start
        if reference_item.end_seconds <= predicted_item.end_seconds:
            reference_index += 1
        if predicted_item.end_seconds <= reference_item.end_seconds:
            prediction_index += 1
