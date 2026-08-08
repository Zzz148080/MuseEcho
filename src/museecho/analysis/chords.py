from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from museecho.analysis.harmonic_features import (
    HOP_LENGTH,
    MINIMUM_SIGNAL_RMS,
    HarmonicFeatures,
    extract_harmonic_features,
    validate_harmonic_input,
)

_PITCH_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_MINIMUM_EVENT_SECONDS = 0.35
_UNKNOWN_STATE = 24


@dataclass(frozen=True)
class ChordEvent:
    symbol: str | None
    start_seconds: float
    end_seconds: float
    confidence: float | None
    algorithm: str = "chroma-triad-viterbi-v1"

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "confidence": self.confidence,
            "algorithm": self.algorithm,
        }


def estimate_chords(
    samples: Sequence[float] | memoryview,
    sample_rate: int,
    *,
    key_tonic: str | None = None,
    key_mode: str | None = None,
) -> tuple[ChordEvent, ...]:
    key_prior = _key_prior(key_tonic, key_mode)
    array, normalized_rate, duration_seconds = validate_harmonic_input(samples, sample_rate)
    features = extract_harmonic_features(array, normalized_rate, duration_seconds)
    if features.chroma.shape[1] == 0 or duration_seconds < _MINIMUM_EVENT_SECONDS:
        return (_unknown_event(duration_seconds),)
    states, frame_confidences = _decode_chord_states(features, key_prior)
    states = _discard_short_runs(states, frame_confidences, features.rms, normalized_rate)
    return _events_from_states(states, frame_confidences, features)


def _chord_templates() -> np.ndarray:
    templates: list[np.ndarray] = []
    for quality_third in (4, 3):
        for root in range(12):
            template = np.zeros(12, dtype=np.float64)
            template[root] = 1.0
            template[(root + quality_third) % 12] = 0.8
            template[(root + 7) % 12] = 0.7
            templates.append(template / np.linalg.norm(template))
    return np.stack(templates)


def _chord_pitch_masks() -> np.ndarray:
    masks: list[np.ndarray] = []
    for quality_third in (4, 3):
        for root in range(12):
            mask = np.zeros(12, dtype=np.float64)
            mask[[root, (root + quality_third) % 12, (root + 7) % 12]] = 1.0
            masks.append(mask)
    return np.stack(masks)


