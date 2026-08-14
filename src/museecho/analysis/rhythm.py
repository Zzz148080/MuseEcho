from __future__ import annotations

import math
from dataclasses import dataclass

import librosa
import numpy as np
from numpy.typing import NDArray

_MINIMUM_BPM = 40.0
_MAXIMUM_BPM = 240.0
_RMS_BLOCK_SAMPLES = 1_000_000
_BEAT_CONTEXT_SECONDS = 4.0
_TENTATIVE_MINIMUM_DURATION_SECONDS = 30.0
_TENTATIVE_THRESHOLD_RATIO = 0.75
_TENTATIVE_CONFIDENCE_MARGIN = 0.05
_TENTATIVE_ACCENT_RATIO = 0.5
_TENTATIVE_HALF_TEMPO_BPM = 150.0
_TENTATIVE_HALF_CONFIDENCE_TOLERANCE = 0.02


@dataclass(frozen=True)
class RhythmEstimate:
    bpm: float | None
    confidence: float | None
    beat_positions_seconds: tuple[float, ...]
    algorithm: str = "librosa-onset-beat-periodicity-v3"


def estimate_rhythm(
    samples: NDArray[np.float32],
    sample_rate: int,
    *,
    hop_length: int,
    minimum_duration_seconds: float,
    minimum_signal_rms: float,
    minimum_confidence: float,
    minimum_onset_periodicity: float,
    maximum_beat_accent_imbalance: float,
    maximum_sample_rate: int,
    n_fft: int,
    band_count: int,
    chunk_seconds: float,
) -> RhythmEstimate:
    duration_seconds = samples.size / sample_rate
    signal_rms = _bounded_signal_rms(samples)
    if duration_seconds < minimum_duration_seconds or signal_rms <= minimum_signal_rms:
        return _unknown_rhythm()

    stride = max(1, math.ceil(sample_rate / maximum_sample_rate))
    rhythm_samples = np.ascontiguousarray(samples[::stride], dtype=np.float32)
    if rhythm_samples.size < n_fft:
        return _unknown_rhythm()
    rhythm_sample_rate = sample_rate / stride
    rhythm_hop_length = max(1, round(hop_length / stride))
    onset_envelope = _chunked_onset_strength(
        rhythm_samples,
        sample_rate=rhythm_sample_rate,
        hop_length=rhythm_hop_length,
        n_fft=n_fft,
        band_count=band_count,
        chunk_seconds=chunk_seconds,
    )
    if onset_envelope.size < 3 or float(np.max(onset_envelope)) <= 1e-12:
        return _unknown_rhythm()

    bpm, onset_periodicity, periodicity_quality = _estimate_periodic_tempo(
        onset_envelope,
        sample_rate=rhythm_sample_rate,
        hop_length=rhythm_hop_length,
    )
    frames = _chunked_beat_frames(
        onset_envelope,
        bpm=bpm,
        sample_rate=rhythm_sample_rate,
        hop_length=rhythm_hop_length,
        chunk_seconds=chunk_seconds,
    )
    if frames.size < 3:
        return _unknown_rhythm()
    times = _beat_times(
        frames,
        sample_rate=rhythm_sample_rate,
        hop_length=rhythm_hop_length,
        duration_seconds=duration_seconds,
    )
    if times.size < 3:
        return _unknown_rhythm()
    accent_imbalance = _beat_accent_imbalance(onset_envelope, frames)
    if accent_imbalance > maximum_beat_accent_imbalance and bpm / 2.0 >= _MINIMUM_BPM:
        half_bpm = bpm / 2.0
        half_frames = _chunked_beat_frames(
            onset_envelope,
            bpm=half_bpm,
            sample_rate=rhythm_sample_rate,
            hop_length=rhythm_hop_length,
            chunk_seconds=chunk_seconds,
        )
        half_times = _beat_times(
            half_frames,
            sample_rate=rhythm_sample_rate,
            hop_length=rhythm_hop_length,
            duration_seconds=duration_seconds,
        )
        half_imbalance = _beat_accent_imbalance(onset_envelope, half_frames)
        if half_times.size >= 3 and half_imbalance < accent_imbalance:
            bpm = half_bpm
            frames = half_frames
            times = half_times
            accent_imbalance = half_imbalance
    confidence = _rhythm_confidence(
        onset_envelope,
        frames,
        times,
        duration_seconds=duration_seconds,
        bpm=bpm,
        periodicity_quality=periodicity_quality,
    )
    if (
        onset_periodicity >= minimum_onset_periodicity
        and accent_imbalance <= maximum_beat_accent_imbalance
        and confidence >= minimum_confidence
    ):
        return RhythmEstimate(
            bpm=bpm,
            confidence=confidence,
            beat_positions_seconds=tuple(float(value) for value in times),
        )

    tentative_periodicity = minimum_onset_periodicity * _TENTATIVE_THRESHOLD_RATIO
    tentative_confidence = max(0.0, minimum_confidence - _TENTATIVE_CONFIDENCE_MARGIN)
    tentative_accent = maximum_beat_accent_imbalance * _TENTATIVE_ACCENT_RATIO
    if (
        duration_seconds < max(minimum_duration_seconds, _TENTATIVE_MINIMUM_DURATION_SECONDS)
        or onset_periodicity < tentative_periodicity
    ):
        return _unknown_rhythm()

    if bpm >= _TENTATIVE_HALF_TEMPO_BPM and bpm / 2.0 >= _MINIMUM_BPM:
        half_bpm = bpm / 2.0
        half_frames = _chunked_beat_frames(
            onset_envelope,
            bpm=half_bpm,
            sample_rate=rhythm_sample_rate,
            hop_length=rhythm_hop_length,
            chunk_seconds=chunk_seconds,
        )
        half_times = _beat_times(
            half_frames,
            sample_rate=rhythm_sample_rate,
            hop_length=rhythm_hop_length,
            duration_seconds=duration_seconds,
        )
        if half_times.size >= 3:
            half_imbalance = _beat_accent_imbalance(onset_envelope, half_frames)
            half_confidence = _rhythm_confidence(
                onset_envelope,
                half_frames,
                half_times,
                duration_seconds=duration_seconds,
                bpm=half_bpm,
                periodicity_quality=periodicity_quality,
            )
            if (
                half_imbalance <= tentative_accent
                and half_confidence >= tentative_confidence
                and half_confidence
                >= confidence - _TENTATIVE_HALF_CONFIDENCE_TOLERANCE
            ):
                bpm = half_bpm
                frames = half_frames
                times = half_times
                accent_imbalance = half_imbalance
                confidence = half_confidence

    if accent_imbalance > tentative_accent or confidence < tentative_confidence:
        return _unknown_rhythm()
    return RhythmEstimate(
        bpm=bpm,
        confidence=confidence,
        beat_positions_seconds=tuple(float(value) for value in times),
    )


