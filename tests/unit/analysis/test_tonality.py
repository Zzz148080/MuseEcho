from __future__ import annotations

import json
import math
import warnings

import numpy as np
import pytest

from museecho.analysis import tonality
from museecho.analysis.tonality import estimate_tonality

SAMPLE_RATE = 22_050


def _mixed_tones(
    frequencies: tuple[float, ...],
    duration_seconds: float,
    *,
    amplitude: float = 0.7,
    sample_rate: int = SAMPLE_RATE,
) -> list[float]:
    frame_count = round(duration_seconds * sample_rate)
    scale = amplitude / len(frequencies)
    return [
        scale
        * sum(
            math.sin(2.0 * math.pi * frequency * index / sample_rate) for frequency in frequencies
        )
        for index in range(frame_count)
    ]


def _c_major_progression() -> list[float]:
    chords = (
        (261.6256, 329.6276, 391.9954),
        (220.0000, 261.6256, 329.6276),
        (174.6141, 220.0000, 261.6256),
        (195.9977, 246.9417, 293.6648),
    )
    return [sample for chord in chords for sample in _mixed_tones(chord, 1.0)]


def _a_minor_progression() -> list[float]:
    chords = (
        (220.0000, 261.6256, 329.6276),
        (293.6648, 349.2282, 440.0000),
        (329.6276, 415.3047, 493.8833),
        (220.0000, 261.6256, 329.6276),
    )
    return [sample for chord in chords for sample in _mixed_tones(chord, 1.0)]


def _d_flat_major_progression() -> list[float]:
    chords = (
        (277.1826, 349.2282, 415.3047),
        (233.0819, 277.1826, 349.2282),
        (184.9972, 233.0819, 277.1826),
        (207.6523, 261.6256, 311.1270),
    )
    return [sample for chord in chords for sample in _mixed_tones(chord, 1.0)]


def test_c_major_progression_is_classified():
    estimate = estimate_tonality(_c_major_progression(), SAMPLE_RATE)

    assert (estimate.tonic, estimate.mode) == ("C", "major")
    assert estimate.confidence is not None
    assert estimate.confidence >= 0.7


def test_a_minor_progression_reports_time_stability():
    estimate = estimate_tonality(_a_minor_progression(), SAMPLE_RATE)

    assert (estimate.tonic, estimate.mode) == ("A", "minor")
    assert estimate.confidence is not None
    assert estimate.confidence >= 0.7
    assert estimate.stability >= 0.7


def test_silence_returns_unknown_without_analysis_warnings():
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        estimate = estimate_tonality([0.0] * (SAMPLE_RATE * 2), SAMPLE_RATE)

    assert estimate.tonic is None
    assert estimate.mode is None
    assert estimate.confidence is None
    assert estimate.stability == 0.0
    assert captured == []


def test_signal_shorter_than_fft_window_returns_unknown_without_warnings():
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        estimate = estimate_tonality(_mixed_tones((440.0,), 0.05), SAMPLE_RATE)

    assert estimate.tonic is None
    assert estimate.mode is None
    assert estimate.confidence is None
    assert estimate.stability == 0.0
    assert captured == []


def test_ambiguous_chromatic_collection_is_unknown_and_diagnostics_stay_private():
    frequencies = tuple(261.6256 * 2 ** (semitone / 12.0) for semitone in range(12))

    estimate = estimate_tonality(_mixed_tones(frequencies, 2.0), SAMPLE_RATE)
    payload = estimate.to_dict()

    assert estimate.tonic is None
    assert estimate.mode is None
    assert estimate.confidence is None
    assert estimate.top_candidates
    assert set(payload) == {"tonic", "mode", "confidence", "stability", "algorithm"}
    assert "top_candidates" not in payload
    json.dumps(payload, allow_nan=False)


def test_enharmonic_tonics_use_canonical_sharp_spelling():
    estimate = estimate_tonality(_d_flat_major_progression(), SAMPLE_RATE)

    assert (estimate.tonic, estimate.mode) == ("C#", "major")
    assert estimate.confidence is not None
    assert estimate.confidence >= 0.7


