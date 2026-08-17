from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from museecho_ml.labels import CanonicalChord


@dataclass(frozen=True)
class ScoredChordInterval:
    start_seconds: float
    end_seconds: float
    chord: CanonicalChord
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.start_seconds)
            or not math.isfinite(self.end_seconds)
            or self.start_seconds < 0
            or self.start_seconds >= self.end_seconds
        ):
            raise ValueError("scored chord interval bounds are invalid")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("scored chord confidence must be within [0, 1]")


def weighted_chord_scores(
    reference: Sequence[ScoredChordInterval],
    prediction: Sequence[ScoredChordInterval],
) -> dict[str, float]:
    _validate_comparable(reference, prediction)
    total_duration = sum(item.end_seconds - item.start_seconds for item in reference)
    root_correct = 0.0
    exact_correct = 0.0
    majmin_correct = 0.0
    majmin_duration = 0.0
    triads_correct = 0.0
    triads_duration = 0.0
    sevenths_correct = 0.0
    sevenths_duration = 0.0
    for reference_item, predicted_item, duration in _aligned_segments(reference, prediction):
        if _root_matches(reference_item.chord, predicted_item.chord):
            root_correct += duration
        if _exact_quality_matches(reference_item.chord, predicted_item.chord):
            exact_correct += duration
        reference_seventh = _seventh_quality(reference_item.chord.quality)
        if reference_seventh is not None:
            sevenths_duration += duration
            if (
                reference_item.chord.root == predicted_item.chord.root
                and reference_seventh == _seventh_quality(predicted_item.chord.quality)
            ):
                sevenths_correct += duration
        reference_majmin = _majmin_quality(reference_item.chord.quality)
        if reference_majmin is not None:
            majmin_duration += duration
            if (
                reference_item.chord.root == predicted_item.chord.root
                and reference_majmin == _majmin_quality(predicted_item.chord.quality)
            ):
                majmin_correct += duration
        reference_triad = _triad_quality(reference_item.chord.quality)
        if reference_triad is not None:
            triads_duration += duration
            if (
                reference_item.chord.root == predicted_item.chord.root
                and reference_triad == _triad_quality(predicted_item.chord.quality)
            ):
                triads_correct += duration
    return {
        "root": root_correct / total_duration,
        "majmin": majmin_correct / majmin_duration if majmin_duration else 0.0,
        "triads": triads_correct / triads_duration if triads_duration else 0.0,
        "sevenths": sevenths_correct / sevenths_duration if sevenths_duration else 0.0,
        "exact_quality": exact_correct / total_duration,
    }


def boundary_f1(
    *,
    reference_boundaries: Sequence[float],
    predicted_boundaries: Sequence[float],
    tolerance_seconds: float,
) -> dict[str, float]:
    if not math.isfinite(tolerance_seconds) or tolerance_seconds < 0:
        raise ValueError("boundary tolerance must be finite and non-negative")
    reference = _validated_boundaries(reference_boundaries)
    predicted = _validated_boundaries(predicted_boundaries)
    matched_reference: set[int] = set()
    true_positives = 0
    for prediction in predicted:
        candidates = [
            (abs(prediction - boundary), index)
            for index, boundary in enumerate(reference)
            if index not in matched_reference
            and abs(prediction - boundary) <= tolerance_seconds
        ]
        if candidates:
            _, index = min(candidates)
            matched_reference.add(index)
            true_positives += 1
    precision = true_positives / len(predicted) if predicted else float(not reference)
    recall = true_positives / len(reference) if reference else float(not predicted)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1}


def expected_calibration_error(
    samples: Iterable[tuple[float, bool, float]], *, bin_count: int = 10
) -> float:
    if type(bin_count) is not int or bin_count <= 0:
        raise ValueError("calibration bin_count must be a positive integer")
    bins: list[list[tuple[float, bool, float]]] = [[] for _ in range(bin_count)]
    total_weight = 0.0
    for confidence, correct, weight in samples:
        if (
            not math.isfinite(confidence)
            or not 0 <= confidence <= 1
            or type(correct) is not bool
            or not math.isfinite(weight)
            or weight <= 0
        ):
            raise ValueError("calibration sample is invalid")
        bins[min(int(confidence * bin_count), bin_count - 1)].append(
            (confidence, correct, weight)
        )
        total_weight += weight
    if total_weight == 0:
        raise ValueError("calibration samples cannot be empty")
    error = 0.0
    for bin_samples in bins:
        bin_weight = sum(sample[2] for sample in bin_samples)
        if bin_weight == 0:
            continue
        accuracy = sum(weight for _, correct, weight in bin_samples if correct) / bin_weight
        mean_confidence = (
            sum(confidence * weight for confidence, _, weight in bin_samples) / bin_weight
        )
        error += bin_weight / total_weight * abs(accuracy - mean_confidence)
    return error


