from __future__ import annotations

import numpy as np
import pytest

from museecho_ml.data.manifest import ChordInterval
from museecho_ml.features.augment import (
    sample_time_stretch_rate,
    time_stretch_example,
    transpose_example,
)
from museecho_ml.features.cqt import FeatureSequence
from museecho_ml.labels import parse_annotation


def _features() -> FeatureSequence:
    main = np.arange(16, dtype=np.float32).reshape(8, 2)
    bass = np.arange(8, dtype=np.float32).reshape(4, 2)
    return FeatureSequence(
        main_cqt=main,
        bass_cqt=bass,
        frame_times=np.array([0.0, 0.1], dtype=np.float64),
        valid_mask=np.array([True, False]),
    )


def test_transposition_shifts_cqt_and_root_while_preserving_relative_bass() -> None:
    intervals = (
        ChordInterval(0.0, 1.0, parse_annotation("C:maj/3")),
        ChordInterval(1.0, 2.0, parse_annotation("N")),
    )

    features, labels = transpose_example(
        _features(), intervals, semitones=1, bins_per_octave=24
    )

    np.testing.assert_array_equal(features.main_cqt[:2], np.zeros((2, 2)))
    np.testing.assert_array_equal(features.main_cqt[2:], _features().main_cqt[:-2])
    np.testing.assert_array_equal(features.bass_cqt[:2], np.zeros((2, 2)))
    np.testing.assert_array_equal(features.bass_cqt[2:], _features().bass_cqt[:-2])
    np.testing.assert_array_equal(features.frame_times, _features().frame_times)
    np.testing.assert_array_equal(features.valid_mask, _features().valid_mask)
    assert labels[0].chord.display_symbol == "C#/F"
    assert labels[1].chord.display_symbol == "N"
    assert (labels[0].start_seconds, labels[0].end_seconds) == (0.0, 1.0)


def test_transposition_rejects_non_semitone_cqt_resolution() -> None:
    with pytest.raises(ValueError, match="divisible"):
        transpose_example(_features(), (), semitones=1, bins_per_octave=25)


def test_time_stretch_resamples_features_and_scales_label_boundaries() -> None:
    features = FeatureSequence(
        main_cqt=np.arange(16, dtype=np.float32).reshape(4, 4),
        bass_cqt=np.arange(8, dtype=np.float32).reshape(2, 4),
        frame_times=np.array([0.0, 0.1, 0.2, 0.3], dtype=np.float64),
        valid_mask=np.ones(4, dtype=np.bool_),
    )
    intervals = (ChordInterval(0.0, 0.4, parse_annotation("C:maj")),)

    stretched, labels = time_stretch_example(features, intervals, rate=2.0)

    assert stretched.main_cqt.shape == (4, 2)
    assert stretched.bass_cqt.shape == (2, 2)
    np.testing.assert_array_equal(stretched.frame_times, np.array([0.0, 0.1]))
    np.testing.assert_array_equal(stretched.valid_mask, np.ones(2, dtype=np.bool_))
    np.testing.assert_allclose(stretched.main_cqt, features.main_cqt[:, [0, 2]])
    assert (labels[0].start_seconds, labels[0].end_seconds) == (0.0, 0.2)


def test_time_stretch_rate_is_seeded_and_can_be_disabled() -> None:
    first = sample_time_stretch_rate(seed=20260818, minimum=0.9, maximum=1.1)
    second = sample_time_stretch_rate(seed=20260818, minimum=0.9, maximum=1.1)

    assert first == second
    assert 0.9 <= first <= 1.1
    assert sample_time_stretch_rate(
        seed=20260818, minimum=0.9, maximum=1.1, enabled=False
    ) == 1.0
