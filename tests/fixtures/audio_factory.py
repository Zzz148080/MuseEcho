from __future__ import annotations

import math
import struct
import subprocess
import wave
from collections.abc import Iterable, Sequence
from pathlib import Path


def write_samples_wav(
    path: Path,
    samples: Iterable[float],
    *,
    sample_rate: int = 22_050,
) -> Path:
    frames = bytearray()
    for sample in samples:
        clamped = max(-1.0, min(1.0, sample))
        frames.extend(struct.pack("<h", round(clamped * 32767)))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(frames)
    return path


def sine_samples(
    duration_seconds: float,
    frequency_hz: float,
    sample_rate: int,
    amplitude: float = 0.5,
) -> list[float]:
    frame_count = round(duration_seconds * sample_rate)
    return [
        amplitude * math.sin(2.0 * math.pi * frequency_hz * index / sample_rate)
        for index in range(frame_count)
    ]


def write_sine_wav(
    path: Path,
    *,
    duration_seconds: float = 2.0,
    frequency_hz: float = 440.0,
    sample_rate: int = 44_100,
    amplitude: float = 0.5,
) -> Path:
    return write_samples_wav(
        path,
        sine_samples(duration_seconds, frequency_hz, sample_rate, amplitude),
        sample_rate=sample_rate,
    )


def write_metronome_wav(
    path: Path,
    *,
    bpm: float = 120.0,
    duration_seconds: float = 4.0,
    sample_rate: int = 22_050,
) -> Path:
    beat_interval = 60.0 / bpm
    click_length = round(0.02 * sample_rate)
    beat_length = round(beat_interval * sample_rate)
    samples: list[float] = []
    for index in range(round(duration_seconds * sample_rate)):
        within_beat = index % beat_length
        envelope = max(0.0, 1.0 - within_beat / click_length)
        click = math.sin(2.0 * math.pi * 1_500.0 * index / sample_rate)
        samples.append(0.8 * envelope * click if within_beat < click_length else 0.0)
    return write_samples_wav(path, samples, sample_rate=sample_rate)


def write_chord_wav(
    path: Path,
    *,
    quality: str = "major",
    duration_seconds: float = 2.0,
    sample_rate: int = 22_050,
) -> Path:
    if quality not in {"major", "minor"}:
        raise ValueError("quality must be major or minor")
    frequencies = (261.6256, 329.6276, 391.9954)
    if quality == "minor":
        frequencies = (261.6256, 311.1270, 391.9954)
    return write_samples_wav(
        path,
        _mixed_tones(frequencies, duration_seconds, sample_rate),
        sample_rate=sample_rate,
    )


def write_chord_progression_wav(
    path: Path,
    *,
    sample_rate: int = 22_050,
) -> Path:
    progression = (
        (261.6256, 329.6276, 391.9954),
        (220.0000, 261.6256, 329.6276),
        (174.6141, 220.0000, 261.6256),
        (195.9977, 246.9417, 293.6648),
    )
    samples: list[float] = []
    for frequencies in progression:
        samples.extend(_mixed_tones(frequencies, 1.0, sample_rate))
    return write_samples_wav(path, samples, sample_rate=sample_rate)


def write_segmented_energy_wav(
    path: Path,
    *,
    sample_rate: int = 22_050,
) -> Path:
    samples: list[float] = []
    for amplitude in (0.1, 0.7, 0.25):
        samples.extend(sine_samples(1.0, 440.0, sample_rate, amplitude))
    return write_samples_wav(path, samples, sample_rate=sample_rate)


def write_silence_wav(
    path: Path, *, duration_seconds: float = 1.0, sample_rate: int = 22_050
) -> Path:
    return write_samples_wav(
        path,
        [0.0] * round(duration_seconds * sample_rate),
        sample_rate=sample_rate,
    )


def write_short_wav(path: Path, *, sample_rate: int = 22_050) -> Path:
    return write_sine_wav(path, duration_seconds=0.02, sample_rate=sample_rate)


def write_corrupt_audio(path: Path) -> Path:
    path.write_bytes(b"not an audio file\x00\xff")
    return path


def encode_mp3(wav_path: Path, mp3_path: Path, *, ffmpeg_executable: str) -> Path:
    completed = subprocess.run(
        [
            ffmpeg_executable,
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(wav_path),
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "4",
            "-map_metadata",
            "-1",
            "-y",
            str(mp3_path),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError("test MP3 encoding failed")
    return mp3_path


def _mixed_tones(
    frequencies: Sequence[float], duration_seconds: float, sample_rate: int
) -> list[float]:
    frame_count = round(duration_seconds * sample_rate)
    scale = 0.7 / len(frequencies)
    return [
        scale
        * sum(
            math.sin(2.0 * math.pi * frequency * index / sample_rate) for frequency in frequencies
        )
        for index in range(frame_count)
    ]
