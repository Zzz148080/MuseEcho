from __future__ import annotations

import math

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


def time_stretch_example(
    features: FeatureSequence,
    intervals: tuple[ChordInterval, ...],
    *,
    rate: float,
) -> tuple[FeatureSequence, tuple[ChordInterval, ...]]:
    """Resample feature time and scale interval boundaries by the same rate."""

    if (
        isinstance(rate, bool)
        or not isinstance(rate, (int, float))
        or not math.isfinite(rate)
        or not 0.5 <= rate <= 2.0
    ):
        raise ValueError("time-stretch rate must be finite and within [0.5, 2.0]")
    frame_count = features.main_cqt.shape[1]
    if (
        frame_count == 0
        or features.bass_cqt.shape[1] != frame_count
        or features.frame_times.shape != (frame_count,)
        or features.valid_mask.shape != (frame_count,)
    ):
        raise ValueError("time-stretch features have inconsistent time axes")
    output_frames = max(1, round(frame_count / rate))
    source_positions = np.minimum(
        np.arange(output_frames, dtype=np.float64) * rate,
        frame_count - 1,
    )
    stretched = FeatureSequence(
        main_cqt=_interpolate_time(features.main_cqt, source_positions),
        bass_cqt=_interpolate_time(features.bass_cqt, source_positions),
        frame_times=_stretched_frame_times(features.frame_times, output_frames),
        valid_mask=np.asarray(
            source_positions < int(np.count_nonzero(features.valid_mask)), dtype=np.bool_
        ),
    )
    labels = tuple(
        ChordInterval(
            interval.start_seconds / rate,
            interval.end_seconds / rate,
            interval.chord,
        )
        for interval in intervals
    )
    return stretched, labels


def sample_time_stretch_rate(
    *,
    seed: int,
    minimum: float,
    maximum: float,
    enabled: bool = True,
) -> float:
    if type(seed) is not int or seed < 0:
        raise ValueError("time-stretch seed must be a non-negative integer")
    if type(enabled) is not bool:
        raise ValueError("time-stretch enabled must be boolean")
    if not enabled:
        return 1.0
    if (
        isinstance(minimum, bool)
        or isinstance(maximum, bool)
        or not isinstance(minimum, (int, float))
        or not isinstance(maximum, (int, float))
        or not math.isfinite(minimum)
        or not math.isfinite(maximum)
        or not 0.5 <= minimum <= maximum <= 2.0
    ):
        raise ValueError("time-stretch bounds must be finite and within [0.5, 2.0]")
    return float(np.random.default_rng(seed).uniform(minimum, maximum))


def _interpolate_time(values: np.ndarray, source_positions: np.ndarray) -> np.ndarray:
    source_axis = np.arange(values.shape[1], dtype=np.float64)
    result = np.stack(
        [np.interp(source_positions, source_axis, row) for row in values], axis=0
    )
    return np.asarray(result, dtype=values.dtype)


def _stretched_frame_times(frame_times: np.ndarray, frame_count: int) -> np.ndarray:
    if len(frame_times) == 1:
        return np.full(frame_count, frame_times[0], dtype=np.float64)
    step = float(np.median(np.diff(frame_times)))
    if not math.isfinite(step) or step <= 0:
        raise ValueError("time-stretch frame times must be strictly increasing")
    return frame_times[0] + np.arange(frame_count, dtype=np.float64) * step
