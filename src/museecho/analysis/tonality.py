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
_PITCH_CLASS_INDEX = {name: index for index, name in enumerate(_PITCH_CLASS_NAMES)}
_MAJOR_PROFILE = np.asarray(
    (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88),
    dtype=np.float64,
)
_MINOR_PROFILE = np.asarray(
    (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17),
    dtype=np.float64,
)
_MINIMUM_SIGNAL_RMS = 1e-4
_CONFIDENT_SIGNAL_RMS = 1e-3
_RMS_BLOCK_SAMPLES = 1_000_000
_N_FFT = 4_096
_HOP_LENGTH = 1_024
_CHROMA_CHUNK_SECONDS = 30.0
_ANALYSIS_SAMPLE_RATE = 22_050
_MINIMUM_SAMPLE_RATE = 8_000
_MAXIMUM_SAMPLE_RATE = 192_000
_MAXIMUM_DURATION_SECONDS = 600.0


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
    if not _MINIMUM_SAMPLE_RATE <= sample_rate <= _MAXIMUM_SAMPLE_RATE:
        raise ValueError("sample_rate must be between 8000 and 192000")
    array = np.asarray(samples, dtype=np.float32)
    if array.ndim != 1 or array.size == 0:
        raise ValueError("samples cannot be empty and must be one-dimensional")
    if array.size > sample_rate * _MAXIMUM_DURATION_SECONDS:
        raise ValueError("duration cannot exceed 600 seconds")
    if not bool(np.all(np.isfinite(array))):
        raise ValueError("samples must be finite")
    if sample_rate != _ANALYSIS_SAMPLE_RATE:
        array = np.ascontiguousarray(
            librosa.resample(
                array,
                orig_sr=sample_rate,
                target_sr=_ANALYSIS_SAMPLE_RATE,
                res_type="soxr_hq",
                scale=False,
            ),
            dtype=np.float32,
        )
        sample_rate = _ANALYSIS_SAMPLE_RATE
    signal_rms = _bounded_signal_rms(array)
    if array.size < _N_FFT or signal_rms <= _MINIMUM_SIGNAL_RMS:
        return TonalityEstimate(None, None, None, 0.0, ())
    signal_strength = float(
        np.clip(
            (signal_rms - _MINIMUM_SIGNAL_RMS) / (_CONFIDENT_SIGNAL_RMS - _MINIMUM_SIGNAL_RMS),
            0.0,
            1.0,
        )
    )
    activity_evidence = _active_audio_evidence(array, sample_rate)

    chroma = _chunked_chroma(array, sample_rate)
    profile = np.asarray(np.mean(chroma, axis=1, dtype=np.float64), dtype=np.float64)
    candidates = _rank_candidates(profile)
    top = candidates[0]
    runner_up = candidates[1]
    pitch_class_coverage = _pitch_class_coverage(profile)
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
    confidence = (
        0.65 * profile_confidence
        + 0.15 * stability
        + 0.1 * signal_strength
        + 0.1 * activity_evidence
    )
    if (
        confidence < 0.7
        or stability < 0.7
        or pitch_class_coverage < 0.6
        or signal_strength < 0.2
        or activity_evidence < 0.5
    ):
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


def _pitch_class_coverage(profile: np.ndarray) -> float:
    nonnegative = np.maximum(np.asarray(profile, dtype=np.float64), 0.0)
    total = float(np.sum(nonnegative))
    if total <= 1e-12:
        return 0.0
    probabilities = nonnegative / total
    entropy = -sum(float(value) * math.log(float(value)) for value in probabilities if value > 0.0)
    effective_pitch_classes = math.exp(entropy)
    return float(np.clip((effective_pitch_classes - 6.5) / 2.0, 0.0, 1.0))


def _bounded_signal_rms(samples: np.ndarray) -> float:
    square_sum = 0.0
    for start in range(0, samples.size, _RMS_BLOCK_SAMPLES):
        block = samples[start : start + _RMS_BLOCK_SAMPLES].astype(np.float64)
        square_sum += float(np.dot(block, block))
    return math.sqrt(square_sum / samples.size)


