from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from museecho_ml.artifacts import canonical_sha256
from museecho_ml.evaluation.metrics import ScoredChordInterval, weighted_chord_scores
from museecho_ml.vocabulary import ChordVocabulary

_DEVELOPMENT_SPLITS = frozenset({"train", "calibration", "validation"})


@dataclass(frozen=True)
class PlanDAuditTrack:
    track_id: str
    dataset_id: str
    cover_group_id: str
    split: str
    duration_seconds: float
    frame_times: NDArray[np.float64]
    reference: tuple[ScoredChordInterval, ...]
    prediction: tuple[ScoredChordInterval, ...]
    seed: int | None = None


def audit_frame_alignment(
    frame_times: NDArray[np.floating],
    reference: Sequence[ScoredChordInterval],
) -> dict[str, float]:
    times = np.asarray(frame_times, dtype=np.float64)
    if (
        times.ndim != 1
        or len(times) == 0
        or not np.all(np.isfinite(times))
        or np.any(times < 0)
        or np.any(np.diff(times) <= 0)
    ):
        raise ValueError("Plan D audit frame times are invalid")
    if not reference:
        raise ValueError("Plan D audit reference cannot be empty")
    grid = times
    if len(times) > 1:
        terminal = times[-1] + float(np.median(np.diff(times)))
        grid = np.append(times, terminal)
    boundaries = np.asarray(
        sorted(
            {item.start_seconds for item in reference}
            | {item.end_seconds for item in reference}
        ),
        dtype=np.float64,
    )
    errors = np.min(np.abs(grid[:, None] - boundaries[None, :]), axis=0)
    return {
        "maximum_boundary_frame_error_seconds": float(errors.max(initial=0.0)),
        "mean_boundary_frame_error_seconds": float(errors.mean()),
    }


def build_plan_d_failure_audit(
    tracks: Sequence[PlanDAuditTrack],
    *,
    supported_qualities: Sequence[str],
) -> dict[str, Any]:
    qualities = _validated_supported_qualities(supported_qualities)
    validated = _validated_audit_tracks(tracks)
    body = {
        "schema_version": 1,
        "audit_version": "plan-d-failure-audit-v1",
        "alignment": _aggregate_alignment(validated),
        "root_confusion_seconds": _confusion_seconds(validated, "root"),
        "quality_confusion_seconds": _confusion_seconds(
            validated, "quality", labels=qualities
        ),
        "bass_confusion_seconds": _confusion_seconds(validated, "bass"),
        "event_counts": _event_count_report(validated),
        "quality_support": _quality_support_report(validated, qualities),
        "confidence_curve": _confidence_curve(validated),
        "cover_group_count": len({track.cover_group_id for track in validated}),
        "datasets": _stratified_reports(validated, key="dataset"),
        "seeds": _stratified_reports(validated, key="seed"),
    }
    return {**body, "audit_sha256": canonical_sha256(body)}


