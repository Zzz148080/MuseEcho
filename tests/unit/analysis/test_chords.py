from __future__ import annotations

import json
import math

import numpy as np
import pytest

from museecho.analysis.chords import estimate_chords

SAMPLE_RATE = 22_050


def _tones(
    frequencies: tuple[float, ...],
    duration_seconds: float,
    *,
    sample_rate: int = SAMPLE_RATE,
    amplitude: float = 0.7,
) -> list[float]:
    count = round(duration_seconds * sample_rate)
    scale = amplitude / len(frequencies)
    return [
        scale
        * sum(
            math.sin(2.0 * math.pi * frequency * index / sample_rate) for frequency in frequencies
        )
        for index in range(count)
    ]


def _progression(*, sample_rate: int = SAMPLE_RATE) -> list[float]:
    chords = (
        (261.6256, 329.6276, 391.9954),
        (195.9977, 246.9417, 293.6648),
        (220.0000, 261.6256, 329.6276),
        (174.6141, 220.0000, 261.6256),
    )
    return [sample for chord in chords for sample in _tones(chord, 1.0, sample_rate=sample_rate)]


def _weighted_tones(tones: tuple[tuple[float, float], ...], duration_seconds: float) -> list[float]:
    count = round(duration_seconds * SAMPLE_RATE)
    scale = 0.7 / sum(amplitude for _frequency, amplitude in tones)
    return [
        scale
        * sum(
            amplitude * math.sin(2.0 * math.pi * frequency * index / SAMPLE_RATE)
            for frequency, amplitude in tones
        )
        for index in range(count)
    ]


def test_c_g_am_f_progression_has_timed_chords():
    events = estimate_chords(_progression(), SAMPLE_RATE)

    assert [event.symbol for event in events] == ["C", "G", "Am", "F"]
    assert events[0].start_seconds == 0.0
    assert events[-1].end_seconds == pytest.approx(4.0)
    assert all(event.end_seconds > event.start_seconds for event in events)
    assert all(event.confidence is not None and event.confidence >= 0.7 for event in events)


def test_events_cover_the_audio_without_gaps_or_overrun():
    events = estimate_chords(_progression(), SAMPLE_RATE)

    assert all(left.end_seconds == right.start_seconds for left, right in zip(events, events[1:]))
    assert all(0.0 <= event.start_seconds < event.end_seconds <= 4.0 for event in events)


def test_silence_is_one_unknown_event():
    events = estimate_chords([0.0] * (SAMPLE_RATE * 2), SAMPLE_RATE)

    assert len(events) == 1
    assert events[0].symbol is None
    assert events[0].confidence is None
    assert (events[0].start_seconds, events[0].end_seconds) == (0.0, 2.0)


def test_chromatic_ambiguity_is_merged_as_unknown():
    frequencies = tuple(261.6256 * 2 ** (semitone / 12.0) for semitone in range(12))
    events = estimate_chords(_tones(frequencies, 2.0), SAMPLE_RATE)

    assert len(events) == 1
    assert events[0].symbol is None
    assert events[0].confidence is None


def test_noise_is_not_reported_as_chords():
    noise = np.random.default_rng(10).normal(0.0, 0.2, SAMPLE_RATE * 3)
    events = estimate_chords(noise, SAMPLE_RATE)

    assert all(event.symbol is None for event in events)


def test_too_short_chord_evidence_is_unknown():
    events = estimate_chords(_tones((261.6256, 329.6276, 391.9954), 0.2), SAMPLE_RATE)

    assert len(events) == 1
    assert events[0].symbol is None


def test_brief_chord_change_does_not_create_a_subminimum_known_event():
    c_major = (261.6256, 329.6276, 391.9954)
    g_major = (195.9977, 246.9417, 293.6648)
    samples = _tones(c_major, 1.0) + _tones(g_major, 0.2) + _tones(c_major, 1.0)

    events = estimate_chords(samples, SAMPLE_RATE)

    assert all(
        event.symbol is None or event.end_seconds - event.start_seconds >= 0.35 for event in events
    )
    assert all(event.confidence is None or event.confidence >= 0.7 for event in events)


def test_short_internal_digital_silence_remains_unknown():
    c_major = _tones((261.6256, 329.6276, 391.9954), 0.5)
    silence = [0.0] * round(0.25 * SAMPLE_RATE)

    events = estimate_chords(c_major + silence + c_major, SAMPLE_RATE)

    assert [event.symbol for event in events] == ["C", None, "C"]
    assert all(event.confidence is None or event.confidence >= 0.7 for event in events)


