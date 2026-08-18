from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import librosa
import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class CqtConfig:
    sample_rate: int = 22_050
    hop_length: int = 512
    fmin_hz: float = 32.70319566257483
    bins_per_octave: int = 24
    n_octaves: int = 6
    bass_octaves: int = 3
    log_scale: float = 10.0
    minimum_analysis_seconds: float = 2.0

    def __post_init__(self) -> None:
        integer_fields = (
            self.sample_rate,
            self.hop_length,
            self.bins_per_octave,
            self.n_octaves,
            self.bass_octaves,
        )
        if any(type(value) is not int or value <= 0 for value in integer_fields):
            raise ValueError("CQT integer parameters must be positive integers")
        if self.bass_octaves > self.n_octaves:
            raise ValueError("CQT bass_octaves cannot exceed n_octaves")
        if (
            isinstance(self.fmin_hz, bool)
            or not isinstance(self.fmin_hz, (int, float))
            or not math.isfinite(self.fmin_hz)
            or self.fmin_hz <= 0
            or isinstance(self.log_scale, bool)
            or not isinstance(self.log_scale, (int, float))
            or not math.isfinite(self.log_scale)
            or self.log_scale <= 0
            or isinstance(self.minimum_analysis_seconds, bool)
            or not isinstance(self.minimum_analysis_seconds, (int, float))
            or not math.isfinite(self.minimum_analysis_seconds)
            or self.minimum_analysis_seconds <= 0
        ):
            raise ValueError("CQT frequency and log parameters must be finite and positive")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CqtConfig:
        required = {
            "schema_version",
            "feature_version",
            "sample_rate",
            "hop_length",
            "fmin_hz",
            "bins_per_octave",
            "n_octaves",
            "bass_octaves",
            "log_scale",
            "minimum_analysis_seconds",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("CQT config fields are invalid")
        if value["schema_version"] != 1 or value["feature_version"] != "1.0.0":
            raise ValueError("CQT config version is unsupported")
        return cls(
            sample_rate=value["sample_rate"],
            hop_length=value["hop_length"],
            fmin_hz=value["fmin_hz"],
            bins_per_octave=value["bins_per_octave"],
            n_octaves=value["n_octaves"],
            bass_octaves=value["bass_octaves"],
            log_scale=value["log_scale"],
            minimum_analysis_seconds=value["minimum_analysis_seconds"],
        )


@dataclass(frozen=True)
class FeatureSequence:
    main_cqt: NDArray[np.float32]
    bass_cqt: NDArray[np.float32]
    frame_times: NDArray[np.float64]
    valid_mask: NDArray[np.bool_]


def extract_features(
    audio: NDArray[np.generic], *, sample_rate: int, config: CqtConfig
) -> FeatureSequence:
    """Extract aligned log-CQT and low-frequency views from finite mono PCM."""

    if not isinstance(audio, np.ndarray) or audio.ndim != 1:
        raise ValueError("CQT audio must be a mono numpy array")
    if audio.size == 0:
        raise ValueError("CQT audio must be non-empty")
    if type(sample_rate) is not int or sample_rate <= 0:
        raise ValueError("CQT sample_rate must be a positive integer")
    if not np.issubdtype(audio.dtype, np.number):
        raise ValueError("CQT audio must contain numeric samples")
    samples = _float_audio(audio)
    if not np.isfinite(samples).all():
        raise ValueError("CQT audio samples must be finite")
    if sample_rate != config.sample_rate:
        samples = librosa.resample(
            samples,
            orig_sr=sample_rate,
            target_sr=config.sample_rate,
            res_type="soxr_hq",
        )
    duration_seconds = len(samples) / config.sample_rate
    minimum_samples = math.ceil(config.minimum_analysis_seconds * config.sample_rate)
    analysis_samples = (
        np.pad(samples, (0, minimum_samples - len(samples)))
        if len(samples) < minimum_samples
        else samples
    )
    n_bins = config.bins_per_octave * config.n_octaves
    complex_cqt = librosa.cqt(
        y=analysis_samples,
        sr=config.sample_rate,
        hop_length=config.hop_length,
        fmin=float(config.fmin_hz),
        n_bins=n_bins,
        bins_per_octave=config.bins_per_octave,
        pad_mode="constant",
    )
    main = np.asarray(
        np.log1p(float(config.log_scale) * np.abs(complex_cqt)), dtype=np.float32
    )
    if main.ndim != 2 or main.shape[0] != n_bins or main.shape[1] == 0:
        raise RuntimeError("CQT extractor returned an invalid feature shape")
    if not np.isfinite(main).all():
        raise RuntimeError("CQT extractor returned non-finite features")
    bass_bins = config.bins_per_octave * config.bass_octaves
    bass = np.ascontiguousarray(main[:bass_bins])
    frame_times = librosa.frames_to_time(
        np.arange(main.shape[1]),
        sr=config.sample_rate,
        hop_length=config.hop_length,
    ).astype(np.float64, copy=False)
    valid_mask = np.asarray(frame_times < duration_seconds, dtype=np.bool_)
    return FeatureSequence(
        main_cqt=np.ascontiguousarray(main),
        bass_cqt=bass,
        frame_times=frame_times,
        valid_mask=valid_mask,
    )


def _float_audio(audio: NDArray[np.generic]) -> NDArray[np.float32]:
    if np.issubdtype(audio.dtype, np.integer):
        info = np.iinfo(audio.dtype)
        scale = max(abs(info.min), abs(info.max))
        return np.asarray(audio, dtype=np.float32) / scale
    return np.asarray(audio, dtype=np.float32)
