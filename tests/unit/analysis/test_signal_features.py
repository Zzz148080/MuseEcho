from __future__ import annotations

import json
import math

import numpy as np
import pytest

from museecho.analysis.energy import extract_energy
from museecho.analysis.rhythm import estimate_rhythm
from museecho.analysis.signal_features import SignalFeatureConfig, extract_signal_features
from tests.fixtures.audio_factory import sine_samples

SAMPLE_RATE = 22_050


def _metronome_samples(*, bpm: float = 120.0, duration_seconds: float = 8.0) -> list[float]:
    beat_length = round((60.0 / bpm) * SAMPLE_RATE)
    click_length = round(0.02 * SAMPLE_RATE)
    samples: list[float] = []
    for index in range(round(duration_seconds * SAMPLE_RATE)):
        within_beat = index % beat_length
        envelope = max(0.0, 1.0 - within_beat / click_length)
        click = math.sin(2.0 * math.pi * 1_500.0 * index / SAMPLE_RATE)
        samples.append(0.8 * envelope * click if within_beat < click_length else 0.0)
    return samples


def _subdivided_metronome_samples(*, duration_seconds: float = 8.0) -> list[float]:
    beat_length = round(0.5 * SAMPLE_RATE)
    subdivision_length = beat_length // 2
    click_length = round(0.02 * SAMPLE_RATE)
    samples: list[float] = []
    for index in range(round(duration_seconds * SAMPLE_RATE)):
        within_subdivision = index % subdivision_length
        if within_subdivision >= click_length:
            samples.append(0.0)
            continue
        subdivision_index = index // subdivision_length
        amplitude = 0.8 if subdivision_index % 2 == 0 else 0.16
        envelope = 1.0 - within_subdivision / click_length
        click = math.sin(2.0 * math.pi * 1_500.0 * index / SAMPLE_RATE)
        samples.append(amplitude * envelope * click)
    return samples


def test_metronome_estimates_120_bpm_with_monotonic_beats():
    samples = _metronome_samples()

    result = extract_signal_features(samples, SAMPLE_RATE)

    assert result.bpm == pytest.approx(120.0, abs=3.0)
    assert result.bpm_confidence is not None
    assert result.bpm_confidence >= 0.7
    assert len(result.beat_positions_seconds) >= 8
    assert list(result.beat_positions_seconds) == sorted(result.beat_positions_seconds)
    assert all(0.0 <= value <= result.duration_seconds for value in result.beat_positions_seconds)
    assert result.rhythm_algorithm


def test_weak_eighth_note_subdivisions_resolve_to_the_strong_120_bpm_pulse():
    result = extract_signal_features(_subdivided_metronome_samples(), SAMPLE_RATE)

    assert result.bpm == pytest.approx(120.0, abs=3.0)
    assert result.bpm_confidence is not None
    assert result.bpm_confidence >= 0.55
    assert len(result.beat_positions_seconds) >= 8


def test_long_ambiguous_track_surfaces_a_tentative_half_tempo(monkeypatch):
    onset_envelope = np.ones(600, dtype=np.float64)
    monkeypatch.setattr(
        "museecho.analysis.rhythm._chunked_onset_strength",
        lambda *args, **kwargs: onset_envelope,
    )
    monkeypatch.setattr(
        "museecho.analysis.rhythm._estimate_periodic_tempo",
        lambda *args, **kwargs: (160.0, 0.18, 0.14),
    )
    monkeypatch.setattr(
        "museecho.analysis.rhythm._chunked_beat_frames",
        lambda *args, bpm, **kwargs: np.arange(0, 600, 4 if bpm > 100.0 else 8),
    )
    monkeypatch.setattr(
        "museecho.analysis.rhythm._beat_accent_imbalance",
        lambda _onset, frames: 0.05 if frames.size > 100 else 0.08,
    )
    monkeypatch.setattr(
        "museecho.analysis.rhythm._rhythm_confidence",
        lambda *args, **kwargs: 0.53,
    )

    result = estimate_rhythm(
        np.full(60_000, 0.1, dtype=np.float32),
        1_000,
        hop_length=100,
        minimum_duration_seconds=2.0,
        minimum_signal_rms=1e-4,
        minimum_confidence=0.55,
        minimum_onset_periodicity=0.2,
        maximum_beat_accent_imbalance=0.25,
        maximum_sample_rate=1_000,
        n_fft=128,
        band_count=32,
        chunk_seconds=30.0,
    )

    assert result.bpm == 80.0
    assert result.confidence == 0.53
    assert len(result.beat_positions_seconds) >= 3


