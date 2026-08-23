from __future__ import annotations

import math
import warnings
from dataclasses import dataclass

import librosa
import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class BtcFeatureConfig:
    sample_rate: int
    n_bins: int
    bins_per_octave: int
    hop_length: int
    chunk_seconds: float
    timestep: int
    log_floor: float

    def __post_init__(self) -> None:
        integer_values = (
            self.sample_rate,
            self.n_bins,
            self.bins_per_octave,
            self.hop_length,
            self.timestep,
        )
        if any(type(value) is not int or value <= 0 for value in integer_values):
            raise ValueError("BTC feature integer parameters must be positive")
        if (
            isinstance(self.chunk_seconds, bool)
            or not math.isfinite(self.chunk_seconds)
            or self.chunk_seconds <= 0
            or isinstance(self.log_floor, bool)
            or not math.isfinite(self.log_floor)
            or self.log_floor <= 0
        ):
            raise ValueError("BTC feature floating parameters must be finite and positive")

    @property
    def frame_seconds(self) -> float:
        return self.chunk_seconds / self.timestep

    @classmethod
    def official(cls) -> BtcFeatureConfig:
        return cls(
            sample_rate=22_050,
            n_bins=144,
            bins_per_octave=24,
            hop_length=2_048,
            chunk_seconds=10.0,
            timestep=108,
            log_floor=1e-6,
        )


def extract_btc_features(
    samples: NDArray[np.float32],
    sample_rate: int,
    config: BtcFeatureConfig,
) -> NDArray[np.float32]:
    if (
        not isinstance(samples, np.ndarray)
        or samples.ndim != 1
        or samples.dtype != np.float32
        or samples.size == 0
        or not np.isfinite(samples).all()
    ):
        raise ValueError("BTC audio must be non-empty finite mono float32 samples")
    if type(sample_rate) is not int or sample_rate <= 0:
        raise ValueError("BTC sample rate must be a positive integer")

    audio = np.ascontiguousarray(samples)
    if sample_rate != config.sample_rate:
        audio = np.asarray(
            librosa.resample(
                audio,
                orig_sr=sample_rate,
                target_sr=config.sample_rate,
                res_type="soxr_hq",
            ),
            dtype=np.float32,
        )
    chunk_samples = int(config.sample_rate * config.chunk_seconds)
    pieces: list[NDArray[np.complexfloating]] = []
    for start in range(0, audio.size, chunk_samples):
        chunk = audio[start : start + chunk_samples]
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"n_fft=.* is too large for input signal of length=.*",
                category=UserWarning,
            )
            cqt = librosa.cqt(
                y=chunk,
                sr=config.sample_rate,
                n_bins=config.n_bins,
                bins_per_octave=config.bins_per_octave,
                hop_length=config.hop_length,
            )
        pieces.append(np.asarray(cqt))
    combined = np.concatenate(pieces, axis=1)
    features = np.asarray(
        np.log(np.abs(combined) + config.log_floor).T,
        dtype=np.float32,
    )
    if (
        features.ndim != 2
        or features.shape[0] == 0
        or features.shape[1] != config.n_bins
        or not np.isfinite(features).all()
    ):
        raise RuntimeError("BTC feature extraction returned an invalid result")
    return np.ascontiguousarray(features)


def standardize_btc_features(
    features: NDArray[np.float32],
    mean: float,
    std: float,
) -> NDArray[np.float32]:
    if (
        not isinstance(features, np.ndarray)
        or features.ndim != 2
        or features.dtype != np.float32
        or features.size == 0
        or not np.isfinite(features).all()
    ):
        raise ValueError("BTC features must be a finite float32 matrix")
    if (
        isinstance(mean, bool)
        or not isinstance(mean, (int, float))
        or not math.isfinite(mean)
        or isinstance(std, bool)
        or not isinstance(std, (int, float))
        or not math.isfinite(std)
        or std <= 0
    ):
        raise ValueError("BTC normalization statistics must be finite with positive std")
    normalized = np.asarray((features - mean) / std, dtype=np.float32)
    if not np.isfinite(normalized).all():
        raise ValueError("BTC normalization produced non-finite features")
    return np.ascontiguousarray(normalized)