def _validated_supported_qualities(values: Sequence[str]) -> tuple[str, ...]:
    if (
        not isinstance(values, Sequence)
        or isinstance(values, (str, bytes))
        or not values
        or any(not isinstance(value, str) or not value for value in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError("Plan D supported qualities are invalid")
    return tuple(sorted(values))


def _validated_audit_tracks(
    tracks: Sequence[PlanDAuditTrack],
) -> tuple[PlanDAuditTrack, ...]:
    if not isinstance(tracks, Sequence) or not tracks:
        raise ValueError("Plan D audit tracks cannot be empty")
    vocabulary = ChordVocabulary.default()
    validated: list[PlanDAuditTrack] = []
    identities: set[tuple[int | None, str]] = set()
    for track in tracks:
        if not isinstance(track, PlanDAuditTrack):
            raise ValueError("Plan D audit track type is invalid")
        if track.split not in _DEVELOPMENT_SPLITS:
            raise ValueError("Plan D audit forbids test split")
        if not track.track_id or not track.dataset_id:
            raise ValueError("Plan D audit track identity is invalid")
        if not track.cover_group_id:
            raise ValueError("Plan D audit cover group is missing")
        if track.seed is not None and type(track.seed) is not int:
            raise ValueError("Plan D audit seed is invalid")
        if not math.isfinite(track.duration_seconds) or track.duration_seconds <= 0:
            raise ValueError("Plan D audit duration is invalid")
        identity = (track.seed, track.track_id)
        if identity in identities:
            raise ValueError("Plan D audit track identity is duplicated")
        identities.add(identity)
        _validate_timeline(track.reference, track.duration_seconds, "reference", vocabulary)
        _validate_timeline(track.prediction, track.duration_seconds, "prediction", vocabulary)
        weighted_chord_scores(track.reference, track.prediction)
        audit_frame_alignment(track.frame_times, track.reference)
        validated.append(track)
    return tuple(
        sorted(
            validated,
            key=lambda item: (
                item.dataset_id,
                -1 if item.seed is None else item.seed,
                item.cover_group_id,
                item.track_id,
            ),
        )
    )


def _validate_timeline(
    items: Sequence[ScoredChordInterval],
    duration_seconds: float,
    name: str,
    vocabulary: ChordVocabulary,
) -> None:
    if not items:
        raise ValueError(f"Plan D audit {name} timeline cannot be empty")
    previous_end = 0.0
    for item in items:
        if item.start_seconds < previous_end:
            raise ValueError(f"Plan D audit {name} intervals overlap")
        try:
            vocabulary.encode(item.chord)
        except ValueError as error:
            raise ValueError("Plan D audit contains an illegal chord state") from error
        previous_end = item.end_seconds
    if not math.isclose(items[0].start_seconds, 0.0, abs_tol=1e-9) or not math.isclose(
        items[-1].end_seconds, duration_seconds, abs_tol=1e-9
    ):
        raise ValueError(f"Plan D audit {name} timeline extent is invalid")


def _aggregate_alignment(tracks: Sequence[PlanDAuditTrack]) -> dict[str, float]:
    reports = [audit_frame_alignment(track.frame_times, track.reference) for track in tracks]
    return {
        "maximum_boundary_frame_error_seconds": max(
            report["maximum_boundary_frame_error_seconds"] for report in reports
        ),
        "mean_boundary_frame_error_seconds": sum(
            report["mean_boundary_frame_error_seconds"] for report in reports
        )
        / len(reports),
    }


def _aligned_segments(
    reference: Sequence[ScoredChordInterval],
    prediction: Sequence[ScoredChordInterval],
) -> Iterable[tuple[ScoredChordInterval, ScoredChordInterval, float]]:
    reference_index = 0
    prediction_index = 0
    while reference_index < len(reference) and prediction_index < len(prediction):
        reference_item = reference[reference_index]
        prediction_item = prediction[prediction_index]
        start = max(reference_item.start_seconds, prediction_item.start_seconds)
        end = min(reference_item.end_seconds, prediction_item.end_seconds)
        if start < end:
            yield reference_item, prediction_item, end - start
        if reference_item.end_seconds <= prediction_item.end_seconds:
            reference_index += 1
        if prediction_item.end_seconds <= reference_item.end_seconds:
            prediction_index += 1


def _confusion_seconds(
    tracks: Sequence[PlanDAuditTrack],
    head: str,
    *,
    labels: Sequence[str] = (),
) -> dict[str, dict[str, float]]:
    rows: dict[str, dict[str, float]] = {label: {} for label in labels}
    for track in tracks:
        for reference, prediction, duration in _aligned_segments(
            track.reference, track.prediction
        ):
            if head == "quality" and reference.chord.root != prediction.chord.root:
                continue
            if head == "bass" and (
                reference.chord.root != prediction.chord.root
                or reference.chord.quality != prediction.chord.quality
            ):
                continue
            expected = getattr(reference.chord, head)
            actual = getattr(prediction.chord, head)
            row = rows.setdefault(expected, {})
            row[actual] = row.get(actual, 0.0) + duration
    return {
        expected: {actual: row[actual] for actual in sorted(row)}
        for expected, row in sorted(rows.items())
    }


def _event_count_report(tracks: Sequence[PlanDAuditTrack]) -> dict[str, float | int]:
    reference = sum(len(track.reference) for track in tracks)
    prediction = sum(len(track.prediction) for track in tracks)
    return {
        "prediction": prediction,
        "reference": reference,
        "ratio": prediction / reference,
    }


def _quality_support_report(
    tracks: Sequence[PlanDAuditTrack], qualities: Sequence[str]
) -> dict[str, dict[str, float | int]]:
    report: dict[str, dict[str, float | int]] = {}
    for quality in qualities:
        matching = [
            (track, item)
            for track in tracks
            for item in track.reference
            if item.chord.quality == quality
        ]
        report[quality] = {
            "cover_groups": len({track.cover_group_id for track, _ in matching}),
            "duration_seconds": sum(
                item.end_seconds - item.start_seconds for _, item in matching
            ),
            "intervals": len(matching),
        }
    return report


def _confidence_curve(tracks: Sequence[PlanDAuditTrack]) -> dict[str, Any]:
    bins = [
        {"lower": index / 10, "upper": (index + 1) / 10, "duration_seconds": 0.0,
         "correct_seconds": 0.0}
        for index in range(10)
    ]
    duration_seconds = 0.0
    correct_seconds = 0.0
    for track in tracks:
        for reference, prediction, duration in _aligned_segments(
            track.reference, track.prediction
        ):
            index = min(int(prediction.confidence * 10), 9)
            bins[index]["duration_seconds"] += duration
            correct = (
                reference.chord.root == prediction.chord.root
                and reference.chord.quality == prediction.chord.quality
            )
            if correct:
                bins[index]["correct_seconds"] += duration
                correct_seconds += duration
            duration_seconds += duration
    return {
        "bins": bins,
        "correct_seconds": correct_seconds,
        "duration_seconds": duration_seconds,
    }


def _stratified_reports(
    tracks: Sequence[PlanDAuditTrack], *, key: str
) -> dict[str, dict[str, Any]]:
    values: dict[str, list[PlanDAuditTrack]] = {}
    for track in tracks:
        if key == "dataset":
            value = track.dataset_id
        else:
            if track.seed is None:
                continue
            value = str(track.seed)
        values.setdefault(value, []).append(track)
    return {
        value: {
            "event_counts": _event_count_report(items),
            "quality_confusion_seconds": _confusion_seconds(items, "quality"),
            "track_count": len(items),
        }
        for value, items in sorted(values.items())
    }
