from __future__ import annotations

import json
import math
import warnings

import numpy as np
import pytest

from museecho.analysis import harmonic_features
from museecho.analysis.structure import segment_structure

SAMPLE_RATE = 22_050


def _tones(frequencies: tuple[float, ...], duration_seconds: float) -> list[float]:
    count = round(duration_seconds * SAMPLE_RATE)
    return [
        0.7
        / len(frequencies)
        * sum(
            math.sin(2.0 * math.pi * frequency * index / SAMPLE_RATE) for frequency in frequencies
        )
        for index in range(count)
    ]


def _aba() -> list[float]:
    section_a = _tones((261.6256, 329.6276, 391.9954), 2.0)
    section_b = _tones((184.9972, 233.0819, 277.1826), 2.0)
    return section_a + section_b + section_a


def test_aba_sections_have_recurrent_labels_and_boundaries():
    segments = segment_structure(_aba(), SAMPLE_RATE)

    assert [segment.label for segment in segments] == ["A", "B", "A"]
    assert segments[0].start_seconds == 0.0
    assert segments[0].end_seconds == pytest.approx(2.0, abs=0.25)
    assert segments[1].end_seconds == pytest.approx(4.0, abs=0.25)
    assert segments[-1].end_seconds == pytest.approx(6.0)


def test_recurrent_multichord_sections_are_grouped_as_aba():
    c_major = _tones((261.6256, 329.6276, 391.9954), 1.0)
    g_major = _tones((195.9977, 246.9417, 293.6648), 1.0)
    f_sharp_major = _tones((184.9972, 233.0819, 277.1826), 1.0)
    c_sharp_major = _tones((138.5913, 174.6141, 207.6523), 1.0)
    section_a = c_major + g_major
    section_b = f_sharp_major + c_sharp_major

    segments = segment_structure(section_a + section_b + section_a, SAMPLE_RATE)

    assert [segment.label for segment in segments] == ["A", "B", "A"]
    assert segments[0].end_seconds == pytest.approx(2.0, abs=0.25)
    assert segments[1].end_seconds == pytest.approx(4.0, abs=0.25)


@pytest.mark.parametrize("chord_seconds", [0.5, 1.0])
def test_four_chord_sections_use_nonlocal_recurrence_for_aba_boundaries(
    chord_seconds: float,
):
    c = _tones((261.6256, 329.6276, 391.9954), chord_seconds)
    g = _tones((195.9977, 246.9417, 293.6648), chord_seconds)
    am = _tones((220.0000, 261.6256, 329.6276), chord_seconds)
    f = _tones((174.6141, 220.0000, 261.6256), chord_seconds)
    dm = _tones((146.8324, 174.6141, 220.0000), chord_seconds)
    section_a = c + g + am + f
    section_b = f + c + dm + g

    segments = segment_structure(section_a + section_b + section_a, SAMPLE_RATE)

    assert [segment.label for segment in segments] == ["A", "B", "A"]
    assert segments[0].end_seconds == pytest.approx(4 * chord_seconds, abs=0.3)
    assert segments[1].end_seconds == pytest.approx(8 * chord_seconds, abs=0.3)


def test_energy_only_change_does_not_create_a_structure_boundary():
    frequencies = (261.6256, 329.6276, 391.9954)
    quiet = np.asarray(_tones(frequencies, 2.0), dtype=np.float32) * 0.2
    loud = np.asarray(_tones(frequencies, 2.0), dtype=np.float32)

    segments = segment_structure(np.concatenate((quiet, loud)), SAMPLE_RATE)

    assert [segment.label for segment in segments] == [None]
    assert segments[0].end_seconds == pytest.approx(4.0)


@pytest.mark.parametrize(
    "frequencies",
    [
        (261.6256,),
        (261.6256, 329.6276, 391.9954),
        (261.6256, 391.9954),
    ],
)
def test_signal_without_structural_change_is_unknown(frequencies):
    segments = segment_structure(_tones(frequencies, 6.0), SAMPLE_RATE)

    assert len(segments) == 1
    assert segments[0].label is None
    assert segments[0].confidence is None


