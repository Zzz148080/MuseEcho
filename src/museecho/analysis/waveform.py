from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class WaveformSeries:
    resolution_seconds: float
    minimums: tuple[float, ...]
    maximums: tuple[float, ...]
    confidence: float = 1.0
    algorithm: str = "waveform-minmax-v1"


def extract_waveform(
    samples: NDArray[np.float32],
    sample_rate: int,
    *,
    bucket_count: int,
) -> WaveformSeries:
    actual_bucket_count = min(bucket_count, samples.size)
    boundaries = np.linspace(0, samples.size, actual_bucket_count + 1, dtype=np.int64)
    minimums: list[float] = []
    maximums: list[float] = []
    for index in range(actual_bucket_count):
        bucket = samples[boundaries[index] : boundaries[index + 1]]
        # Lossy codecs may reconstruct samples slightly outside the normalised
        # PCM range.  The visual contract is deliberately bounded to [-1, 1].
        minimums.append(float(np.clip(np.min(bucket), -1.0, 1.0)))
        maximums.append(float(np.clip(np.max(bucket), -1.0, 1.0)))
    duration_seconds = samples.size / sample_rate
    return WaveformSeries(
        resolution_seconds=float(duration_seconds / actual_bucket_count),
        minimums=tuple(minimums),
        maximums=tuple(maximums),
    )


def waveform_to_dict(series: WaveformSeries) -> dict[str, object]:
    return {
        "resolution_seconds": series.resolution_seconds,
        "minimums": list(series.minimums),
        "maximums": list(series.maximums),
        "confidence": series.confidence,
        "algorithm": series.algorithm,
    }
