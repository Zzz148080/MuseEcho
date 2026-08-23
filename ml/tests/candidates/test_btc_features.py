from __future__ import annotations

import warnings

import numpy as np
import pytest

from museecho_ml.candidates.btc_features import (
    BtcFeatureConfig,
    extract_btc_features,
    standardize_btc_features,
)


def test_btc_features_are_deterministic_144_bin_log_cqt() -> None:
    config = BtcFeatureConfig.official()
    time = np.arange(22_050, dtype=np.float32) / 22_050
    samples = np.sin(2 * np.pi * 220 * time).astype(np.float32)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        first = extract_btc_features(samples, 22_050, config)
        second = extract_btc_features(samples, 22_050, config)

    assert first.shape[1] == 144
    assert first.dtype == np.float32
    assert first.flags.c_contiguous
    assert np.isfinite(first).all()
    np.testing.assert_array_equal(first, second)


def test_btc_feature_config_freezes_upstream_geometry() -> None:
    config = BtcFeatureConfig.official()

    assert config.sample_rate == 22_050
    assert config.n_bins == 144
    assert config.bins_per_octave == 24
    assert config.hop_length == 2_048
    assert config.chunk_seconds == 10.0
    assert config.timestep == 108
    assert config.frame_seconds == pytest.approx(10.0 / 108)


@pytest.mark.parametrize(
    "samples",
    [
        np.asarray([], dtype=np.float32),
        np.asarray([np.nan], dtype=np.float32),
        np.asarray([[0.0]], dtype=np.float32),
        np.asarray([0], dtype=np.int16),
    ],
)
def test_btc_features_reject_invalid_audio(samples: np.ndarray) -> None:
    with pytest.raises(ValueError, match="BTC audio"):
        extract_btc_features(samples, 22_050, BtcFeatureConfig.official())


@pytest.mark.parametrize("sample_rate", [0, -1, True])
def test_btc_features_reject_invalid_sample_rate(sample_rate: int) -> None:
    with pytest.raises(ValueError, match="sample rate"):
        extract_btc_features(
            np.zeros(22_050, dtype=np.float32),
            sample_rate,
            BtcFeatureConfig.official(),
        )


def test_btc_feature_standardization_uses_scalar_checkpoint_statistics() -> None:
    features = np.asarray([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)

    standardized = standardize_btc_features(features, mean=1.0, std=2.0)

    np.testing.assert_array_equal(
        standardized,
        np.asarray([[0.0, 0.5], [1.0, 1.5]], dtype=np.float32),
    )


@pytest.mark.parametrize(("mean", "std"), [(float("nan"), 1.0), (0.0, 0.0)])
def test_btc_feature_standardization_rejects_invalid_statistics(
    mean: float, std: float
) -> None:
    with pytest.raises(ValueError, match="normalization"):
        standardize_btc_features(np.ones((2, 144), dtype=np.float32), mean, std)
