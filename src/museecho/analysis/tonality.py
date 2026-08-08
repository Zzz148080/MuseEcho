from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import librosa
import numpy as np

_PITCH_CLASS_NAMES = (
    "C",
    "C#",
    "D",
    "D#",
    "E",
    "F",
    "F#",
    "G",
    "G#",
    "A",
    "A#",
    "B",
)
_MAJOR_PROFILE = np.asarray(
    (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88),
    dtype=np.float64,
)
_MINOR_PROFILE = np.asarray(
    (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17),
    dtype=np.float64,
)
_MINIMUM_SIGNAL_RMS = 1e-4
_RMS_BLOCK_SAMPLES = 1_000_000
_N_FFT = 4_096
_HOP_LENGTH = 1_024
_CHROMA_CHUNK_SECONDS = 30.0


@dataclass(frozen=True)
class TonalityCandidate:
    tonic: str
    mode: str
    score: float


@dataclass(frozen=True)
class TonalityEstimate:
    tonic: str | None
    mode: str | None
    confidence: float | None
    stability: float
    top_candidates: tuple[TonalityCandidate, ...]
    algorithm: str = "tuning-aware-chroma-krumhansl-v1"

    def to_dict(self) -> dict[str, object]:
        return {
            "tonic": self.tonic,
            "mode": self.mode,
            "confidence": self.confidence,
            "stability": self.stability,
            "algorithm": self.algorithm,
        }


def estimate_tonality(
    samples: Sequence[float] | memoryview,
    sample_rate: int,
) -> TonalityEstimate:
    if type(sample_rate) is not int or sample_rate <= 0:
        raise ValueError("sample_rate must be a positive integer")
    array = np.asarray(samples, dtype=np.float32)
    if array.ndim != 1 or array.size == 0:
        raise ValueError("samples cannot be empty and must be one-dimensional")
    if not bool(np.all(np.isfinite(array))):
        raise ValueError("samples must be finite")
    if array.size < _N_FFT or _bounded_signal_rms(array) <= _MINIMUM_SIGNAL_RMS:
        return TonalityEstimate(None, None, None, 0.0, ())

    chroma = _chunked_chroma(array, sample_rate)
    profile = np.asarray(np.mean(chroma, axis=1, dtype=np.float64), dtype=np.float64)
    candidates = _rank_candidates(profile)
    top = candidates[0]
    runner_up = candidates[1]
    stability = _temporal_stability(
        chroma,
        top,
        window_frames=max(1, round(sample_rate / _HOP_LENGTH)),
    )
    margin = max(0.0, top.score - runner_up.score)
    profile_confidence = min(
        1.0,
        0.65 * max(0.0, top.score) + 0.35 * min(1.0, margin / 0.15),
    )
    confidence = 0.8 * profile_confidence + 0.2 * stability
    if confidence < 0.7 or stability < 0.7:
        return TonalityEstimate(None, None, None, stability, tuple(candidates[:3]))
    return TonalityEstimate(
        top.tonic,
        top.mode,
        float(confidence),
        stability,
        tuple(candidates[:3]),
    )


def _rank_candidates(profile: np.ndarray) -> list[TonalityCandidate]:
    standardized = _standardize(profile)
    candidates: list[TonalityCandidate] = []
    for mode, template in (("major", _MAJOR_PROFILE), ("minor", _MINOR_PROFILE)):
        standardized_template = _standardize(template)
        for tonic_index, tonic in enumerate(_PITCH_CLASS_NAMES):
            shifted = np.roll(standardized_template, tonic_index)
            score = float(np.dot(standardized, shifted) / standardized.size)
            candidates.append(TonalityCandidate(tonic, mode, score))
    return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)


def _standardize(values: np.ndarray) -> np.ndarray:
    centered = np.asarray(values, dtype=np.float64) - float(np.mean(values))
    scale = float(np.std(centered))
    if scale <= 1e-12:
        return np.zeros_like(centered)
    return centered / scale


def _bounded_signal_rms(samples: np.ndarray) -> float:
    square_sum = 0.0
    for start in range(0, samples.size, _RMS_BLOCK_SAMPLES):
        block = samples[start : start + _RMS_BLOCK_SAMPLES].astype(np.float64)
        square_sum += float(np.dot(block, block))
    return math.sqrt(square_sum / samples.size)


def _chunked_chroma(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    context_samples = math.ceil(_N_FFT / _HOP_LENGTH) * _HOP_LENGTH
    requested_chunk = math.floor(_CHROMA_CHUNK_SECONDS * sample_rate / _HOP_LENGTH) * _HOP_LENGTH
    chunk_samples = max(_HOP_LENGTH, requested_chunk)
    pieces: list[np.ndarray] = []
    for core_start in range(0, samples.size, chunk_samples):
        core_end = min(samples.size, core_start + chunk_samples)
        context_start = max(0, core_start - context_samples)
        context_end = min(samples.size, core_end + context_samples)
        chroma = librosa.feature.chroma_stft(
            y=samples[context_start:context_end],
            sr=sample_rate,
            n_fft=_N_FFT,
            hop_length=_HOP_LENGTH,
            tuning=None,
            norm=2,
            center=False,
        )
        first_frame = math.ceil((core_start - context_start) / _HOP_LENGTH)
        final_frame = math.ceil((core_end - context_start) / _HOP_LENGTH)
        pieces.append(chroma[:, first_frame : min(final_frame, chroma.shape[1])])
    return np.concatenate(pieces, axis=1)


def _temporal_stability(
    chroma: np.ndarray,
    candidate: TonalityCandidate,
    *,
    window_frames: int,
) -> float:
    scores: list[float] = []
    for start in range(0, chroma.shape[1], window_frames):
        window_profile = np.mean(chroma[:, start : start + window_frames], axis=1)
        matching = next(
            ranked
            for ranked in _rank_candidates(window_profile)
            if ranked.tonic == candidate.tonic and ranked.mode == candidate.mode
        )
        scores.append((matching.score + 1.0) / 2.0)
    return float(np.clip(np.mean(scores), 0.0, 1.0))