def _beat_times(
    frames: NDArray[np.int64],
    *,
    sample_rate: float,
    hop_length: int,
    duration_seconds: float,
) -> NDArray[np.float64]:
    times = np.asarray(
        librosa.frames_to_time(frames, sr=sample_rate, hop_length=hop_length),
        dtype=np.float64,
    )
    return times[(times >= 0.0) & (times <= duration_seconds)]


def _bounded_signal_rms(samples: NDArray[np.float32]) -> float:
    square_sum = 0.0
    for start in range(0, samples.size, _RMS_BLOCK_SAMPLES):
        block = samples[start : start + _RMS_BLOCK_SAMPLES].astype(np.float64)
        square_sum += float(np.dot(block, block))
    return math.sqrt(square_sum / samples.size)


def _chunked_onset_strength(
    samples: NDArray[np.float32],
    *,
    sample_rate: float,
    hop_length: int,
    n_fft: int,
    band_count: int,
    chunk_seconds: float,
) -> NDArray[np.float64]:
    context_samples = math.ceil(n_fft / hop_length) * hop_length
    requested_chunk_samples = math.floor(chunk_seconds * sample_rate / hop_length) * hop_length
    chunk_samples = max(hop_length, requested_chunk_samples)
    pieces: list[NDArray[np.float64]] = []
    for core_start in range(0, samples.size, chunk_samples):
        core_end = min(samples.size, core_start + chunk_samples)
        context_start = max(0, core_start - context_samples)
        context_end = min(samples.size, core_end + context_samples)
        chunk = samples[context_start:context_end]
        onset = np.asarray(
            librosa.onset.onset_strength(
                y=chunk,
                sr=sample_rate,
                hop_length=hop_length,
                center=False,
                n_fft=n_fft,
                n_mels=band_count,
            ),
            dtype=np.float64,
        )
        first_frame = math.ceil((core_start - context_start) / hop_length)
        final_frame = math.ceil((core_end - context_start) / hop_length)
        pieces.append(onset[first_frame : min(final_frame, onset.size)])
    return np.concatenate(pieces) if pieces else np.empty(0, dtype=np.float64)


