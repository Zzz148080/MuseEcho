from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import median_filter


@dataclass(frozen=True)
class EnergySeries:
    resolution_seconds: float
    points: tuple[float, ...]
    confidence: float = 1.0
    algorithm: str = "rms-normalized-v1"


@dataclass(frozen=True)
class EnergyChange:
    timestamp_seconds: float
    direction: str
    magnitude: float
    confidence: float
    algorithm: str = "robust-smoothed-rms-delta-v2"


def extract_energy(
    samples: NDArray[np.float32],
    sample_rate: int,
    *,
    frame_length: int,
    hop_length: int,
    change_zscore: float,
    minimum_change: float,
    silence_rms: float,
    change_window_seconds: float = 0.5,
) -> tuple[EnergySeries, tuple[EnergyChange, ...]]:
    rms_values = _frame_rms(samples, frame_length=frame_length, hop_length=hop_length)
    peak_rms = float(np.max(rms_values))
    if peak_rms <= silence_rms:
        normalized = np.zeros_like(rms_values)
    else:
        normalized = rms_values / peak_rms
    series = EnergySeries(
        resolution_seconds=float(hop_length / sample_rate),
        points=tuple(float(value) for value in normalized),
    )
    changes = _find_energy_changes(
        normalized,
        sample_rate=sample_rate,
        frame_length=frame_length,
        hop_length=hop_length,
        change_zscore=change_zscore,
        minimum_change=minimum_change,
        change_window_seconds=change_window_seconds,
    )
    return series, changes


def _frame_rms(
    samples: NDArray[np.float32], *, frame_length: int, hop_length: int
) -> NDArray[np.float64]:
    if samples.size <= frame_length:
        starts: tuple[int, ...] | range = (0,)
    else:
        starts = range(0, samples.size - frame_length + 1, hop_length)
    values = [
        math.sqrt(
            float(
                np.mean(
                    np.square(samples[start : start + frame_length], dtype=np.float64),
                    dtype=np.float64,
                )
            )
        )
        for start in starts
    ]
    return np.asarray(values, dtype=np.float64)


def _find_energy_changes(
    normalized: NDArray[np.float64],
    *,
    sample_rate: int,
    frame_length: int,
    hop_length: int,
    change_zscore: float,
    minimum_change: float,
    change_window_seconds: float,
) -> tuple[EnergyChange, ...]:
    if normalized.size < 2 or float(np.max(normalized)) == 0.0:
        return ()
    requested_window = max(3, round(change_window_seconds * sample_rate / hop_length))
    if requested_window % 2 == 0:
        requested_window += 1
    maximum_window = normalized.size if normalized.size % 2 == 1 else normalized.size - 1
    window_frames = max(1, min(requested_window, maximum_window))
    smoothed = (
        median_filter(normalized, size=window_frames, mode="nearest")
        if window_frames >= 3
        else normalized
    )
    comparison_lag = max(1, window_frames // 2)
    deltas = smoothed[comparison_lag:] - smoothed[:-comparison_lag]
    median = float(np.median(deltas))
    deviations = np.abs(deltas - median)
    robust_sigma = 1.4826 * float(np.median(deviations))
    threshold = max(minimum_change, change_zscore * robust_sigma)
    candidates = [
        index
        for index, delta in enumerate(deltas)
        if index >= comparison_lag and abs(float(delta)) >= threshold
    ]
    if not candidates:
        return ()
    refractory_frames = max(window_frames, math.ceil(frame_length / hop_length))
    groups: list[list[int]] = []
    for candidate in candidates:
        if not groups or candidate - groups[-1][-1] > refractory_frames:
            groups.append([candidate])
        else:
            groups[-1].append(candidate)
    changes: list[EnergyChange] = []
    for group in groups:
        strongest = max(group, key=lambda index: abs(float(deltas[index]) - median))
        delta = float(deltas[strongest])
        magnitude = abs(delta)
        confidence_margin = max(1e-12, 1.0 - threshold)
        confidence = 0.7 + 0.3 * min(
            1.0,
            max(0.0, magnitude - threshold) / confidence_margin,
        )
        changes.append(
            EnergyChange(
                timestamp_seconds=float(
                    (strongest + comparison_lag / 2.0) * hop_length / sample_rate
                ),
                direction="rise" if delta > 0.0 else "fall",
                magnitude=float(magnitude),
                confidence=float(confidence),
            )
        )
    return tuple(changes)


def energy_to_dict(
    series: EnergySeries, changes: tuple[EnergyChange, ...]
) -> tuple[dict[str, object], list[dict[str, object]]]:
    payload = {
        "resolution_seconds": series.resolution_seconds,
        "points": list(series.points),
        "confidence": series.confidence,
        "algorithm": series.algorithm,
    }
    change_payload = [
        {
            "timestamp_seconds": change.timestamp_seconds,
            "direction": change.direction,
            "magnitude": change.magnitude,
            "confidence": change.confidence,
            "algorithm": change.algorithm,
        }
        for change in changes
    ]
    return payload, change_payload
