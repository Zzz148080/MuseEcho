from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray

from museecho_ml.evaluation.metrics import ScoredChordInterval
from museecho_ml.labels import CanonicalChord

BTC_ROOTS = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
BTC_QUALITIES = (
    "min",
    "maj",
    "dim",
    "aug",
    "min6",
    "maj6",
    "min7",
    "minmaj7",
    "maj7",
    "7",
    "dim7",
    "hdim7",
    "sus2",
    "sus4",
)
UNSUPPORTED_QUALITIES = frozenset(("aug", "min6", "maj6", "minmaj7", "dim7"))


def decode_btc_class(index: int) -> CanonicalChord:
    if type(index) is not int or not 0 <= index < 170:
        raise ValueError("BTC class index must be an integer within [0, 169]")
    if index == 168:
        return CanonicalChord("X", "X", "X")
    if index == 169:
        return CanonicalChord("N", "N", "N")
    root_index, quality_index = divmod(index, len(BTC_QUALITIES))
    quality = BTC_QUALITIES[quality_index]
    if quality in UNSUPPORTED_QUALITIES:
        return CanonicalChord("X", "X", "X", f"unsupported-quality:{quality}")
    return CanonicalChord(BTC_ROOTS[root_index], quality, "1")


def frames_to_intervals(
    class_ids: NDArray[np.integer],
    confidences: NDArray[np.floating],
    frame_seconds: float,
    duration_seconds: float,
) -> tuple[ScoredChordInterval, ...]:
    classes = np.asarray(class_ids)
    scores = np.asarray(confidences)
    if classes.ndim != 1 or scores.ndim != 1:
        raise ValueError("BTC frame arrays must be one-dimensional")
    if classes.size == 0:
        raise ValueError("BTC frame arrays must be non-empty")
    if classes.size != scores.size:
        raise ValueError("BTC frame arrays must have equal length")
    if np.issubdtype(classes.dtype, np.bool_) or not np.issubdtype(
        classes.dtype, np.integer
    ):
        raise ValueError("BTC class IDs must be integers")
    try:
        numeric_scores = scores.astype(np.float64, copy=False)
    except (TypeError, ValueError) as error:
        raise ValueError("BTC frame confidence values are invalid") from error
    if not np.isfinite(numeric_scores).all() or np.any(
        (numeric_scores < 0) | (numeric_scores > 1)
    ):
        raise ValueError("BTC frame confidence must be finite and within [0, 1]")
    if (
        isinstance(frame_seconds, bool)
        or not math.isfinite(frame_seconds)
        or frame_seconds <= 0
    ):
        raise ValueError("BTC frame duration must be finite and positive")
    if (
        isinstance(duration_seconds, bool)
        or not math.isfinite(duration_seconds)
        or duration_seconds <= 0
    ):
        raise ValueError("BTC track duration must be finite and positive")
    if (classes.size - 1) * frame_seconds >= duration_seconds:
        raise ValueError("BTC timeline contains impossible extra frames")

    decoded = tuple(decode_btc_class(int(index)) for index in classes)
    intervals: list[ScoredChordInterval] = []
    current_chord = decoded[0]
    current_start = 0.0
    weighted_confidence = 0.0
    current_duration = 0.0
    for frame_index, (chord, confidence) in enumerate(
        zip(decoded, numeric_scores, strict=True)
    ):
        frame_start = frame_index * frame_seconds
        frame_end = min((frame_index + 1) * frame_seconds, duration_seconds)
        if chord != current_chord:
            intervals.append(
                ScoredChordInterval(
                    current_start,
                    frame_start,
                    current_chord,
                    weighted_confidence / current_duration,
                )
            )
            current_chord = chord
            current_start = frame_start
            weighted_confidence = 0.0
            current_duration = 0.0
        frame_duration = frame_end - frame_start
        weighted_confidence += float(confidence) * frame_duration
        current_duration += frame_duration
    intervals.append(
        ScoredChordInterval(
            current_start,
            duration_seconds,
            current_chord,
            weighted_confidence / current_duration,
        )
    )
    return tuple(intervals)