@pytest.mark.parametrize("sample_rate", [8_000, 44_100, 96_000, 192_000])
def test_supported_sample_rate_is_normalized_before_analysis(sample_rate: int):
    events = estimate_chords(_progression(sample_rate=sample_rate), sample_rate)

    assert [event.symbol for event in events] == ["C", "G", "Am", "F"]
    assert events[-1].end_seconds == pytest.approx(4.0)


def test_key_hint_does_not_force_an_out_of_key_chord():
    f_sharp_major = _tones((184.9972, 233.0819, 277.1826), 2.0)

    events = estimate_chords(
        f_sharp_major,
        SAMPLE_RATE,
        key_tonic="C",
        key_mode="major",
    )

    assert [event.symbol for event in events] == ["F#"]


def test_key_hint_cannot_flip_an_ambiguous_acoustic_winner():
    ambiguous_f = _weighted_tones(
        (
            (174.6141, 1.0),
            (207.6523, 1.0),
            (220.0000, 0.85),
            (261.6256, 1.0),
        ),
        2.0,
    )

    without_hint = estimate_chords(ambiguous_f, SAMPLE_RATE)
    with_hint = estimate_chords(
        ambiguous_f,
        SAMPLE_RATE,
        key_tonic="C",
        key_mode="major",
    )

    assert [event.symbol for event in with_hint] == [event.symbol for event in without_hint]
    assert [event.confidence for event in with_hint] == pytest.approx(
        [event.confidence for event in without_hint]
    )


def test_key_hint_does_not_turn_chromatic_ambiguity_into_a_chord():
    frequencies = tuple(261.6256 * 2 ** (semitone / 12.0) for semitone in range(12))

    events = estimate_chords(
        _tones(frequencies, 2.0),
        SAMPLE_RATE,
        key_tonic="C",
        key_mode="major",
    )

    assert [event.symbol for event in events] == [None]


@pytest.mark.parametrize(
    "frequencies",
    [
        (261.6256, 329.6276, 391.9954, 493.8833),
        (261.6256, 311.1270, 391.9954, 466.1638),
    ],
)
def test_seventh_chords_are_unknown_when_only_triads_are_supported(frequencies):
    events = estimate_chords(_tones(frequencies, 2.0), SAMPLE_RATE)

    assert [event.symbol for event in events] == [None]


@pytest.mark.parametrize(
    ("key_tonic", "key_mode"),
    [("H", "major"), ("C", "dorian"), ("C", None), (None, "major")],
)
def test_invalid_key_hints_are_rejected(key_tonic, key_mode):
    with pytest.raises(ValueError, match="key"):
        estimate_chords(
            _tones((261.6256, 329.6276, 391.9954), 1.0),
            SAMPLE_RATE,
            key_tonic=key_tonic,
            key_mode=key_mode,
        )


@pytest.mark.parametrize("silence_first", [True, False])
def test_short_silence_at_audio_edge_is_not_absorbed_into_a_chord(silence_first: bool):
    silence = [0.0] * round(0.34 * SAMPLE_RATE)
    c_major = _tones((261.6256, 329.6276, 391.9954), 1.0)
    samples = silence + c_major if silence_first else c_major + silence

    events = estimate_chords(samples, SAMPLE_RATE)

    assert len(events) == 2
    assert events[0 if silence_first else 1].symbol is None
    assert events[1 if silence_first else 0].symbol == "C"


def test_output_is_strict_json_and_versioned():
    payload = [event.to_dict() for event in estimate_chords(_progression(), SAMPLE_RATE)]

    encoded = json.dumps(payload, allow_nan=False)
    assert '"algorithm": "chroma-triad-viterbi-v1"' in encoded
    assert set(payload[0]) == {
        "symbol",
        "start_seconds",
        "end_seconds",
        "confidence",
        "algorithm",
    }


@pytest.mark.parametrize("sample_rate", [True, 7_999, 192_001])
def test_invalid_sample_rates_are_rejected(sample_rate):
    with pytest.raises(ValueError, match="sample_rate"):
        estimate_chords([0.0] * 10, sample_rate)


@pytest.mark.parametrize("samples", [[], [math.nan], [math.inf], [[0.0], [0.0]]])
def test_invalid_pcm_is_rejected(samples):
    with pytest.raises(ValueError, match="samples"):
        estimate_chords(samples, SAMPLE_RATE)


def test_over_ten_minutes_is_rejected_before_feature_extraction(monkeypatch):
    def fail_if_started(*args, **kwargs):
        raise AssertionError("feature extraction must not start")

    monkeypatch.setattr("museecho.analysis.chords.extract_harmonic_features", fail_if_started)
    oversized = np.zeros(SAMPLE_RATE * 600 + 1, dtype=np.float32)

    with pytest.raises(ValueError, match="600"):
        estimate_chords(oversized, SAMPLE_RATE)
