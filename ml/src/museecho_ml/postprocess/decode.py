from __future__ import annotations

import heapq
import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from museecho_ml.evaluation.metrics import ScoredChordInterval
from museecho_ml.labels import CanonicalChord
from museecho_ml.postprocess.calibration import CalibrationParameters
from museecho_ml.postprocess.events import serialize_events
from museecho_ml.vocabulary import ChordVocabulary, EncodedChord

__all__ = ["decode_logits", "serialize_events"]


def decode_logits(
    root_logits: NDArray[np.floating],
    quality_logits: NDArray[np.floating],
    bass_logits: NDArray[np.floating],
    boundary_logits: NDArray[np.floating],
    frame_times: NDArray[np.floating],
    valid_mask: NDArray[np.bool_],
    *,
    duration_seconds: float,
    vocabulary: ChordVocabulary,
    calibration: CalibrationParameters,
    low_energy_mask: NDArray[np.bool_] | None = None,
) -> tuple[ScoredChordInterval, ...]:
    roots, qualities, basses, boundaries, times, mask, low_energy = _validated_inputs(
        root_logits,
        quality_logits,
        bass_logits,
        boundary_logits,
        frame_times,
        valid_mask,
        duration_seconds,
        vocabulary,
        low_energy_mask,
    )
    root_probabilities = _softmax(roots / calibration.root_temperature)
    quality_probabilities = _softmax(qualities / calibration.quality_temperature)
    bass_probabilities = _softmax(basses / calibration.bass_temperature)
    boundary_probabilities = 1.0 / (1.0 + np.exp(-boundaries))

    states: list[CanonicalChord] = []
    confidences: list[float] = []
    for index in range(len(times)):
        state, confidence = _frame_state(
            root_probabilities[index],
            quality_probabilities[index],
            bass_probabilities[index],
            vocabulary,
            publication_threshold=calibration.publication_threshold,
            low_energy=bool(low_energy[index]),
        )
        states.append(state)
        confidences.append(confidence)
    states = _suppress_short_runs(
        states,
        confidences,
        times,
        duration_seconds,
        calibration.minimum_event_seconds,
    )
    return _events_from_frames(
        states,
        confidences,
        boundary_probabilities,
        times,
        duration_seconds,
        calibration.boundary_threshold,
    )


def _validated_inputs(
    root_logits: NDArray[np.floating],
    quality_logits: NDArray[np.floating],
    bass_logits: NDArray[np.floating],
    boundary_logits: NDArray[np.floating],
    frame_times: NDArray[np.floating],
    valid_mask: NDArray[np.bool_],
    duration_seconds: float,
    vocabulary: ChordVocabulary,
    low_energy_mask: NDArray[np.bool_] | None,
) -> tuple[
    NDArray[np.float64],
    NDArray[np.float64],
    NDArray[np.float64],
    NDArray[np.float64],
    NDArray[np.float64],
    NDArray[np.bool_],
    NDArray[np.bool_],
]:
    roots = np.asarray(root_logits, dtype=np.float64)
    qualities = np.asarray(quality_logits, dtype=np.float64)
    basses = np.asarray(bass_logits, dtype=np.float64)
    boundaries = np.asarray(boundary_logits, dtype=np.float64)
    times = np.asarray(frame_times, dtype=np.float64)
    mask = np.asarray(valid_mask)
    if (
        roots.ndim != 2
        or qualities.ndim != 2
        or basses.ndim != 2
        or roots.shape[1] != len(vocabulary.root_labels)
        or qualities.shape[1] != len(vocabulary.quality_labels)
        or basses.shape[1] != len(vocabulary.bass_labels)
        or not roots.shape[0] == qualities.shape[0] == basses.shape[0]
        or boundaries.shape != (roots.shape[0],)
        or times.shape != (roots.shape[0],)
        or mask.dtype != np.bool_
        or mask.shape != (roots.shape[0],)
        or not len(times)
        or not np.isfinite(roots).all()
        or not np.isfinite(qualities).all()
        or not np.isfinite(basses).all()
        or not np.isfinite(boundaries).all()
        or not np.isfinite(times).all()
        or np.any(np.diff(times) <= 0)
        or not mask.any()
        or np.any(np.maximum.accumulate(~mask) & mask)
        or isinstance(duration_seconds, bool)
        or not isinstance(duration_seconds, (int, float))
        or not math.isfinite(duration_seconds)
        or duration_seconds <= 0
    ):
        raise ValueError("decoder frame evidence is invalid")
    count = int(mask.sum())
    roots = roots[:count]
    qualities = qualities[:count]
    basses = basses[:count]
    boundaries = boundaries[:count]
    times = times[:count]
    if times[0] < 0 or times[-1] >= duration_seconds:
        raise ValueError("decoder frame times fall outside the audio")
    if low_energy_mask is None:
        low_energy = np.zeros(count, dtype=np.bool_)
    else:
        raw_low_energy = np.asarray(low_energy_mask)
        if raw_low_energy.dtype != np.bool_ or raw_low_energy.shape != mask.shape:
            raise ValueError("decoder low-energy mask is invalid")
        low_energy = raw_low_energy[:count]
    return roots, qualities, basses, boundaries, times, mask[:count], low_energy


