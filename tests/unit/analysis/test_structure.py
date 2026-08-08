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
