from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


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
    algorithm: str = "robust-rms-delta-v1"


def extract_energy(
    samples: NDArray[np.float32],
    sample_rate: int,
    *,
    frame_length: int,
    hop_length: int,
    change_zscore: float,
    minimum_change: float,
    silence_rms: float,
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
) -> tuple[EnergyChange, ...]:
    if normalized.size < 2 or float(np.max(normalized)) == 0.0:
        return ()
    deltas = np.diff(normalized)
    median = float(np.median(deltas))
    deviations = np.abs(deltas - median)
    robust_sigma = 1.4826 * float(np.median(deviations))
    threshold = max(minimum_change, change_zscore * robust_sigma)
    candidates = [
        index for index, delta in enumerate(deltas) if abs(float(delta) - median) >= threshold
    ]
    if not candidates:
        return ()
    refractory_frames = max(1, math.ceil(frame_length / hop_length))
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
        magnitude = abs(delta - median)
        confidence_margin = max(1e-12, 1.0 - threshold)
        confidence = 0.7 + 0.3 * min(
            1.0,
            max(0.0, magnitude - threshold) / confidence_margin,
        )
        changes.append(
            EnergyChange(
                timestamp_seconds=float((strongest + 1) * hop_length / sample_rate),
                direction="rise" if delta > median else "fall",
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
