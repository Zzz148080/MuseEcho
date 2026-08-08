from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class RhythmEstimate:
    bpm: float | None
    confidence: float | None
    beat_positions_seconds: tuple[float, ...]
    algorithm: str = "librosa-onset-beat-v1"


def estimate_rhythm(
    samples: NDArray[np.float32],
    sample_rate: int,
    *,
    hop_length: int,
    minimum_duration_seconds: float,
    minimum_signal_rms: float,
    minimum_confidence: float,
) -> RhythmEstimate:
    duration_seconds = samples.size / sample_rate
    signal_rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    if duration_seconds < minimum_duration_seconds or signal_rms <= minimum_signal_rms:
        return _unknown_rhythm()
    onset_envelope = librosa.onset.onset_strength(
        y=samples,
        sr=float(sample_rate),
        hop_length=hop_length,
        center=False,
    )
    if onset_envelope.size < 3 or float(np.max(onset_envelope)) <= 1e-12:
        return _unknown_rhythm()
    tempo, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_envelope,
        sr=float(sample_rate),
        hop_length=hop_length,
        start_bpm=120.0,
        tightness=100.0,
        trim=False,
        units="frames",
    )
    bpm = float(np.asarray(tempo).reshape(-1)[0])
    frames = np.asarray(beat_frames, dtype=np.int64)
    if not np.isfinite(bpm) or bpm <= 0.0 or frames.size < 3:
        return _unknown_rhythm()
    times = np.asarray(
        librosa.frames_to_time(frames, sr=float(sample_rate), hop_length=hop_length),
        dtype=np.float64,
    )
    times = times[(times >= 0.0) & (times <= duration_seconds)]
    if times.size < 3:
        return _unknown_rhythm()
    confidence = _rhythm_confidence(
        onset_envelope,
        frames,
        times,
        duration_seconds=duration_seconds,
        bpm=bpm,
    )
    if confidence < minimum_confidence:
        return _unknown_rhythm()
    return RhythmEstimate(
        bpm=bpm,
        confidence=confidence,
        beat_positions_seconds=tuple(float(value) for value in times),
    )


def _rhythm_confidence(
    onset_envelope: NDArray[np.floating],
    beat_frames: NDArray[np.int64],
    beat_times: NDArray[np.float64],
    *,
    duration_seconds: float,
    bpm: float,
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
    return float(min(1.0, 0.5 * regularity + 0.3 * salience + 0.2 * coverage))


def _unknown_rhythm() -> RhythmEstimate:
    return RhythmEstimate(bpm=None, confidence=None, beat_positions_seconds=())


def rhythm_to_dict(estimate: RhythmEstimate) -> dict[str, object]:
    return {
        "bpm": estimate.bpm,
        "confidence": estimate.confidence,
        "beat_positions_seconds": list(estimate.beat_positions_seconds),
        "algorithm": estimate.algorithm,
    }
