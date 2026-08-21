from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from museecho_ml.evaluation.metrics import ScoredChordInterval
from museecho_ml.labels import CanonicalChord
from museecho_ml.vocabulary import ChordVocabulary

_QUALITY_BASS_TONES = {
    "maj": frozenset({"1", "3", "5"}),
    "min": frozenset({"1", "b3", "5"}),
    "7": frozenset({"1", "3", "5", "b7"}),
    "maj7": frozenset({"1", "3", "5", "7"}),
    "min7": frozenset({"1", "b3", "5", "b7"}),
    "dim": frozenset({"1", "b3", "b5"}),
    "hdim7": frozenset({"1", "b3", "b5", "b7"}),
    "sus4": frozenset({"1", "4", "5"}),
}


@dataclass(frozen=True)
class HybridFrameProbabilities:
    frame_times: NDArray[np.float64]
    valid_mask: NDArray[np.bool_]
    root: NDArray[np.float64]
    quality: NDArray[np.float64]
    bass: NDArray[np.float64]
    low_energy_mask: NDArray[np.bool_]


@dataclass(frozen=True)
class HybridDecodeConfig:
    known_threshold: float
    quality_thresholds: tuple[tuple[str, float], ...]
    bass_threshold: float
    minimum_support_fraction: float
    minimum_event_seconds: float
    hysteresis_frames: int
    maximum_event_ratio: float

    def __post_init__(self) -> None:
        thresholds = (
            self.known_threshold,
            self.bass_threshold,
            self.minimum_support_fraction,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1
            for value in thresholds
        ):
            raise ValueError("hybrid probability thresholds must be within [0, 1]")
        quality_names = [quality for quality, _ in self.quality_thresholds]
        if (
            len(set(quality_names)) != len(quality_names)
            or any(not quality or quality in {"N", "X"} for quality in quality_names)
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1
                for _, value in self.quality_thresholds
            )
        ):
            raise ValueError("hybrid quality thresholds are invalid")
        if (
            isinstance(self.minimum_event_seconds, bool)
            or not isinstance(self.minimum_event_seconds, (int, float))
            or not math.isfinite(self.minimum_event_seconds)
            or self.minimum_event_seconds < 0
        ):
            raise ValueError("hybrid minimum event duration is invalid")
        if type(self.hysteresis_frames) is not int or self.hysteresis_frames <= 0:
            raise ValueError("hybrid hysteresis frames must be positive")
        if (
            isinstance(self.maximum_event_ratio, bool)
            or not isinstance(self.maximum_event_ratio, (int, float))
            or not math.isfinite(self.maximum_event_ratio)
            or self.maximum_event_ratio <= 0
        ):
            raise ValueError("hybrid maximum event ratio must be positive")


def decode_hybrid(
    legacy: Sequence[ScoredChordInterval],
    neural: HybridFrameProbabilities,
    *,
    vocabulary: ChordVocabulary,
    config: HybridDecodeConfig,
) -> tuple[ScoredChordInterval, ...]:
    timeline, evidence = _validated_hybrid_inputs(legacy, neural, vocabulary)
    decoded = tuple(
        _decode_legacy_interval(item, evidence, vocabulary, config)
        for item in timeline
    )
    merged = _merge_adjacent_identical(decoded)
    ratio = len(merged) / len(timeline)
    if ratio > config.maximum_event_ratio:
        raise ValueError("hybrid event-count ratio exceeds the configured maximum")
    return merged


def _validated_hybrid_inputs(
    legacy: Sequence[ScoredChordInterval],
    neural: HybridFrameProbabilities,
    vocabulary: ChordVocabulary,
) -> tuple[tuple[ScoredChordInterval, ...], HybridFrameProbabilities]:
    if not isinstance(legacy, Sequence) or not legacy:
        raise ValueError("hybrid legacy timeline cannot be empty")
    timeline = tuple(legacy)
    previous_end = 0.0
    for index, item in enumerate(timeline):
        if item.start_seconds < previous_end:
            raise ValueError("hybrid legacy timeline intervals overlap")
        if index > 0 and not math.isclose(
            item.start_seconds, previous_end, abs_tol=1e-9
        ):
            raise ValueError("hybrid legacy timeline must be continuous")
        try:
            vocabulary.encode(item.chord)
        except ValueError as error:
            raise ValueError("hybrid legacy timeline contains an illegal chord") from error
        previous_end = item.end_seconds
    if not math.isclose(timeline[0].start_seconds, 0.0, abs_tol=1e-9):
        raise ValueError("hybrid legacy timeline must start at zero")

    times = np.asarray(neural.frame_times, dtype=np.float64)
    valid = np.asarray(neural.valid_mask)
    low_energy = np.asarray(neural.low_energy_mask)
    heads = (
        (np.asarray(neural.root, dtype=np.float64), len(vocabulary.root_labels)),
        (np.asarray(neural.quality, dtype=np.float64), len(vocabulary.quality_labels)),
        (np.asarray(neural.bass, dtype=np.float64), len(vocabulary.bass_labels)),
    )
    frame_count = len(times) if times.ndim == 1 else -1
    if (
        frame_count <= 0
        or not np.isfinite(times).all()
        or np.any(np.diff(times) <= 0)
        or times[0] < 0
        or times[-1] >= timeline[-1].end_seconds
        or valid.dtype != np.bool_
        or valid.shape != (frame_count,)
        or low_energy.dtype != np.bool_
        or low_energy.shape != (frame_count,)
        or not valid.any()
    ):
        raise ValueError("hybrid frame evidence is invalid")
    for probabilities, label_count in heads:
        if (
            probabilities.shape != (frame_count, label_count)
            or not np.isfinite(probabilities).all()
            or np.any(probabilities < 0)
            or np.any(probabilities > 1)
            or not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-9)
        ):
            raise ValueError("hybrid head probabilities are invalid")
    return timeline, HybridFrameProbabilities(
        frame_times=times,
        valid_mask=valid,
        root=heads[0][0],
        quality=heads[1][0],
        bass=heads[2][0],
        low_energy_mask=low_energy,
    )