@pytest.mark.parametrize("middle_seconds", [1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0])
def test_unequal_middle_section_keeps_recurrent_aba_boundaries(middle_seconds: float):
    section_a = _tones((261.6256, 329.6276, 391.9954), 4.0)
    section_b = _tones((184.9972, 233.0819, 277.1826), middle_seconds)

    segments = segment_structure(section_a + section_b + section_a, SAMPLE_RATE)

    assert [segment.label for segment in segments] == ["A", "B", "A"]
    assert segments[0].end_seconds == pytest.approx(4.0, abs=0.3)
    assert segments[1].end_seconds == pytest.approx(4.0 + middle_seconds, abs=0.3)


@pytest.mark.parametrize(
    "cycle",
    [
        ((261.6256, 329.6276, 391.9954), (195.9977, 246.9417, 293.6648)),
        (
            (261.6256, 329.6276, 391.9954),
            (195.9977, 246.9417, 293.6648),
            (220.0000, 261.6256, 329.6276),
            (174.6141, 220.0000, 261.6256),
        ),
    ],
)
def test_uniform_repeating_progression_is_not_forced_into_sections(cycle):
    samples = [sample for _ in range(3) for chord in cycle for sample in _tones(chord, 1.0)]

    segments = segment_structure(samples, SAMPLE_RATE)

    assert [segment.label for segment in segments] == [None]


@pytest.mark.parametrize("middle", ["silence", "noise"])
def test_section_without_harmonic_evidence_has_unknown_label(middle: str):
    section_a = np.asarray(_tones((261.6256, 329.6276, 391.9954), 4.0), dtype=np.float32)
    if middle == "silence":
        section_b = np.zeros(SAMPLE_RATE * 2, dtype=np.float32)
    else:
        section_b = np.random.default_rng(13).normal(0.0, 0.2, SAMPLE_RATE * 2)

    segments = segment_structure(np.concatenate((section_a, section_b, section_a)), SAMPLE_RATE)

    assert [segment.label for segment in segments] == ["A", None, "A"]
    assert segments[1].confidence is None


@pytest.mark.parametrize("first_seconds", [3.0, 4.0])
def test_one_second_final_section_respects_minimum_duration(first_seconds: float):
    first = _tones((261.6256, 329.6276, 391.9954), first_seconds)
    final = _tones((184.9972, 233.0819, 277.1826), 1.0)

    segments = segment_structure(first + final, SAMPLE_RATE)

    assert len(segments) == 2
    assert segments[-1].end_seconds - segments[-1].start_seconds >= 1.0


@pytest.mark.parametrize("section_seconds", [2.0, 4.0, 8.0, 12.0])
def test_static_abc_sections_keep_all_novelty_boundaries(section_seconds: float):
    frequencies = (
        (261.6256, 329.6276, 391.9954),
        (184.9972, 233.0819, 277.1826),
        (146.8324, 184.9972, 220.0000),
    )
    samples = [sample for chord in frequencies for sample in _tones(chord, section_seconds)]

    segments = segment_structure(samples, SAMPLE_RATE)

    assert [segment.label for segment in segments] == ["A", "B", "C"]
    assert segments[0].end_seconds == pytest.approx(section_seconds, abs=0.3)
    assert segments[1].end_seconds == pytest.approx(2 * section_seconds, abs=0.3)


@pytest.mark.parametrize(
    ("sequence", "expected"),
    [
        ("ABAB", ["A", "B", "A", "B"]),
        ("ABCA", ["A", "B", "C", "A"]),
        ("ABCBA", ["A", "B", "C", "B", "A"]),
    ],
)
def test_multiple_novelty_boundaries_preserve_recurrent_labels(sequence, expected):
    frequencies = {
        "A": (261.6256, 329.6276, 391.9954),
        "B": (184.9972, 233.0819, 277.1826),
        "C": (146.8324, 184.9972, 220.0000),
    }
    samples = [sample for label in sequence for sample in _tones(frequencies[label], 2.0)]

    segments = segment_structure(samples, SAMPLE_RATE)

    assert [segment.label for segment in segments] == expected
    assert all(segment.end_seconds - segment.start_seconds >= 1.0 for segment in segments)


