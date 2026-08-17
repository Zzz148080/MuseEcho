from __future__ import annotations

import hashlib
import wave
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class AudioFingerprint:
    duration_seconds: float
    shingles: tuple[str, ...]


@dataclass(frozen=True)
class NearDuplicateCandidate:
    left_track_id: str
    right_track_id: str
    score: float


def fingerprint_wav(
    path: Path,
    *,
    target_sample_rate: int = 400,
    window_seconds: float = 1.0,
    hop_seconds: float = 0.5,
) -> AudioFingerprint:
    """Create a lightweight PCM fingerprint suitable for duplicate-audit triage."""

    if target_sample_rate <= 0 or window_seconds <= 0 or hop_seconds <= 0:
        raise ValueError("fingerprint timing parameters must be positive")
    try:
        with wave.open(str(path), "rb") as audio:
            if audio.getsampwidth() != 2:
                raise ValueError("fingerprint WAV input must use 16-bit PCM")
            channels = audio.getnchannels()
            sample_rate = audio.getframerate()
            frame_count = audio.getnframes()
            if channels <= 0 or sample_rate <= 0 or frame_count <= 0:
                raise ValueError("fingerprint WAV metadata is invalid")
            resampled = _read_resampled_mono(
                audio, channels=channels, sample_rate=sample_rate, target_rate=target_sample_rate
            )
    except (EOFError, wave.Error):
        raise ValueError("fingerprint input must be a readable PCM WAV file") from None
    window_size = max(1, round(window_seconds * target_sample_rate))
    hop_size = max(1, round(hop_seconds * target_sample_rate))
    shingles: list[str] = []
    for start in range(0, len(resampled) - window_size + 1, hop_size):
        window = resampled[start : start + window_size]
        peak = max(abs(sample) for sample in window)
        if peak < 1:
            continue
        quantized = bytes(
            max(0, min(255, round(sample / peak * 63) + 128)) for sample in window
        )
        shingles.append(hashlib.sha256(quantized).hexdigest()[:24])
    return AudioFingerprint(frame_count / sample_rate, tuple(shingles))


def _read_resampled_mono(
    audio: wave.Wave_read, *, channels: int, sample_rate: int, target_rate: int
) -> list[float]:
    resampled: list[float] = []
    frame_offset = 0
    next_output = 0
    while payload := audio.readframes(65_536):
        interleaved = np.frombuffer(payload, dtype="<i2")
        usable_samples = len(interleaved) - len(interleaved) % channels
        if usable_samples == 0:
            continue
        mono = interleaved[:usable_samples].reshape(-1, channels).mean(axis=1)
        chunk_end = frame_offset + len(mono)
        source_indices: list[int] = []
        while (source_index := next_output * sample_rate // target_rate) < chunk_end:
            if source_index >= frame_offset:
                source_indices.append(source_index - frame_offset)
            next_output += 1
        if source_indices:
            resampled.extend(mono[np.asarray(source_indices)].tolist())
        frame_offset = chunk_end
    return resampled


def near_duplicate_score(left: AudioFingerprint, right: AudioFingerprint) -> float:
    """Return multiset shingle containment in the shorter fingerprint."""

    if not left.shingles or not right.shingles:
        return 0.0
    left_counts = Counter(left.shingles)
    right_counts = Counter(right.shingles)
    overlap = sum((left_counts & right_counts).values())
    return overlap / min(len(left.shingles), len(right.shingles))


def find_near_duplicates(
    fingerprints: Mapping[str, AudioFingerprint], *, threshold: float
) -> tuple[NearDuplicateCandidate, ...]:
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not 0 < threshold <= 1
    ):
        raise ValueError("near-duplicate threshold must be within (0, 1]")
    candidates: list[NearDuplicateCandidate] = []
    for left_track_id, right_track_id in combinations(sorted(fingerprints), 2):
        score = near_duplicate_score(
            fingerprints[left_track_id], fingerprints[right_track_id]
        )
        if score >= threshold:
            candidates.append(
                NearDuplicateCandidate(left_track_id, right_track_id, round(score, 6))
            )
    return tuple(candidates)
