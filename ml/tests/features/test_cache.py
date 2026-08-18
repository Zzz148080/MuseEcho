from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from museecho_ml.features.cache import FeatureCache, FeatureCacheCorruption
from museecho_ml.features.cqt import CqtConfig, FeatureSequence


def _features() -> FeatureSequence:
    return FeatureSequence(
        main_cqt=np.arange(24, dtype=np.float32).reshape(6, 4),
        bass_cqt=np.arange(12, dtype=np.float32).reshape(3, 4),
        frame_times=np.arange(4, dtype=np.float64) * 0.1,
        valid_mask=np.array([True, True, True, False]),
    )


def test_feature_cache_key_binds_audio_config_and_extractor_version() -> None:
    audio_sha256 = "a" * 64

    first = FeatureCache.compute_key(audio_sha256, CqtConfig())
    same = FeatureCache.compute_key(audio_sha256, CqtConfig())
    changed_audio = FeatureCache.compute_key("b" * 64, CqtConfig())
    changed_config = FeatureCache.compute_key(
        audio_sha256, CqtConfig(hop_length=256)
    )
    changed_code = FeatureCache.compute_key(
        audio_sha256, CqtConfig(), extractor_version="cqt-v2"
    )

    assert first == same
    assert len(first) == 64
    assert len({first, changed_audio, changed_config, changed_code}) == 4


def test_feature_cache_round_trip_is_atomic_and_typed(tmp_path: Path) -> None:
    cache = FeatureCache(tmp_path)
    key = FeatureCache.compute_key("a" * 64, CqtConfig())

    path = cache.store(key, _features())
    loaded = cache.load(key)

    assert path.is_file()
    assert loaded is not None
    np.testing.assert_array_equal(loaded.main_cqt, _features().main_cqt)
    np.testing.assert_array_equal(loaded.bass_cqt, _features().bass_cqt)
    np.testing.assert_array_equal(loaded.frame_times, _features().frame_times)
    np.testing.assert_array_equal(loaded.valid_mask, _features().valid_mask)
    assert not list(tmp_path.rglob("*.tmp"))


def test_feature_cache_rejects_corrupt_entry(tmp_path: Path) -> None:
    cache = FeatureCache(tmp_path)
    key = FeatureCache.compute_key("a" * 64, CqtConfig())
    path = cache.path_for(key)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not an npz")

    with pytest.raises(FeatureCacheCorruption, match="corrupt"):
        cache.load(key)


def test_feature_cache_returns_none_for_miss(tmp_path: Path) -> None:
    cache = FeatureCache(tmp_path)
    key = FeatureCache.compute_key("a" * 64, CqtConfig())

    assert cache.load(key) is None