def test_recurrent_one_second_sections_never_fall_below_minimum_duration():
    section_a = _tones((261.6256, 329.6276, 391.9954), 1.0)
    section_b = _tones((184.9972, 233.0819, 277.1826), 2.0)

    segments = segment_structure(section_a + section_b + section_a, SAMPLE_RATE)

    assert [segment.label for segment in segments] == ["A", "B", "A"]
    assert all(segment.end_seconds - segment.start_seconds >= 1.0 for segment in segments)


@pytest.mark.parametrize(
    ("outer_seconds", "inner_seconds"),
    [(4.0, 1.0), (4.0, 2.0), (6.0, 2.0)],
)
def test_recurrent_outer_section_does_not_hide_distinct_middle_sections(
    outer_seconds: float,
    inner_seconds: float,
):
    frequencies = {
        "A": (261.6256, 329.6276, 391.9954),
        "B": (184.9972, 233.0819, 277.1826),
        "C": (146.8324, 184.9972, 220.0000),
    }
    samples = (
        _tones(frequencies["A"], outer_seconds)
        + _tones(frequencies["B"], inner_seconds)
        + _tones(frequencies["C"], inner_seconds)
        + _tones(frequencies["A"], outer_seconds)
    )

    segments = segment_structure(samples, SAMPLE_RATE)

    assert [segment.label for segment in segments] == ["A", "B", "C", "A"]
    assert all(segment.end_seconds - segment.start_seconds >= 1.0 for segment in segments)


@pytest.mark.parametrize("section_seconds", [1.0, 1.1, 1.2, 1.4])
def test_short_abcba_sections_keep_recurrence_and_minimum_duration(section_seconds: float):
    frequencies = {
        "A": (261.6256, 329.6276, 391.9954),
        "B": (184.9972, 233.0819, 277.1826),
        "C": (146.8324, 184.9972, 220.0000),
    }
    samples = [
        sample for label in "ABCBA" for sample in _tones(frequencies[label], section_seconds)
    ]

    segments = segment_structure(samples, SAMPLE_RATE)

    assert [segment.label for segment in segments] == ["A", "B", "C", "B", "A"]
    assert all(segment.end_seconds - segment.start_seconds >= 1.0 for segment in segments)


@pytest.mark.parametrize("section_seconds", [1.4, 1.5, 1.6])
def test_threefold_uniform_loop_is_unknown_without_duration_cliff(section_seconds: float):
    a = _tones((261.6256, 329.6276, 391.9954), section_seconds)
    b = _tones((184.9972, 233.0819, 277.1826), section_seconds)

    segments = segment_structure((a + b) * 3, SAMPLE_RATE)

    assert [segment.label for segment in segments] == [None]


@pytest.mark.parametrize(
    ("outer_seconds", "middle_labels"),
    [(2.0, "BCD"), (4.0, "BCD"), (6.0, "BCD"), (2.0, "BCDE")],
)
def test_recurrent_outer_section_keeps_unique_stable_middle_sections(
    outer_seconds: float,
    middle_labels: str,
):
    frequencies = {
        "A": (261.6256, 329.6276, 391.9954),
        "B": (184.9972, 233.0819, 277.1826),
        "C": (146.8324, 184.9972, 220.0000),
        "D": (164.8138, 207.6523, 246.9417),
        "E": (207.6523, 261.6256, 311.1270),
    }
    samples = _tones(frequencies["A"], outer_seconds)
    samples += [sample for label in middle_labels for sample in _tones(frequencies[label], 2.0)]
    samples += _tones(frequencies["A"], outer_seconds)

    segments = segment_structure(samples, SAMPLE_RATE)

    expected = ["A", *list(middle_labels), "A"]
    assert [segment.label for segment in segments] == expected


@pytest.mark.parametrize("repeat_count", [3, 4, 5])
def test_uniform_loop_is_unknown_for_any_three_or_more_repeats(repeat_count: int):
    a = _tones((261.6256, 329.6276, 391.9954), 1.5)
    b = _tones((184.9972, 233.0819, 277.1826), 1.5)

    segments = segment_structure((a + b) * repeat_count, SAMPLE_RATE)

    assert [segment.label for segment in segments] == [None]


