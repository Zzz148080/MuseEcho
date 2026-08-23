from __future__ import annotations

import numpy as np
import pytest

from museecho_ml.candidates.btc_labels import (
    BTC_QUALITIES,
    BTC_ROOTS,
    decode_btc_class,
    frames_to_intervals,
)
from museecho_ml.labels import SUPPORTED_QUALITIES


@pytest.mark.parametrize("quality_offset", [3, 4, 5, 7, 10])
def test_unsupported_btc_qualities_map_strictly_to_x(quality_offset: int) -> None:
    chord = decode_btc_class(4 * 14 + quality_offset)

    assert (chord.root, chord.quality, chord.bass) == ("X", "X", "X")
    assert chord.mapping_reason is not None
    assert chord.mapping_reason.startswith("unsupported-quality:")


def test_every_btc_class_has_the_frozen_upstream_mapping() -> None:
    assert len(BTC_ROOTS) == 12
    assert len(BTC_QUALITIES) == 14
    unsupported = {"aug", "min6", "maj6", "minmaj7", "dim7"}

    for index in range(168):
        root_index, quality_index = divmod(index, 14)
        chord = decode_btc_class(index)
        quality = BTC_QUALITIES[quality_index]
        if quality in unsupported:
            assert (chord.root, chord.quality, chord.bass) == ("X", "X", "X")
            assert chord.mapping_reason == f"unsupported-quality:{quality}"
        else:
            assert chord.root == BTC_ROOTS[root_index]
            assert chord.quality == quality
            assert chord.quality in SUPPORTED_QUALITIES
            assert chord.bass == "1"
            assert chord.mapping_reason is None
        assert chord.display_symbol


def test_btc_special_classes_are_frozen() -> None:
    assert decode_btc_class(168).root == "X"
    assert decode_btc_class(168).display_symbol == "X"
    assert decode_btc_class(169).root == "N"
    assert decode_btc_class(169).display_symbol == "N"


@pytest.mark.parametrize("index", [True, -1, 170])
def test_btc_class_index_must_be_an_integer_in_the_170_class_range(
    index: int,
) -> None:
    with pytest.raises(ValueError, match="class index"):
        decode_btc_class(index)


def test_frame_events_cover_the_track_and_merge_equal_states() -> None:
    events = frames_to_intervals(
        np.asarray([1, 1, 169, 15], dtype=np.int64),
        np.asarray([0.8, 0.6, 0.9, 0.7], dtype=np.float64),
        frame_seconds=0.5,
        duration_seconds=2.0,
    )

    assert [(event.start_seconds, event.end_seconds) for event in events] == [
        (0.0, 1.0),
        (1.0, 1.5),
        (1.5, 2.0),
    ]
    assert [event.chord for event in events] == [
        decode_btc_class(1),
        decode_btc_class(169),
        decode_btc_class(15),
    ]
    assert events[0].confidence == pytest.approx(0.7)


def test_frame_events_clamp_only_the_last_frame_to_exact_duration() -> None:
    events = frames_to_intervals(
        np.asarray([1, 15, 29], dtype=np.int64),
        np.asarray([0.8, 0.7, 0.6], dtype=np.float64),
        frame_seconds=0.5,
        duration_seconds=1.2,
    )

    assert [(event.start_seconds, event.end_seconds) for event in events] == [
        (0.0, 0.5),
        (0.5, 1.0),
        (1.0, 1.2),
    ]


@pytest.mark.parametrize(
    ("class_ids", "confidences", "frame_seconds", "duration_seconds", "message"),
    [
        (np.asarray([], dtype=np.int64), np.asarray([]), 0.5, 1.0, "non-empty"),
        (np.asarray([[1]], dtype=np.int64), np.asarray([0.5]), 0.5, 1.0, "one-dimensional"),
        (np.asarray([1], dtype=np.int64), np.asarray([0.5, 0.4]), 0.5, 1.0, "equal length"),
        (np.asarray([1], dtype=np.int64), np.asarray([np.nan]), 0.5, 1.0, "confidence"),
        (np.asarray([1], dtype=np.int64), np.asarray([1.1]), 0.5, 1.0, "confidence"),
        (np.asarray([1], dtype=np.int64), np.asarray([0.5]), 0.0, 1.0, "frame duration"),
        (np.asarray([1], dtype=np.int64), np.asarray([0.5]), 0.5, 0.0, "track duration"),
        (
            np.asarray([1, 15, 29], dtype=np.int64),
            np.asarray([0.5, 0.5, 0.5]),
            0.5,
            1.0,
            "extra frames",
        ),
    ],
)
def test_frame_events_reject_invalid_timeline_inputs(
    class_ids: np.ndarray,
    confidences: np.ndarray,
    frame_seconds: float,
    duration_seconds: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        frames_to_intervals(
            class_ids,
            confidences,
            frame_seconds=frame_seconds,
            duration_seconds=duration_seconds,
        )