def _softmax(logits: NDArray[np.float64]) -> NDArray[np.float64]:
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    exponentials = np.exp(shifted)
    return exponentials / exponentials.sum(axis=1, keepdims=True)


def _frame_state(
    root_probabilities: NDArray[np.float64],
    quality_probabilities: NDArray[np.float64],
    bass_probabilities: NDArray[np.float64],
    vocabulary: ChordVocabulary,
    *,
    publication_threshold: float,
    low_energy: bool,
) -> tuple[CanonicalChord, float]:
    if low_energy:
        return CanonicalChord("N", "N", "N"), 1.0
    root_index = int(np.argmax(root_probabilities))
    quality_index = int(np.argmax(quality_probabilities))
    bass_index = int(np.argmax(bass_probabilities))
    root = vocabulary.root_labels[root_index]
    quality = vocabulary.quality_labels[quality_index]
    bass = vocabulary.bass_labels[bass_index]
    confidence = float(
        min(
            root_probabilities[root_index],
            quality_probabilities[quality_index],
            bass_probabilities[bass_index],
        )
    )
    if root in {"N", "X"}:
        return CanonicalChord(root, root, root), confidence
    if quality in {"N", "X"} or bass in {"N", "X"}:
        return CanonicalChord("X", "X", "X"), confidence
    if confidence < publication_threshold:
        return CanonicalChord("X", "X", "X"), confidence
    return vocabulary.decode(EncodedChord(root_index, quality_index, bass_index)), confidence


