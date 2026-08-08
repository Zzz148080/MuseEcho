from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import librosa
import numpy as np

ANALYSIS_SAMPLE_RATE = 22_050
N_FFT = 4_096
HOP_LENGTH = 1_024
MINIMUM_SAMPLE_RATE = 8_000
MAXIMUM_SAMPLE_RATE = 192_000
MAXIMUM_DURATION_SECONDS = 600.0
MINIMUM_SIGNAL_RMS = 1e-4
_CHUNK_SECONDS = 30.0


@dataclass(frozen=True)
class HarmonicFeatures:
    chroma: np.ndarray
    rms: np.ndarray
    sample_rate: int
    duration_seconds: float

    @property
    def frame_centers_seconds(self) -> np.ndarray:
        frame_indices = np.arange(self.chroma.shape[1], dtype=np.float64)
        return (frame_indices * HOP_LENGTH + N_FFT / 2) / self.sample_rate


def validate_harmonic_input(
    samples: Sequence[float] | memoryview,
    sample_rate: int,
) -> tuple[np.ndarray, int, float]:
    if (
        type(sample_rate) is not int
        or not MINIMUM_SAMPLE_RATE <= sample_rate <= MAXIMUM_SAMPLE_RATE
    ):
        raise ValueError("sample_rate must be an integer between 8000 and 192000")
    try:
        array = np.asarray(samples, dtype=np.float32)
    except (TypeError, ValueError):
        raise ValueError("samples must be a finite, non-empty one-dimensional sequence") from None
    if array.ndim != 1 or array.size == 0:
        raise ValueError("samples must be a finite, non-empty one-dimensional sequence")
    duration_seconds = array.size / sample_rate
    if duration_seconds > MAXIMUM_DURATION_SECONDS:
        raise ValueError("samples duration cannot exceed 600 seconds")
    if not bool(np.all(np.isfinite(array))):
        raise ValueError("samples must contain only finite values")
    if sample_rate != ANALYSIS_SAMPLE_RATE:
        array = np.ascontiguousarray(
            librosa.resample(
                array,
                orig_sr=sample_rate,
                target_sr=ANALYSIS_SAMPLE_RATE,
                res_type="soxr_hq",
                scale=False,
            ),
            dtype=np.float32,
        )
        sample_rate = ANALYSIS_SAMPLE_RATE
    return array, sample_rate, duration_seconds


def extract_harmonic_features(
    samples: np.ndarray,
    sample_rate: int,
    duration_seconds: float,
) -> HarmonicFeatures:
    if samples.size < N_FFT:
        return HarmonicFeatures(
            np.empty((12, 0), dtype=np.float64),
            np.empty(0, dtype=np.float64),
            sample_rate,
            duration_seconds,
        )
    context_samples = math.ceil(N_FFT / HOP_LENGTH) * HOP_LENGTH
    requested_chunk = math.floor(_CHUNK_SECONDS * sample_rate / HOP_LENGTH) * HOP_LENGTH
    chunk_samples = max(HOP_LENGTH, requested_chunk)
    chroma_pieces: list[np.ndarray] = []
    rms_pieces: list[np.ndarray] = []
    for core_start in range(0, samples.size, chunk_samples):
        core_end = min(samples.size, core_start + chunk_samples)
        context_start = max(0, core_start - context_samples)
        context_end = min(samples.size, core_end + context_samples)
        chunk = samples[context_start:context_end]
        available_frames = max(0, 1 + (chunk.size - N_FFT) // HOP_LENGTH)
        first_frame = math.ceil((core_start - context_start) / HOP_LENGTH)
        final_frame = min(
            math.ceil((core_end - context_start) / HOP_LENGTH),
            available_frames,
        )
        piece_frames = max(0, final_frame - first_frame)
        if piece_frames == 0:
            continue
        chunk_rms = librosa.feature.rms(
            y=chunk,
            frame_length=N_FFT,
            hop_length=HOP_LENGTH,
            center=False,
        )[0]
        if float(np.max(chunk_rms, initial=0.0)) <= MINIMUM_SIGNAL_RMS:
            chroma_pieces.append(np.zeros((12, piece_frames), dtype=np.float64))
            rms_pieces.append(np.asarray(chunk_rms[first_frame:final_frame], dtype=np.float64))
            continue
        chunk_chroma = librosa.feature.chroma_stft(
            y=chunk,
            sr=sample_rate,
            n_fft=N_FFT,
            hop_length=HOP_LENGTH,
            tuning=None,
            norm=2,
            center=False,
        )
        chroma_pieces.append(np.asarray(chunk_chroma[:, first_frame:final_frame], dtype=np.float64))
        rms_pieces.append(np.asarray(chunk_rms[first_frame:final_frame], dtype=np.float64))
    if not chroma_pieces:
        chroma = np.empty((12, 0), dtype=np.float64)
        rms = np.empty(0, dtype=np.float64)
    else:
        chroma = np.concatenate(chroma_pieces, axis=1)
        rms = np.concatenate(rms_pieces)
    return HarmonicFeatures(chroma, rms, sample_rate, duration_seconds)