def _decode_legacy_interval(
    legacy: ScoredChordInterval,
    neural: HybridFrameProbabilities,
    vocabulary: ChordVocabulary,
    config: HybridDecodeConfig,
) -> ScoredChordInterval:
    if legacy.chord.root == "N":
        return legacy
    duration = legacy.end_seconds - legacy.start_seconds
    if duration < config.minimum_event_seconds:
        return legacy
    weights = _frame_overlap_weights(
        neural.frame_times,
        start_seconds=legacy.start_seconds,
        end_seconds=legacy.end_seconds,
    )
    eligible = neural.valid_mask & ~neural.low_energy_mask & (weights > 0)
    eligible_duration = float(weights[eligible].sum())
    if eligible_duration / duration < config.minimum_support_fraction:
        return legacy

    root_probabilities = np.average(neural.root[eligible], axis=0, weights=weights[eligible])
    quality_probabilities = np.average(
        neural.quality[eligible], axis=0, weights=weights[eligible]
    )
    bass_probabilities = np.average(neural.bass[eligible], axis=0, weights=weights[eligible])
    root_index = int(np.argmax(root_probabilities))
    quality_index = int(np.argmax(quality_probabilities))
    bass_index = int(np.argmax(bass_probabilities))
    neural_root = vocabulary.root_labels[root_index]
    quality = vocabulary.quality_labels[quality_index]
    bass = vocabulary.bass_labels[bass_index]
    root_confidence = float(root_probabilities[root_index])
    quality_confidence = float(quality_probabilities[quality_index])
    bass_confidence = float(bass_probabilities[bass_index])
    if neural_root in {"N", "X"} or root_confidence < config.known_threshold:
        return legacy
    if quality in {"N", "X"} or quality_confidence < _quality_threshold(
        quality, config
    ):
        return legacy
    if not _has_hysteresis_support(neural, eligible, quality_index, config):
        return legacy

    root = neural_root if legacy.chord.root == "X" else legacy.chord.root
    allowed_bass = _QUALITY_BASS_TONES.get(quality, frozenset())
    bass_override = bass_confidence >= config.bass_threshold and bass in allowed_bass
    if legacy.chord.root == "X" and not bass_override:
        return legacy
    selected_bass = bass if bass_override else legacy.chord.bass
    if selected_bass not in allowed_bass:
        selected_bass = "1"
    chord = CanonicalChord(root, quality, selected_bass)
    vocabulary.encode(chord)
    if chord == legacy.chord:
        return legacy
    confidence_parts = [root_confidence, quality_confidence]
    if bass_override:
        confidence_parts.append(bass_confidence)
    return ScoredChordInterval(
        legacy.start_seconds,
        legacy.end_seconds,
        chord,
        min(confidence_parts),
    )


def _frame_overlap_weights(
    times: NDArray[np.float64], *, start_seconds: float, end_seconds: float
) -> NDArray[np.float64]:
    ends = np.empty_like(times)
    ends[:-1] = times[1:]
    ends[-1] = end_seconds
    ends = np.minimum(ends, end_seconds)
    starts = np.maximum(times, start_seconds)
    return np.maximum(0.0, ends - starts)


def _quality_threshold(quality: str, config: HybridDecodeConfig) -> float:
    return dict(config.quality_thresholds).get(quality, config.known_threshold)


def _has_hysteresis_support(
    neural: HybridFrameProbabilities,
    eligible: NDArray[np.bool_],
    quality_index: int,
    config: HybridDecodeConfig,
) -> bool:
    matching = eligible & (np.argmax(neural.quality, axis=1) == quality_index)
    longest = 0
    current = 0
    for value in matching:
        current = current + 1 if value else 0
        longest = max(longest, current)
    return longest >= config.hysteresis_frames


def _merge_adjacent_identical(
    events: Sequence[ScoredChordInterval],
) -> tuple[ScoredChordInterval, ...]:
    merged: list[ScoredChordInterval] = []
    for event in events:
        if not merged or merged[-1].chord != event.chord:
            merged.append(event)
            continue
        previous = merged.pop()
        previous_duration = previous.end_seconds - previous.start_seconds
        event_duration = event.end_seconds - event.start_seconds
        confidence = (
            previous.confidence * previous_duration + event.confidence * event_duration
        ) / (previous_duration + event_duration)
        merged.append(
            ScoredChordInterval(
                previous.start_seconds,
                event.end_seconds,
                event.chord,
                confidence,
            )
        )
    return tuple(merged)
