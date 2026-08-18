from __future__ import annotations

import numpy as np
import pytest

from museecho_ml.data.manifest import ChordInterval
from museecho_ml.features.augment import transpose_example
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