def test_constant_positive_onset_envelope_returns_unknown_rhythm(monkeypatch):
    monkeypatch.setattr(
        "museecho.analysis.rhythm._chunked_onset_strength",
        lambda *args, **kwargs: np.ones(600, dtype=np.float64),
    )

    result = estimate_rhythm(
        np.full(60_000, 0.1, dtype=np.float32),
        1_000,
        hop_length=100,
        minimum_duration_seconds=2.0,
        minimum_signal_rms=1e-4,
        minimum_confidence=0.55,
        minimum_onset_periodicity=0.2,
        maximum_beat_accent_imbalance=0.25,
        maximum_sample_rate=1_000,
        n_fft=128,
        band_count=32,
        chunk_seconds=30.0,
    )

    assert result.bpm is None
    assert result.confidence is None
    assert result.beat_positions_seconds == ()


@pytest.mark.parametrize("bpm", [180.0, 220.0])
def test_fast_metronome_does_not_report_a_high_confidence_half_tempo(bpm: float):
    result = extract_signal_features(
        _metronome_samples(bpm=bpm, duration_seconds=12.0),
        SAMPLE_RATE,
    )

    assert result.bpm == pytest.approx(bpm, abs=5.0)
    assert result.bpm_confidence is not None
    assert result.bpm_confidence >= 0.7


def test_waveform_buckets_preserve_minimum_and_maximum_peaks():
    samples = [-0.8, 0.2, -0.1, 0.9, -0.4, 0.5, -1.0, 0.7]
    config = SignalFeatureConfig(waveform_bucket_count=4, frame_length=4, hop_length=2)

    result = extract_signal_features(samples, 8, config=config)

    assert result.waveform.minimums == pytest.approx((-0.8, -0.1, -0.4, -1.0))
    assert result.waveform.maximums == pytest.approx((0.2, 0.9, 0.5, 0.7))
    assert result.waveform.resolution_seconds == pytest.approx(0.25)
    assert result.waveform.confidence == 1.0
    assert result.waveform.algorithm


def test_waveform_buckets_clamp_decoder_overshoot_to_safe_display_range():
    samples = [-1.2, 0.2, -0.1, 1.25]
    config = SignalFeatureConfig(waveform_bucket_count=2, frame_length=4, hop_length=2)

    result = extract_signal_features(samples, 4, config=config)

    assert result.waveform.minimums == pytest.approx((-1.0, -0.1))
    assert result.waveform.maximums == pytest.approx((0.2, 1.0))


def test_segmented_energy_detects_rise_and_fall_near_boundaries():
    samples: list[float] = []
    for amplitude in (0.1, 0.7, 0.25):
        samples.extend(sine_samples(1.0, 440.0, SAMPLE_RATE, amplitude))

    result = extract_signal_features(samples, SAMPLE_RATE)

    assert result.energy.points
    assert min(result.energy.points) >= 0.0
    assert max(result.energy.points) <= 1.0
    rise = next(change for change in result.energy_changes if change.direction == "rise")
    fall = next(change for change in result.energy_changes if change.direction == "fall")
    assert rise.timestamp_seconds == pytest.approx(1.0, abs=0.15)
    assert fall.timestamp_seconds == pytest.approx(2.0, abs=0.15)
    assert rise.confidence >= 0.7
    assert fall.confidence >= 0.7
    assert result.energy.algorithm


@pytest.mark.parametrize("boundary_seconds", [0.15, 0.25])
def test_early_sustained_energy_rise_is_not_hidden(boundary_seconds: float):
    samples = sine_samples(boundary_seconds, 440.0, SAMPLE_RATE, 0.1)
    samples += sine_samples(2.0 - boundary_seconds, 440.0, SAMPLE_RATE, 0.7)

    result = extract_signal_features(samples, SAMPLE_RATE)

    rise = next(change for change in result.energy_changes if change.direction == "rise")
    assert rise.timestamp_seconds == pytest.approx(boundary_seconds, abs=0.12)


@pytest.mark.parametrize("bpm", [60.0, 120.0, 180.0, 220.0])
def test_stable_metronome_beats_are_not_macro_energy_changes(bpm: float):
    result = extract_signal_features(
        _metronome_samples(bpm=bpm, duration_seconds=12.0), SAMPLE_RATE
    )

    assert result.energy_changes == ()


