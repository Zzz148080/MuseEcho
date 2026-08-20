from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from museecho_ml.features.cqt import CqtConfig, extract_features

ML_ROOT = Path(__file__).resolve().parents[2]


def _tone(sample_rate: int, duration_seconds: float = 1.0) -> np.ndarray:
    times = np.arange(round(sample_rate * duration_seconds)) / sample_rate
    return np.sin(2 * math.pi * 440.0 * times).astype(np.float32)


def test_cqt_resamples_and_returns_aligned_main_bass_and_time_axes() -> None:
    config = CqtConfig(
        sample_rate=22_050,
        hop_length=512,
        fmin_hz=32.70319566257483,
        bins_per_octave=24,
        n_octaves=6,
        bass_octaves=3,
        log_scale=10.0,
    )

    features = extract_features(_tone(16_000), sample_rate=16_000, config=config)

    assert features.main_cqt.shape[0] == 144
    assert features.bass_cqt.shape[0] == 72
    assert features.main_cqt.shape[1] == features.bass_cqt.shape[1]
    assert features.main_cqt.shape[1] == len(features.frame_times)
    assert features.valid_mask.shape == features.frame_times.shape
    assert features.valid_mask.dtype == np.bool_
    assert features.valid_mask.any()
    assert np.all(np.diff(features.frame_times) > 0)
    assert np.isfinite(features.main_cqt).all()
    assert np.isfinite(features.bass_cqt).all()


def test_chunked_cqt_preserves_full_time_axis_and_interior_values() -> None:
    audio = _tone(8_000, duration_seconds=6.3)
    common = {
        "sample_rate": 8_000,
        "hop_length": 256,
        "fmin_hz": 55.0,
        "bins_per_octave": 12,
        "n_octaves": 3,
        "bass_octaves": 1,
        "log_scale": 10.0,
        "minimum_analysis_seconds": 1.0,
        "context_seconds": 1.0,
    }

    chunked = extract_features(
        audio,
        sample_rate=8_000,
        config=CqtConfig(**common, chunk_seconds=2.0),
    )
    single = extract_features(
        audio,
        sample_rate=8_000,
        config=CqtConfig(**common, chunk_seconds=20.0),
    )

    assert chunked.main_cqt.shape == single.main_cqt.shape
    np.testing.assert_array_equal(chunked.frame_times, single.frame_times)
    np.testing.assert_array_equal(chunked.valid_mask, single.valid_mask)
    np.testing.assert_allclose(chunked.main_cqt, single.main_cqt, atol=0.08, rtol=0.08)


def test_five_minute_audio_uses_complete_bounded_chunked_time_axis() -> None:
    sample_rate = 22_050
    duration_seconds = 300.0
    sample_count = round(sample_rate * duration_seconds)
    times = np.arange(sample_count, dtype=np.float32) / sample_rate
    audio = (
        0.4 * np.sin(2 * math.pi * 220.0 * times)
        + 0.3 * np.sin(2 * math.pi * 277.18 * times)
        + 0.2 * np.sin(2 * math.pi * 329.63 * times)
    ).astype(np.float32)
    config = CqtConfig()

    features = extract_features(audio, sample_rate=sample_rate, config=config)

    assert features.main_cqt.shape == (
        config.bins_per_octave * config.n_octaves,
        math.ceil(sample_count / config.hop_length),
    )
    assert features.valid_mask.all()
    assert features.frame_times[-1] < duration_seconds
    assert np.isfinite(features.main_cqt).all()


@pytest.mark.parametrize(
    ("audio", "sample_rate", "message"),
    [
        (np.zeros((2, 100), dtype=np.float32), 22_050, "mono"),
        (np.array([0.0, np.nan], dtype=np.float32), 22_050, "finite"),
        (np.zeros(100, dtype=np.float32), 0, "sample_rate"),
        (np.zeros(0, dtype=np.float32), 22_050, "non-empty"),
    ],
)
def test_cqt_rejects_invalid_audio(
    audio: np.ndarray, sample_rate: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        extract_features(audio, sample_rate=sample_rate, config=CqtConfig())


def test_versioned_cqt_config_matches_code() -> None:
    payload = json.loads(
        (ML_ROOT / "configs" / "features-cqt-v1.json").read_text(encoding="utf-8")
    )

    assert CqtConfig.from_dict(payload) == CqtConfig()