def test_frequent_distant_key_changes_return_unknown():
    c_major = (261.6256, 329.6276, 391.9954)
    f_sharp_major = (184.9972, 233.0819, 277.1826)
    samples = [
        sample
        for chord in (c_major, f_sharp_major, c_major, f_sharp_major)
        for sample in _mixed_tones(chord, 1.0)
    ]

    estimate = estimate_tonality(samples, SAMPLE_RATE)

    assert estimate.tonic is None
    assert estimate.mode is None
    assert estimate.confidence is None
    assert estimate.stability < 0.7


def test_sustained_distant_key_change_overrides_strong_global_average():
    c_major_progression = (
        (261.6256, 329.6276, 391.9954),
        (220.0000, 261.6256, 329.6276),
        (174.6141, 220.0000, 261.6256),
        (195.9977, 246.9417, 293.6648),
    )
    tritone_ratio = 2 ** (6 / 12)
    f_sharp_major_progression = tuple(
        tuple(frequency * tritone_ratio for frequency in chord) for chord in c_major_progression
    )
    samples = [
        sample
        for chord in c_major_progression * 2 + f_sharp_major_progression
        for sample in _mixed_tones(chord, 1.0)
    ]

    estimate = estimate_tonality(samples, SAMPLE_RATE)

    assert estimate.tonic is None
    assert estimate.mode is None
    assert estimate.confidence is None
    assert estimate.stability < 0.7


def test_long_audio_chroma_extraction_is_chunked(monkeypatch):
    observed_sample_counts: list[int] = []
    real_chroma_stft = tonality.librosa.feature.chroma_stft

    def recording_chroma_stft(**kwargs):
        observed_sample_counts.append(len(kwargs["y"]))
        return real_chroma_stft(**kwargs)

    monkeypatch.setattr(tonality.librosa.feature, "chroma_stft", recording_chroma_stft)

    estimate = estimate_tonality(_c_major_progression() * 18, SAMPLE_RATE)

    assert (estimate.tonic, estimate.mode) == ("C", "major")
    assert len(observed_sample_counts) >= 3
    assert max(observed_sample_counts) <= round(31.0 * SAMPLE_RATE)


def test_silent_analysis_chunks_do_not_invoke_empty_tuning_estimation():
    samples = _c_major_progression() + [0.0] * (SAMPLE_RATE * 36)

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        estimate = estimate_tonality(samples, SAMPLE_RATE)

    assert estimate.tonic is None
    assert estimate.mode is None
    assert captured == []


def test_detuned_progression_keeps_the_same_tonic():
    detune_ratio = 2 ** (30 / 1_200)
    chords = (
        (261.6256, 329.6276, 391.9954),
        (220.0000, 261.6256, 329.6276),
        (174.6141, 220.0000, 261.6256),
        (195.9977, 246.9417, 293.6648),
    )
    samples = [
        sample
        for chord in chords
        for sample in _mixed_tones(tuple(frequency * detune_ratio for frequency in chord), 1.0)
    ]

    estimate = estimate_tonality(samples, SAMPLE_RATE)

    assert (estimate.tonic, estimate.mode) == ("C", "major")


@pytest.mark.parametrize(
    "frequencies",
    [
        (261.6256, 329.6276, 391.9954),
        (220.0000, 261.6256, 329.6276),
    ],
)
def test_single_triad_is_not_enough_evidence_for_a_key(frequencies):
    estimate = estimate_tonality(_mixed_tones(frequencies, 4.0), SAMPLE_RATE)

    assert estimate.tonic is None
    assert estimate.mode is None
    assert estimate.confidence is None