def test_incomplete_tail_frame_does_not_create_a_false_energy_change():
    sample_count = 10 * 512 + 1
    samples = [0.5 * math.sin(2.0 * math.pi * index / 512.0) for index in range(sample_count)]
    config = SignalFeatureConfig(frame_length=512, hop_length=512)

    result = extract_signal_features(samples, SAMPLE_RATE, config=config)

    assert result.energy_changes == ()


def test_energy_change_confidence_varies_with_margin_above_threshold():
    samples = np.concatenate(
        (
            np.full(512 * 5, 0.5, dtype=np.float32),
            np.full(512 * 5, 0.55, dtype=np.float32),
        )
    )

    _, changes = extract_energy(
        samples,
        SAMPLE_RATE,
        frame_length=512,
        hop_length=512,
        change_zscore=3.5,
        minimum_change=0.08,
        silence_rms=1e-4,
        change_window_seconds=0.1,
    )

    assert len(changes) == 1
    assert 0.7 <= changes[0].confidence < 1.0


def test_silence_returns_unknown_rhythm_and_zero_energy():
    result = extract_signal_features([0.0] * (SAMPLE_RATE * 2), SAMPLE_RATE)

    assert result.bpm is None
    assert result.bpm_confidence is None
    assert result.beat_positions_seconds == ()
    assert result.energy_changes == ()
    assert set(result.energy.points) == {0.0}


def test_low_sample_rate_short_signal_returns_unknown_before_fft(monkeypatch):
    def fail_if_fft_starts(*args, **kwargs):
        raise AssertionError("FFT extraction must not start when n_fft exceeds input length")

    monkeypatch.setattr("museecho.analysis.rhythm._chunked_onset_strength", fail_if_fft_starts)
    samples = sine_samples(2.1, 20.0, 200, 0.5)

    result = extract_signal_features(samples, 200)

    assert result.bpm is None
    assert result.bpm_confidence is None
    assert result.beat_positions_seconds == ()


def test_aperiodic_noise_returns_unknown_rhythm():
    noise = np.random.default_rng(7).normal(0.0, 0.2, SAMPLE_RATE * 8).astype(np.float32)

    result = extract_signal_features(noise, SAMPLE_RATE)

    assert result.bpm is None
    assert result.bpm_confidence is None
    assert result.beat_positions_seconds == ()


def test_output_is_strict_json_and_contains_versioned_algorithms():
    result = extract_signal_features(_metronome_samples(duration_seconds=4.0), SAMPLE_RATE)

    payload = result.to_dict()
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)

    assert '"config_version": "signal-v3"' in encoded
    assert payload["waveform"]["algorithm"]
    assert payload["energy"]["algorithm"]
    assert payload["rhythm"]["algorithm"]


@pytest.mark.parametrize(
    ("samples", "sample_rate", "message"),
    [
        ([], SAMPLE_RATE, "samples cannot be empty"),
        ([0.0], 0, "sample_rate must be positive"),
        ([math.nan], SAMPLE_RATE, "samples must be finite"),
        ([math.inf], SAMPLE_RATE, "samples must be finite"),
    ],
)
def test_invalid_signal_inputs_are_rejected(samples, sample_rate, message):
    with pytest.raises(ValueError, match=message):
        extract_signal_features(samples, sample_rate)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"waveform_bucket_count": 0},
        {"waveform_bucket_count": 4.5},
        {"frame_length": 0},
        {"frame_length": 1024.0},
        {"hop_length": 0},
        {"hop_length": 512.0},
        {"frame_length": 256, "hop_length": 512},
        {"energy_change_zscore": 0.0},
        {"minimum_energy_change": -0.1},
        {"minimum_energy_change": 0.0},
        {"energy_change_window_seconds": 0.01},
        {"energy_change_window_seconds": 10.0},
        {"minimum_rhythm_seconds": 0.0},
        {"maximum_beat_accent_imbalance": -0.1},
        {"maximum_beat_accent_imbalance": 1.1},
        {"maximum_rhythm_sample_rate": 1},
        {"maximum_rhythm_sample_rate": 10_000},
        {"rhythm_n_fft": 513},
        {"rhythm_band_count": 256},
        {"rhythm_chunk_seconds": 1.0},
        {"maximum_rhythm_sample_rate": 1_000, "minimum_rhythm_seconds": 0.25},
    ],
)
def test_signal_feature_config_rejects_invalid_values(kwargs):
    with pytest.raises(ValueError):
        SignalFeatureConfig(**kwargs)