def _active_audio_evidence(samples: np.ndarray, sample_rate: int) -> float:
    frame_count = 0
    active_frame_count = 0
    for start in range(0, samples.size - _N_FFT + 1, _HOP_LENGTH):
        frame = samples[start : start + _N_FFT].astype(np.float64)
        frame_rms = math.sqrt(float(np.dot(frame, frame)) / frame.size)
        frame_count += 1
        if frame_rms > _MINIMUM_SIGNAL_RMS:
            active_frame_count += 1
    if frame_count == 0 or active_frame_count == 0:
        return 0.0
    active_ratio = active_frame_count / frame_count
    active_duration = active_frame_count * _HOP_LENGTH / sample_rate
    duration_evidence = min(1.0, active_duration / 2.0)
    return math.sqrt(active_ratio * duration_evidence)


def _chunked_chroma(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    context_samples = math.ceil(_N_FFT / _HOP_LENGTH) * _HOP_LENGTH
    requested_chunk = math.floor(_CHROMA_CHUNK_SECONDS * sample_rate / _HOP_LENGTH) * _HOP_LENGTH
    chunk_samples = max(_HOP_LENGTH, requested_chunk)
    pieces: list[np.ndarray] = []
    for core_start in range(0, samples.size, chunk_samples):
        core_end = min(samples.size, core_start + chunk_samples)
        context_start = max(0, core_start - context_samples)
        context_end = min(samples.size, core_end + context_samples)
        chunk = samples[context_start:context_end]
        available_frames = max(0, 1 + (chunk.size - _N_FFT) // _HOP_LENGTH)
        first_frame = math.ceil((core_start - context_start) / _HOP_LENGTH)
        final_frame = math.ceil((core_end - context_start) / _HOP_LENGTH)
        piece_frames = max(0, min(final_frame, available_frames) - first_frame)
        if _bounded_signal_rms(chunk) <= _MINIMUM_SIGNAL_RMS:
            pieces.append(np.zeros((12, piece_frames), dtype=np.float64))
            continue
        chroma = librosa.feature.chroma_stft(
            y=chunk,
            sr=sample_rate,
            n_fft=_N_FFT,
            hop_length=_HOP_LENGTH,
            tuning=None,
            norm=2,
            center=False,
        )
        pieces.append(chroma[:, first_frame : min(final_frame, chroma.shape[1])])
    return np.concatenate(pieces, axis=1)


def _temporal_stability(
    chroma: np.ndarray,
    candidate: TonalityCandidate,
    *,
    window_frames: int,
) -> float:
    scale_scores = [
        _window_key_consistency(
            chroma,
            candidate,
            window_frames=window_frames * multiplier,
        )
        for multiplier in (1, 2, 4)
    ]
    valid_scores = [score for score in scale_scores if score is not None]
    if not valid_scores:
        return 0.0
    return float(min(valid_scores))


def _window_key_consistency(
    chroma: np.ndarray,
    candidate: TonalityCandidate,
    *,
    window_frames: int,
) -> float | None:
    scores: list[float] = []
    for start in range(0, chroma.shape[1], window_frames):
        window_profile = np.mean(chroma[:, start : start + window_frames], axis=1)
        if float(np.sum(window_profile)) <= 1e-12:
            continue
        local_candidates = _rank_candidates(window_profile)
        local_top = local_candidates[0]
        local_margin = max(0.0, local_top.score - local_candidates[1].score)
        decisiveness = min(1.0, local_margin / 0.2)
        if _keys_are_compatible(candidate, local_top):
            scores.append(0.8 + 0.2 * decisiveness)
        elif local_margin < 0.05:
            scores.append(0.5)
        else:
            scores.append(0.0)
    if not scores:
        return None
    return float(np.clip(np.mean(scores), 0.0, 1.0))


def _keys_are_compatible(
    global_candidate: TonalityCandidate,
    local_candidate: TonalityCandidate,
) -> bool:
    global_tonic = _PITCH_CLASS_INDEX[global_candidate.tonic]
    local_tonic = _PITCH_CLASS_INDEX[local_candidate.tonic]
    interval = (local_tonic - global_tonic) % 12
    if global_candidate.mode == "major":
        compatible = {
            (0, "major"),
            (5, "major"),
            (7, "major"),
            (2, "minor"),
            (4, "minor"),
            (9, "minor"),
        }
    else:
        compatible = {
            (0, "minor"),
            (5, "minor"),
            (7, "minor"),
            (7, "major"),
            (3, "major"),
            (10, "major"),
        }
    return (interval, local_candidate.mode) in compatible