def _suppress_short_runs(
    states: list[CanonicalChord],
    confidences: Sequence[float],
    times: NDArray[np.float64],
    duration_seconds: float,
    minimum_event_seconds: float,
) -> list[CanonicalChord]:
    if minimum_event_seconds <= 0 or len(states) == 1:
        return states
    runs = _label_runs(states)
    if len(runs) == 1:
        return list(states)
    starts = [start for start, _ in runs]
    ends = [end for _, end in runs]
    labels = [states[start] for start, _ in runs]
    previous = [index - 1 for index in range(len(runs))]
    following = [index + 1 for index in range(len(runs))]
    following[-1] = -1
    active = [True] * len(runs)
    versions = [0] * len(runs)

    def is_short(index: int) -> bool:
        start_seconds = 0.0 if starts[index] == 0 else float(times[starts[index]])
        end_seconds = (
            duration_seconds
            if ends[index] == len(states)
            else float(times[ends[index]])
        )
        return end_seconds - start_seconds < minimum_event_seconds

    pending: list[tuple[int, int, int]] = []

    def enqueue(index: int) -> None:
        if active[index] and is_short(index):
            heapq.heappush(pending, (starts[index], index, versions[index]))

    for index in range(len(runs)):
        enqueue(index)

    while pending:
        _, index, version = heapq.heappop(pending)
        if (
            not active[index]
            or versions[index] != version
            or not is_short(index)
        ):
            continue
        previous_index = previous[index]
        following_index = following[index]
        if previous_index == -1 and following_index == -1:
            break
        if previous_index == -1:
            replacement = labels[following_index]
        elif following_index == -1:
            replacement = labels[previous_index]
        elif labels[previous_index] == labels[following_index]:
            replacement = labels[previous_index]
        else:
            previous_confidence = float(
                np.mean(confidences[starts[previous_index] : ends[previous_index]])
            )
            following_confidence = float(
                np.mean(confidences[starts[following_index] : ends[following_index]])
            )
            replacement = (
                labels[previous_index]
                if previous_confidence >= following_confidence
                else labels[following_index]
            )
        labels[index] = replacement
        versions[index] += 1

        if previous_index != -1 and labels[previous_index] == labels[index]:
            starts[index] = starts[previous_index]
            previous[index] = previous[previous_index]
            if previous[index] != -1:
                following[previous[index]] = index
            active[previous_index] = False
            versions[previous_index] += 1
        following_index = following[index]
        if following_index != -1 and labels[following_index] == labels[index]:
            ends[index] = ends[following_index]
            following[index] = following[following_index]
            if following[index] != -1:
                previous[following[index]] = index
            active[following_index] = False
            versions[following_index] += 1
        versions[index] += 1
        enqueue(index)

    result = list(states)
    index = next(
        run_index
        for run_index in range(len(runs))
        if active[run_index] and previous[run_index] == -1
    )
    while index != -1:
        result[starts[index] : ends[index]] = [labels[index]] * (
            ends[index] - starts[index]
        )
        index = following[index]
    return result


def _label_runs(states: Sequence[CanonicalChord]) -> list[tuple[int, int]]:
    starts = [0]
    starts.extend(
        index for index in range(1, len(states)) if states[index] != states[index - 1]
    )
    return [
        (start, starts[index + 1] if index + 1 < len(starts) else len(states))
        for index, start in enumerate(starts)
    ]


def _events_from_frames(
    states: Sequence[CanonicalChord],
    confidences: Sequence[float],
    boundary_probabilities: NDArray[np.float64],
    times: NDArray[np.float64],
    duration_seconds: float,
    boundary_threshold: float,
) -> tuple[ScoredChordInterval, ...]:
    starts = [0]
    starts.extend(
        index
        for index in range(1, len(states))
        if states[index] != states[index - 1]
        or boundary_probabilities[index] >= boundary_threshold
    )
    raw: list[ScoredChordInterval] = []
    for run_index, start in enumerate(starts):
        end = starts[run_index + 1] if run_index + 1 < len(starts) else len(states)
        start_seconds = 0.0 if start == 0 else float(times[start])
        end_seconds = duration_seconds if end == len(states) else float(times[end])
        raw.append(
            ScoredChordInterval(
                start_seconds,
                end_seconds,
                states[start],
                float(np.mean(confidences[start:end])),
            )
        )
    merged: list[ScoredChordInterval] = []
    for event in raw:
        if merged and merged[-1].chord == event.chord:
            previous = merged.pop()
            previous_duration = previous.end_seconds - previous.start_seconds
            event_duration = event.end_seconds - event.start_seconds
            confidence = (
                previous.confidence * previous_duration
                + event.confidence * event_duration
            ) / (previous_duration + event_duration)
            merged.append(
                ScoredChordInterval(
                    previous.start_seconds,
                    event.end_seconds,
                    event.chord,
                    confidence,
                )
            )
        else:
            merged.append(event)
    return tuple(merged)
