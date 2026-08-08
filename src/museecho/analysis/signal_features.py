from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from museecho.analysis.energy import EnergyChange, EnergySeries, energy_to_dict, extract_energy
from museecho.analysis.rhythm import RhythmEstimate, estimate_rhythm, rhythm_to_dict
from museecho.analysis.waveform import WaveformSeries, extract_waveform, waveform_to_dict


@dataclass(frozen=True)
class SignalFeatureConfig:
    version: str = "signal-v1"
    waveform_bucket_count: int = 1_000
    frame_length: int = 2_048
    hop_length: int = 512
    energy_change_zscore: float = 3.5
    minimum_energy_change: float = 0.08
    energy_change_window_seconds: float = 0.5
    minimum_rhythm_seconds: float = 2.0
    minimum_signal_rms: float = 1e-4
    minimum_rhythm_confidence: float = 0.55
    minimum_onset_periodicity: float = 0.2
    maximum_beat_accent_imbalance: float = 0.25
    maximum_rhythm_sample_rate: int = 3_000
    rhythm_n_fft: int = 512
    rhythm_band_count: int = 32
    rhythm_chunk_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("version cannot be empty")
        _require_positive_int(self.waveform_bucket_count, "waveform_bucket_count")
        _require_positive_int(self.frame_length, "frame_length")
        _require_positive_int(self.hop_length, "hop_length")
        if self.hop_length > self.frame_length:
            raise ValueError("hop_length cannot exceed frame_length")
        _require_positive_finite(self.energy_change_zscore, "energy_change_zscore")
        _require_positive_finite(self.minimum_energy_change, "minimum_energy_change")
        if self.minimum_energy_change > 1.0:
            raise ValueError("minimum_energy_change cannot exceed 1")
        _require_positive_finite(self.energy_change_window_seconds, "energy_change_window_seconds")
        if not 0.1 <= self.energy_change_window_seconds <= 5.0:
            raise ValueError("energy_change_window_seconds must be between 0.1 and 5")
        _require_positive_finite(self.minimum_rhythm_seconds, "minimum_rhythm_seconds")
        _require_nonnegative_finite(self.minimum_signal_rms, "minimum_signal_rms")
        if not 0.0 <= self.minimum_rhythm_confidence <= 1.0:
            raise ValueError("minimum_rhythm_confidence must be between 0 and 1")
        if not 0.0 <= self.minimum_onset_periodicity <= 1.0:
            raise ValueError("minimum_onset_periodicity must be between 0 and 1")
        if not 0.0 <= self.maximum_beat_accent_imbalance <= 1.0:
            raise ValueError("maximum_beat_accent_imbalance must be between 0 and 1")
        _require_positive_int(self.maximum_rhythm_sample_rate, "maximum_rhythm_sample_rate")
        if not 1_000 <= self.maximum_rhythm_sample_rate <= 8_000:
            raise ValueError("maximum_rhythm_sample_rate must be between 1000 and 8000")
        _require_positive_int(self.rhythm_n_fft, "rhythm_n_fft")
        if not 128 <= self.rhythm_n_fft <= 2_048 or self.rhythm_n_fft.bit_count() != 1:
            raise ValueError("rhythm_n_fft must be a power of two between 128 and 2048")
        _require_positive_int(self.rhythm_band_count, "rhythm_band_count")
        if not 8 <= self.rhythm_band_count <= 128:
            raise ValueError("rhythm_band_count must be between 8 and 128")
        _require_positive_finite(self.rhythm_chunk_seconds, "rhythm_chunk_seconds")
        if not 5.0 <= self.rhythm_chunk_seconds <= 60.0:
            raise ValueError("rhythm_chunk_seconds must be between 5 and 60")
        if self.rhythm_n_fft > (self.maximum_rhythm_sample_rate * self.minimum_rhythm_seconds):
            raise ValueError("rhythm_n_fft cannot exceed the minimum rhythm input length")


@dataclass(frozen=True)
class SignalFeatures:
    duration_seconds: float
    config_version: str
    waveform: WaveformSeries
    rhythm: RhythmEstimate
    energy: EnergySeries
    energy_changes: tuple[EnergyChange, ...]

    @property
    def bpm(self) -> float | None:
        return self.rhythm.bpm

    @property
    def bpm_confidence(self) -> float | None:
        return self.rhythm.confidence

    @property
    def beat_positions_seconds(self) -> tuple[float, ...]:
        return self.rhythm.beat_positions_seconds

    @property
    def rhythm_algorithm(self) -> str:
        return self.rhythm.algorithm

    def to_dict(self) -> dict[str, object]:
        energy, changes = energy_to_dict(self.energy, self.energy_changes)
        return {
            "duration_seconds": self.duration_seconds,
            "config_version": self.config_version,
            "waveform": waveform_to_dict(self.waveform),
            "rhythm": rhythm_to_dict(self.rhythm),
            "energy": energy,
            "energy_changes": changes,
        }


def extract_signal_features(
    samples: Sequence[float] | memoryview,
    sample_rate: int,
    *,
    config: SignalFeatureConfig | None = None,
) -> SignalFeatures:
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    array = np.asarray(samples, dtype=np.float32)
    if array.ndim != 1 or array.size == 0:
        raise ValueError("samples cannot be empty and must be one-dimensional")
    if not bool(np.all(np.isfinite(array))):
        raise ValueError("samples must be finite")
    selected = config or SignalFeatureConfig()
    waveform = extract_waveform(
        array,
        sample_rate,
        bucket_count=selected.waveform_bucket_count,
    )
    energy, energy_changes = extract_energy(
        array,
        sample_rate,
        frame_length=selected.frame_length,
        hop_length=selected.hop_length,
        change_zscore=selected.energy_change_zscore,
        minimum_change=selected.minimum_energy_change,
        silence_rms=selected.minimum_signal_rms,
        change_window_seconds=selected.energy_change_window_seconds,
    )
    rhythm = estimate_rhythm(
        array,
        sample_rate,
        hop_length=selected.hop_length,
        minimum_duration_seconds=selected.minimum_rhythm_seconds,
        minimum_signal_rms=selected.minimum_signal_rms,
        minimum_confidence=selected.minimum_rhythm_confidence,
        minimum_onset_periodicity=selected.minimum_onset_periodicity,
        maximum_beat_accent_imbalance=selected.maximum_beat_accent_imbalance,
        maximum_sample_rate=selected.maximum_rhythm_sample_rate,
        n_fft=selected.rhythm_n_fft,
        band_count=selected.rhythm_band_count,
        chunk_seconds=selected.rhythm_chunk_seconds,
    )
    return SignalFeatures(
        duration_seconds=float(array.size / sample_rate),
        config_version=selected.version,
        waveform=waveform,
        rhythm=rhythm,
        energy=energy,
        energy_changes=energy_changes,
    )


def _require_positive_finite(value: float, name: str) -> None:
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be positive and finite")


def _require_nonnegative_finite(value: float, name: str) -> None:
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be nonnegative and finite")


def _require_positive_int(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