def precision_coverage(
    reference: Sequence[ScoredChordInterval],
    prediction: Sequence[ScoredChordInterval],
    *,
    threshold: float,
) -> dict[str, float]:
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("publication threshold must be within [0, 1]")
    _validate_comparable(reference, prediction)
    total_duration = sum(item.end_seconds - item.start_seconds for item in reference)
    published_duration = 0.0
    correct_duration = 0.0
    for reference_item, predicted_item, duration in _aligned_segments(reference, prediction):
        if predicted_item.confidence < threshold or predicted_item.chord.root in {"N", "X"}:
            continue
        published_duration += duration
        if _exact_quality_matches(reference_item.chord, predicted_item.chord):
            correct_duration += duration
    precision = correct_duration / published_duration if published_duration else 0.0
    return {"precision": precision, "coverage": published_duration / total_duration}


def quality_f1_report(
    reference: Sequence[ScoredChordInterval], prediction: Sequence[ScoredChordInterval]
) -> dict[str, object]:
    _validate_comparable(reference, prediction)
    true_positive: dict[str, float] = {}
    false_positive: dict[str, float] = {}
    false_negative: dict[str, float] = {}
    support: dict[str, float] = {}
    for reference_item, predicted_item, duration in _aligned_segments(reference, prediction):
        reference_quality = reference_item.chord.quality
        predicted_quality = predicted_item.chord.quality
        support[reference_quality] = support.get(reference_quality, 0.0) + duration
        if reference_quality == predicted_quality:
            true_positive[reference_quality] = (
                true_positive.get(reference_quality, 0.0) + duration
            )
        else:
            false_negative[reference_quality] = (
                false_negative.get(reference_quality, 0.0) + duration
            )
            false_positive[predicted_quality] = (
                false_positive.get(predicted_quality, 0.0) + duration
            )
    qualities = sorted(set(support) | set(false_positive))
    per_quality: dict[str, dict[str, float]] = {}
    for quality in qualities:
        tp = true_positive.get(quality, 0.0)
        precision_denominator = tp + false_positive.get(quality, 0.0)
        recall_denominator = tp + false_negative.get(quality, 0.0)
        precision = tp / precision_denominator if precision_denominator else 0.0
        recall = tp / recall_denominator if recall_denominator else 0.0
        f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
        per_quality[quality] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support_seconds": support.get(quality, 0.0),
        }
    supported_f1 = [values["f1"] for quality, values in per_quality.items() if quality in support]
    return {
        "per_quality": per_quality,
        "macro_f1": sum(supported_f1) / len(supported_f1),
    }


def _validate_timeline(items: Sequence[ScoredChordInterval], name: str) -> None:
    if not items:
        raise ValueError(f"{name} timeline cannot be empty")
    previous_end = 0.0
    for index, item in enumerate(items):
        if item.start_seconds < previous_end:
            raise ValueError(f"{name} timeline intervals overlap")
        if index > 0 and not math.isclose(item.start_seconds, previous_end, abs_tol=1e-9):
            raise ValueError(f"{name} timeline must be continuous")
        previous_end = item.end_seconds


def _validate_comparable(
    reference: Sequence[ScoredChordInterval], prediction: Sequence[ScoredChordInterval]
) -> None:
    _validate_timeline(reference, "reference")
    _validate_timeline(prediction, "prediction")
    if not math.isclose(
        reference[0].start_seconds, prediction[0].start_seconds, abs_tol=1e-9
    ) or not math.isclose(reference[-1].end_seconds, prediction[-1].end_seconds, abs_tol=1e-9):
        raise ValueError("reference and prediction timelines must cover the same extent")


def _aligned_segments(
    reference: Sequence[ScoredChordInterval], prediction: Sequence[ScoredChordInterval]
) -> Iterable[tuple[ScoredChordInterval, ScoredChordInterval, float]]:
    reference_index = 0
    prediction_index = 0
    while reference_index < len(reference) and prediction_index < len(prediction):
        reference_item = reference[reference_index]
        predicted_item = prediction[prediction_index]
        start = max(reference_item.start_seconds, predicted_item.start_seconds)
        end = min(reference_item.end_seconds, predicted_item.end_seconds)
        if start < end:
            yield reference_item, predicted_item, end - start
        if reference_item.end_seconds <= predicted_item.end_seconds:
            reference_index += 1
        if predicted_item.end_seconds <= reference_item.end_seconds:
            prediction_index += 1


def _root_matches(reference: CanonicalChord, prediction: CanonicalChord) -> bool:
    return reference.root == prediction.root


def _exact_quality_matches(reference: CanonicalChord, prediction: CanonicalChord) -> bool:
    return reference.root == prediction.root and reference.quality == prediction.quality


def _majmin_quality(quality: str) -> str | None:
    if quality in {"maj", "7", "maj7"}:
        return "maj"
    if quality in {"min", "min7"}:
        return "min"
    return None


def _triad_quality(quality: str) -> str | None:
    if quality in {"maj", "7", "maj7"}:
        return "maj"
    if quality in {"min", "min7"}:
        return "min"
    if quality in {"dim", "hdim7"}:
        return "dim"
    if quality in {"sus2", "sus4"}:
        return quality
    return None


def _seventh_quality(quality: str) -> str | None:
    if quality in {"maj", "min", "7", "maj7", "min7", "dim", "hdim7"}:
        return quality
    return None


def _validated_boundaries(values: Sequence[float]) -> tuple[float, ...]:
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("boundary positions must be finite and non-negative")
    return tuple(sorted(values))