def _decode_chord_states(
    features: HarmonicFeatures,
    key_prior: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    chroma = np.maximum(features.chroma, 0.0)
    norms = np.linalg.norm(chroma, axis=0)
    normalized = np.divide(chroma, norms, out=np.zeros_like(chroma), where=norms > 1e-12)
    template_scores = _chord_templates() @ normalized
    order = np.argsort(template_scores, axis=0)
    best_states = order[-1, :]
    best_scores = np.take_along_axis(template_scores, order[-1:, :], axis=0)[0]
    second_scores = np.take_along_axis(template_scores, order[-2:-1, :], axis=0)[0]
    margins = best_scores - second_scores
    sorted_chroma = np.sort(chroma, axis=0)
    chroma_sums = np.sum(chroma, axis=0)
    concentration = np.divide(
        np.sum(sorted_chroma[-3:, :], axis=0),
        chroma_sums,
        out=np.zeros(chroma.shape[1], dtype=np.float64),
        where=chroma_sums > 1e-12,
    )
    l1_chroma = np.divide(
        chroma,
        chroma_sums,
        out=np.zeros_like(chroma),
        where=chroma_sums > 1e-12,
    )
    all_template_coverage = _chord_pitch_masks() @ l1_chroma
    template_coverage = np.take_along_axis(
        all_template_coverage,
        best_states[np.newaxis, :],
        axis=0,
    )[0]
    signal_evidence = np.clip(
        (features.rms - MINIMUM_SIGNAL_RMS) / (1e-3 - MINIMUM_SIGNAL_RMS),
        0.0,
        1.0,
    )
    frame_confidences = np.clip(
        0.45 * best_scores
        + 0.2 * np.clip(margins / 0.12, 0.0, 1.0)
        + 0.2 * template_coverage
        + 0.05 * concentration
        + 0.1 * signal_evidence,
        0.0,
        1.0,
    )
    known = (
        (best_scores >= 0.78)
        & (margins >= 0.035)
        & (concentration >= 0.55)
        & (template_coverage >= 0.68)
        & (features.rms > MINIMUM_SIGNAL_RMS)
        & (frame_confidences >= 0.7)
    )
    emissions = np.clip(template_scores, 0.0, 1.0) * 0.55
    emissions += frame_confidences[np.newaxis, :] * 0.45
    emissions[best_states, np.arange(chroma.shape[1])] += key_prior[best_states]
    emissions[:, ~known] *= 0.35
    unknown_emission = np.where(known, 0.2, 1.0)[np.newaxis, :]
    all_emissions = np.concatenate((emissions, unknown_emission), axis=0)
    states = _viterbi(all_emissions)
    selected_confidences = np.where(states == best_states, frame_confidences, 0.0)
    return states, selected_confidences


def _key_prior(key_tonic: str | None, key_mode: str | None) -> np.ndarray:
    if key_tonic is None and key_mode is None:
        return np.zeros(24, dtype=np.float64)
    if key_tonic not in _PITCH_NAMES or key_mode not in {"major", "minor"}:
        raise ValueError("key_tonic and key_mode must form a canonical major or minor key")
    tonic = _PITCH_NAMES.index(key_tonic)
    scale_intervals = (0, 2, 4, 5, 7, 9, 11) if key_mode == "major" else (0, 2, 3, 5, 7, 8, 10)
    scale = {(tonic + interval) % 12 for interval in scale_intervals}
    prior = np.zeros(24, dtype=np.float64)
    for state in range(24):
        root = state % 12
        third = (root + (4 if state < 12 else 3)) % 12
        fifth = (root + 7) % 12
        if {root, third, fifth}.issubset(scale):
            prior[state] = 0.03
    return prior


def _viterbi(emissions: np.ndarray) -> np.ndarray:
    state_count, frame_count = emissions.shape
    scores = np.empty((state_count, frame_count), dtype=np.float64)
    backpointers = np.empty((state_count, frame_count), dtype=np.int16)
    scores[:, 0] = emissions[:, 0]
    backpointers[:, 0] = 0
    transition_penalty = 0.18
    for frame in range(1, frame_count):
        previous = scores[:, frame - 1]
        for state in range(state_count):
            candidates = previous - transition_penalty
            best_previous = int(np.argmax(candidates))
            if previous[state] >= candidates[best_previous]:
                best_previous = state
            scores[state, frame] = previous[best_previous] + emissions[state, frame]
            backpointers[state, frame] = best_previous
    path = np.empty(frame_count, dtype=np.int16)
    path[-1] = int(np.argmax(scores[:, -1]))
    for frame in range(frame_count - 1, 0, -1):
        path[frame - 1] = backpointers[path[frame], frame]
    return path


def _discard_short_runs(
    states: np.ndarray,
    frame_confidences: np.ndarray,
    frame_rms: np.ndarray,
    sample_rate: int,
) -> np.ndarray:
    result = states.copy()
    result[frame_confidences < 0.7] = _UNKNOWN_STATE
    minimum_frames = max(1, math.ceil(_MINIMUM_EVENT_SECONDS * sample_rate / HOP_LENGTH))
    for _pass in range(states.size):
        previous_result = result.copy()
        start = 0
        for index in range(1, result.size + 1):
            if index < result.size and result[index] == result[start]:
                continue
            if index - start < minimum_frames:
                state = int(result[start])
                left = int(result[start - 1]) if start > 0 else _UNKNOWN_STATE
                right = int(result[index]) if index < result.size else _UNKNOWN_STATE
                has_both_neighbors = start > 0 and index < result.size
                if state == _UNKNOWN_STATE:
                    has_active_evidence = bool(np.all(frame_rms[start:index] > MINIMUM_SIGNAL_RMS))
                    if has_both_neighbors and has_active_evidence:
                        replacement = left if left != _UNKNOWN_STATE else right
                    else:
                        replacement = _UNKNOWN_STATE
                elif has_both_neighbors and left == right and left != _UNKNOWN_STATE:
                    replacement = left
                else:
                    replacement = _UNKNOWN_STATE
                result[start:index] = replacement
            start = index
        if np.array_equal(result, previous_result):
            break
    return result


def _events_from_states(
    states: np.ndarray,
    frame_confidences: np.ndarray,
    features: HarmonicFeatures,
) -> tuple[ChordEvent, ...]:
    centers = features.frame_centers_seconds
    boundaries = np.empty(states.size + 1, dtype=np.float64)
    boundaries[0] = 0.0
    boundaries[-1] = features.duration_seconds
    if states.size > 1:
        boundaries[1:-1] = (centers[:-1] + centers[1:]) / 2
    events: list[ChordEvent] = []
    start = 0
    for index in range(1, states.size + 1):
        if index < states.size and states[index] == states[start]:
            continue
        state = int(states[start])
        symbol = _symbol_for_state(state)
        confidence = None
        if symbol is not None:
            supported = frame_confidences[start:index]
            supported = supported[supported >= 0.7]
            if supported.size == 0 or supported.size / (index - start) < 0.6:
                symbol = None
            else:
                confidence = float(np.clip(np.mean(supported), 0.0, 1.0))
        event = ChordEvent(
            symbol,
            float(boundaries[start]),
            float(boundaries[index]),
            confidence,
        )
        if event.end_seconds > event.start_seconds:
            events.append(event)
        start = index
    if not events:
        return (_unknown_event(features.duration_seconds),)
    return tuple(events)


def _symbol_for_state(state: int) -> str | None:
    if state == _UNKNOWN_STATE:
        return None
    root = state % 12
    return _PITCH_NAMES[root] if state < 12 else f"{_PITCH_NAMES[root]}m"


def _unknown_event(duration_seconds: float) -> ChordEvent:
    return ChordEvent(None, 0.0, float(duration_seconds), None)
