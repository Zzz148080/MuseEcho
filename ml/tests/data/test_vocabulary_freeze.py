from __future__ import annotations

from typing import Any

import pytest

from museecho_ml.data.vocabulary_freeze import (
    freeze_plan_c_vocabulary,
    map_to_frozen_vocabulary,
)
from museecho_ml.labels import CanonicalChord
from museecho_ml.vocabulary import ChordVocabulary


def _track(index: int, quality: str, *, cover_group_id: str | None = None) -> dict[str, Any]:
    return {
        "dataset_id": "fixture",
        "track_id": f"fixture:track-{index:03d}",
        "work_id": f"fixture:work-{index:03d}",
        "cover_group_id": cover_group_id or f"fixture:cover-{index:03d}",
        "intervals": [
            {
                "start_seconds": 0.0,
                "end_seconds": 1.0,
                "root": "C",
                "quality": quality,
                "bass": "1",
            }
        ],
    }


def _manifest(
    *, split: str = "train", role: str = "real-gold", tracks: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "corpus_role": role,
        "split": split,
        "split_sha256": "a" * 64,
        "tracks": tracks,
    }


def test_vocabulary_counts_cover_groups_only_from_real_gold_train() -> None:
    tracks = [_track(index, "maj") for index in range(20)]
    tracks.extend(_track(100 + index, "dim") for index in range(19))
    tracks.extend(_track(200 + index, "sus2") for index in range(25))

    frozen = freeze_plan_c_vocabulary(_manifest(tracks=tracks))

    assert frozen["quality_group_counts"] == {"dim": 19, "maj": 20, "sus2": 25}
    assert frozen["quality_labels"] == ["maj", "N", "X"]
    assert frozen["mapped_to_x"] == [
        "7",
        "dim",
        "hdim7",
        "maj7",
        "min",
        "min7",
        "sus2",
        "sus4",
    ]
    assert len(frozen["vocabulary_sha256"]) == 64


def test_vocabulary_does_not_count_two_tracks_from_the_same_cover_twice() -> None:
    tracks = [
        _track(1, "maj", cover_group_id="fixture:shared-cover"),
        _track(2, "maj", cover_group_id="fixture:shared-cover"),
    ]

    frozen = freeze_plan_c_vocabulary(
        _manifest(tracks=tracks), minimum_group_count=2
    )

    assert frozen["quality_group_counts"]["maj"] == 1
    assert "maj" not in frozen["quality_labels"]


@pytest.mark.parametrize("split", ["calibration", "validation", "test"])
def test_vocabulary_refuses_non_train_split(split: str) -> None:
    with pytest.raises(PermissionError, match="train"):
        freeze_plan_c_vocabulary(_manifest(split=split, tracks=[_track(1, "maj")]))


def test_vocabulary_refuses_non_real_gold_training_data() -> None:
    with pytest.raises(ValueError, match="real-gold"):
        freeze_plan_c_vocabulary(
            _manifest(role="synthetic-supervised", tracks=[_track(1, "maj")])
        )


def test_sus2_maps_to_full_x_state_even_when_it_has_twenty_groups() -> None:
    tracks = [_track(index, "maj") for index in range(20)]
    tracks.extend(_track(100 + index, "sus2") for index in range(20))
    frozen = freeze_plan_c_vocabulary(_manifest(tracks=tracks))
    vocabulary = ChordVocabulary.from_dict(frozen)

    mapped = map_to_frozen_vocabulary(
        CanonicalChord("D", "sus2", "1"), vocabulary
    )

    assert (mapped.root, mapped.quality, mapped.bass) == ("X", "X", "X")
    assert mapped.mapping_reason == "plan-c-unsupported-quality:sus2"


def test_supported_quality_is_not_changed_by_frozen_mapping() -> None:
    tracks = [_track(index, "maj") for index in range(20)]
    vocabulary = ChordVocabulary.from_dict(
        freeze_plan_c_vocabulary(_manifest(tracks=tracks))
    )
    chord = CanonicalChord("D", "maj", "b3")

    assert map_to_frozen_vocabulary(chord, vocabulary) is chord