@pytest.mark.parametrize("silence_first", [True, False])
def test_short_edge_padding_does_not_bypass_loop_detection(silence_first: bool):
    a = _tones((261.6256, 329.6276, 391.9954), 1.5)
    b = _tones((184.9972, 233.0819, 277.1826), 1.5)
    loop = np.asarray((a + b) * 3, dtype=np.float32)
    silence = np.zeros(round(0.25 * SAMPLE_RATE), dtype=np.float32)
    samples = np.concatenate((silence, loop) if silence_first else (loop, silence))

    segments = segment_structure(samples, SAMPLE_RATE)

    assert [segment.label for segment in segments] == [None]


def test_segments_cover_audio_without_gaps_or_overrun():
    segments = segment_structure(_aba(), SAMPLE_RATE)

    assert all(
        left.end_seconds == right.start_seconds for left, right in zip(segments, segments[1:])
    )
    assert all(0.0 <= segment.start_seconds < segment.end_seconds <= 6.0 for segment in segments)


def test_silence_returns_one_unknown_segment():
    segments = segment_structure([0.0] * (SAMPLE_RATE * 2), SAMPLE_RATE)

    assert len(segments) == 1
    assert segments[0].label is None
    assert segments[0].confidence is None
    assert (segments[0].start_seconds, segments[0].end_seconds) == (0.0, 2.0)


def test_noise_does_not_create_confident_structure():
    noise = np.random.default_rng(11).normal(0.0, 0.2, SAMPLE_RATE * 6)
    segments = segment_structure(noise, SAMPLE_RATE)

    assert len(segments) == 1
    assert segments[0].label is None


def test_output_is_strict_json_and_versioned():
    payload = [segment.to_dict() for segment in segment_structure(_aba(), SAMPLE_RATE)]

    encoded = json.dumps(payload, allow_nan=False)
    assert '"algorithm": "chroma-recurrence-novelty-v1"' in encoded
    assert set(payload[0]) == {
        "label",
        "start_seconds",
        "end_seconds",
        "confidence",
        "algorithm",
    }
    assert all(
        segment["label"] is None
        or (isinstance(segment["label"], str) and segment["label"].isalpha())
        for segment in payload
    )


def test_long_audio_feature_extraction_is_chunked(monkeypatch):
    observed_sample_counts: list[int] = []
    real_chroma_stft = harmonic_features.librosa.feature.chroma_stft

    def recording_chroma_stft(**kwargs):
        observed_sample_counts.append(len(kwargs["y"]))
        return real_chroma_stft(**kwargs)

    monkeypatch.setattr(harmonic_features.librosa.feature, "chroma_stft", recording_chroma_stft)
    samples = np.tile(np.asarray(_aba(), dtype=np.float32), 12)

    segment_structure(samples, SAMPLE_RATE)

    assert len(observed_sample_counts) >= 3
    assert max(observed_sample_counts) <= round(31.0 * SAMPLE_RATE)


def test_silent_analysis_chunks_do_not_emit_tuning_warnings():
    samples = np.concatenate(
        (np.asarray(_aba(), dtype=np.float32), np.zeros(SAMPLE_RATE * 36, dtype=np.float32))
    )

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        segment_structure(samples, SAMPLE_RATE)

    assert captured == []


@pytest.mark.parametrize("sample_rate", [True, 7_999, 192_001])
def test_invalid_sample_rates_are_rejected(sample_rate):
    with pytest.raises(ValueError, match="sample_rate"):
        segment_structure([0.0] * 10, sample_rate)


@pytest.mark.parametrize("samples", [[], [math.nan], [math.inf], [[0.0], [0.0]]])
def test_invalid_pcm_is_rejected(samples):
    with pytest.raises(ValueError, match="samples"):
        segment_structure(samples, SAMPLE_RATE)


def test_over_ten_minutes_is_rejected_before_feature_extraction(monkeypatch):
    def fail_if_started(*args, **kwargs):
        raise AssertionError("feature extraction must not start")

    monkeypatch.setattr("museecho.analysis.structure.extract_harmonic_features", fail_if_started)
    oversized = np.zeros(SAMPLE_RATE * 600 + 1, dtype=np.float32)

    with pytest.raises(ValueError, match="600"):
        segment_structure(oversized, SAMPLE_RATE)