def test_barely_audible_progression_does_not_keep_full_confidence():
    chords = (
        (220.0000, 261.6256, 329.6276),
        (293.6648, 349.2282, 440.0000),
        (329.6276, 415.3047, 493.8833),
        (220.0000, 261.6256, 329.6276),
    )
    samples = [sample for chord in chords for sample in _mixed_tones(chord, 1.0, amplitude=0.0003)]

    estimate = estimate_tonality(samples, SAMPLE_RATE)

    assert estimate.tonic is None
    assert estimate.mode is None
    assert estimate.confidence is None


def test_half_second_of_active_harmony_is_not_enough_for_a_track_key():
    chords = (
        (261.6256, 329.6276, 391.9954),
        (220.0000, 261.6256, 329.6276),
        (174.6141, 220.0000, 261.6256),
        (195.9977, 246.9417, 293.6648),
    )
    samples = [sample for chord in chords for sample in _mixed_tones(chord, 0.125)] + [0.0] * round(
        1.5 * SAMPLE_RATE
    )

    estimate = estimate_tonality(samples, SAMPLE_RATE)

    assert estimate.tonic is None
    assert estimate.mode is None
    assert estimate.confidence is None


@pytest.mark.parametrize("order", [(0, 1, 0, 1), (0, 0, 1, 1)])
def test_incompatible_minor_key_sections_return_unknown(order):
    a_minor = (
        (220.0000, 261.6256, 329.6276),
        (293.6648, 349.2282, 440.0000),
        (329.6276, 415.3047, 493.8833),
        (220.0000, 261.6256, 329.6276),
    )
    major_third_ratio = 2 ** (4 / 12)
    c_sharp_minor = tuple(
        tuple(frequency * major_third_ratio for frequency in chord) for chord in a_minor
    )
    progressions = (a_minor, c_sharp_minor)
    samples = [
        sample
        for progression_index in order
        for chord in progressions[progression_index]
        for sample in _mixed_tones(chord, 1.0)
    ]

    estimate = estimate_tonality(samples, SAMPLE_RATE)

    assert estimate.tonic is None
    assert estimate.mode is None
    assert estimate.confidence is None
    assert estimate.stability < 0.7


@pytest.mark.parametrize("sample_rate", [0, -1, True, 22_050.0])
def test_sample_rate_must_be_a_strict_positive_integer(sample_rate):
    with pytest.raises(ValueError, match="sample_rate must be a positive integer"):
        estimate_tonality([0.0] * 4_096, sample_rate)


@pytest.mark.parametrize("sample_rate", [4_000, 192_001])
def test_sample_rate_must_be_in_the_decoder_supported_range(sample_rate):
    with pytest.raises(ValueError, match="sample_rate must be between 8000 and 192000"):
        estimate_tonality([0.0] * max(4_096, sample_rate), sample_rate)


def test_audio_longer_than_v1_limit_is_rejected_before_analysis():
    samples = np.zeros(600 * 8_000 + 1, dtype=np.float32)

    with pytest.raises(ValueError, match="duration cannot exceed 600 seconds"):
        estimate_tonality(samples, 8_000)


@pytest.mark.parametrize("sample_rate", [8_000, 44_100, 96_000, 192_000])
def test_supported_sample_rates_are_normalized_before_key_estimation(sample_rate):
    chords = (
        (261.6256, 329.6276, 391.9954),
        (220.0000, 261.6256, 329.6276),
        (174.6141, 220.0000, 261.6256),
        (195.9977, 246.9417, 293.6648),
    )
    samples = [
        sample for chord in chords for sample in _mixed_tones(chord, 1.0, sample_rate=sample_rate)
    ]

    estimate = estimate_tonality(samples, sample_rate)

    assert (estimate.tonic, estimate.mode) == ("C", "major")


@pytest.mark.parametrize(
    ("samples", "message"),
    [
        ([], "samples cannot be empty"),
        ([[0.0], [0.0]], "one-dimensional"),
        ([math.nan] * 4_096, "samples must be finite"),
        ([math.inf] * 4_096, "samples must be finite"),
    ],
)
def test_invalid_pcm_is_rejected(samples, message):
    with pytest.raises(ValueError, match=message):
        estimate_tonality(np.asarray(samples), SAMPLE_RATE)
