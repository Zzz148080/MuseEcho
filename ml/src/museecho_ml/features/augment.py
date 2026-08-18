from __future__ import annotations

import numpy as np

from museecho_ml.data.manifest import ChordInterval
from museecho_ml.features.cqt import FeatureSequence


def transpose_example(
    features: FeatureSequence,
    intervals: tuple[ChordInterval, ...],
    *,
    semitones: int,
    bins_per_octave: int,
) -> tuple[FeatureSequence, tuple[ChordInterval, ...]]:
    """Apply one integer-semitone shift to CQT bins and chord labels."""

    if type(semitones) is not int:
        raise ValueError("transposition semitones must be an integer")
    if type(bins_per_octave) is not int or bins_per_octave <= 0:
        raise ValueError("transposition bins_per_octave must be a positive integer")
    if bins_per_octave % 12:
        raise ValueError("transposition bins_per_octave must be divisible by 12")
    shift_bins = semitones * bins_per_octave // 12
    if abs(shift_bins) >= min(features.main_cqt.shape[0], features.bass_cqt.shape[0]):
        raise ValueError("transposition shift exceeds the feature frequency range")
    shifted = FeatureSequence(
        main_cqt=_shift_frequency(features.main_cqt, shift_bins),
        bass_cqt=_shift_frequency(features.bass_cqt, shift_bins),
        frame_times=features.frame_times.copy(),
        valid_mask=features.valid_mask.copy(),
    )
    labels = tuple(
        ChordInterval(
            interval.start_seconds,
            interval.end_seconds,
            interval.chord.transpose(semitones),
        )
        for interval in intervals
    )
    return shifted, labels


def _shift_frequency(values: np.ndarray, bins: int) -> np.ndarray:
    result = np.zeros_like(values)
    if bins > 0:
        result[bins:] = values[:-bins]
    elif bins < 0:
        result[:bins] = values[-bins:]
    else:
        result[:] = values
    return result