def _estimate_periodic_tempo(
    onset_envelope: NDArray[np.float64],
    *,
    sample_rate: float,
    hop_length: int,
) -> tuple[float, float, float]:
    centered = onset_envelope - np.mean(onset_envelope)
    denominator = float(np.dot(centered, centered))
    if denominator <= 1e-12:
        return 0.0, 0.0, 0.0
    minimum_lag = max(1, math.ceil(60.0 * sample_rate / (_MAXIMUM_BPM * hop_length)))
    maximum_lag = min(
        centered.size - 1,
        math.floor(60.0 * sample_rate / (_MINIMUM_BPM * hop_length)),
    )
    periodicities = {
        lag: max(0.0, float(np.dot(centered[:-lag], centered[lag:]) / denominator))
        for lag in range(minimum_lag, maximum_lag + 1)
    }
    strongest_periodicity = max(periodicities.values(), default=0.0)
    local_peaks = [
        lag
        for lag, periodicity in periodicities.items()
        if periodicity >= periodicities.get(lag - 1, -1.0)
        and periodicity >= periodicities.get(lag + 1, -1.0)
    ]
    plausible_lags = [
        lag for lag in local_peaks if periodicities[lag] >= strongest_periodicity * 0.75
    ]
    strongest_lag = max(periodicities, key=lambda lag: periodicities[lag], default=minimum_lag)
    selected_lag = min(plausible_lags, default=strongest_lag)
    selected_periodicity = periodicities.get(selected_lag, 0.0)
    octave_centers = (selected_lag * 2, round(selected_lag / 2))
    octave_lags: set[int] = set()
    for center in octave_centers:
        octave_lags.update(
            candidate
            for candidate in (center - 1, center, center + 1)
            if candidate in periodicities and candidate != selected_lag
        )
    octave_periodicity = max(
        (periodicities[candidate] for candidate in octave_lags),
        default=0.0,
    )
    periodicity_quality = max(0.0, selected_periodicity - 0.25 * octave_periodicity)
    bpm = 60.0 * sample_rate / (selected_lag * hop_length)
    return float(bpm), float(selected_periodicity), float(periodicity_quality)


def _chunked_beat_frames(
    onset_envelope: NDArray[np.float64],
    *,
    bpm: float,
    sample_rate: float,
    hop_length: int,
    chunk_seconds: float,
) -> NDArray[np.int64]:
    requested_chunk_frames = math.floor(chunk_seconds * sample_rate / hop_length)
    chunk_frames = max(1, requested_chunk_frames)
    context_frames = max(1, math.ceil(_BEAT_CONTEXT_SECONDS * sample_rate / hop_length))
    pieces: list[NDArray[np.int64]] = []
    for core_start in range(0, onset_envelope.size, chunk_frames):
        core_end = min(onset_envelope.size, core_start + chunk_frames)
        context_start = max(0, core_start - context_frames)
        context_end = min(onset_envelope.size, core_end + context_frames)
        _, local_frames = librosa.beat.beat_track(
            onset_envelope=onset_envelope[context_start:context_end],
            sr=sample_rate,
            hop_length=hop_length,
            bpm=bpm,
            tightness=100.0,
            trim=False,
            units="frames",
        )
        global_frames = np.asarray(local_frames, dtype=np.int64) + context_start
        pieces.append(global_frames[(global_frames >= core_start) & (global_frames < core_end)])
    return np.concatenate(pieces) if pieces else np.empty(0, dtype=np.int64)


def _rhythm_confidence(
    onset_envelope: NDArray[np.floating],
    beat_frames: NDArray[np.int64],
    beat_times: NDArray[np.float64],
    *,
    duration_seconds: float,
    bpm: float,
    periodicity_quality: float,
) -> float:
    intervals = np.diff(beat_times)
    mean_interval = float(np.mean(intervals))
    coefficient_of_variation = float(np.std(intervals) / mean_interval)
    regularity = max(0.0, 1.0 - min(1.0, coefficient_of_variation * 4.0))
    valid_frames = beat_frames[(beat_frames >= 0) & (beat_frames < onset_envelope.size)]
    peak_reference = max(float(np.percentile(onset_envelope, 95.0)), 1e-12)
    salience = min(1.0, float(np.median(onset_envelope[valid_frames])) / peak_reference)
    expected_beats = max(1.0, duration_seconds * bpm / 60.0)
    coverage = min(1.0, beat_times.size / (expected_beats * 0.75))
    return float(
        min(
            1.0,
            0.4 * periodicity_quality + 0.3 * regularity + 0.2 * salience + 0.1 * coverage,
        )
    )


def _beat_accent_imbalance(
    onset_envelope: NDArray[np.floating], beat_frames: NDArray[np.int64]
) -> float:
    valid_frames = beat_frames[(beat_frames >= 0) & (beat_frames < onset_envelope.size)]
    strengths = np.asarray(onset_envelope[valid_frames], dtype=np.float64)
    strengths = strengths[strengths > 1e-12]
    if strengths.size < 6:
        return 0.0
    even_accent = float(np.median(strengths[::2]))
    odd_accent = float(np.median(strengths[1::2]))
    reference = max(even_accent, odd_accent, 1e-12)
    return abs(even_accent - odd_accent) / reference


def _unknown_rhythm() -> RhythmEstimate:
    return RhythmEstimate(bpm=None, confidence=None, beat_positions_seconds=())


def rhythm_to_dict(estimate: RhythmEstimate) -> dict[str, object]:
    return {
        "bpm": estimate.bpm,
        "confidence": estimate.confidence,
        "beat_positions_seconds": list(estimate.beat_positions_seconds),
        "algorithm": estimate.algorithm,
    }
