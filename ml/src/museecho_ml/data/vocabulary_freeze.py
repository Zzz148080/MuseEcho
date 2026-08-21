from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from museecho_ml.artifacts import canonical_sha256
from museecho_ml.labels import BASS_INTERVALS, PITCH_NAMES, SUPPORTED_QUALITIES, CanonicalChord
from museecho_ml.vocabulary import ChordVocabulary

PLAN_C_INITIAL_QUALITIES = (
    "maj",
    "min",
    "7",
    "maj7",
    "min7",
    "dim",
    "hdim7",
    "sus4",
)


def freeze_plan_c_vocabulary(
    train_manifest: Mapping[str, Any], *, minimum_group_count: int = 20
) -> dict[str, Any]:
    if type(minimum_group_count) is not int or minimum_group_count <= 0:
        raise ValueError("vocabulary minimum group count must be a positive integer")
    tracks = _validated_real_gold_train(train_manifest)
    quality_groups: dict[str, set[tuple[str, str]]] = {}
    for track in tracks:
        dataset_id = str(track["dataset_id"])
        cover_group_id = str(track["cover_group_id"])
        intervals = track.get("intervals")
        if not isinstance(intervals, list):
            raise ValueError("vocabulary train tracks must contain interval lists")
        for interval in intervals:
            if not isinstance(interval, Mapping):
                raise ValueError("vocabulary train intervals must be objects")
            quality = interval.get("quality")
            if not isinstance(quality, str) or quality not in (*SUPPORTED_QUALITIES, "N", "X"):
                raise ValueError("vocabulary train interval quality is invalid")
            quality_groups.setdefault(quality, set()).add(
                (dataset_id, cover_group_id)
            )
    counts = {
        quality: len(groups) for quality, groups in sorted(quality_groups.items())
    }
    kept = tuple(
        quality
        for quality in PLAN_C_INITIAL_QUALITIES
        if counts.get(quality, 0) >= minimum_group_count
    )
    body = {
        "schema_version": 1,
        "vocabulary_version": "plan-c-v1",
        "source_corpus_role": "real-gold",
        "source_split": "train",
        "source_split_sha256": train_manifest["split_sha256"],
        "minimum_group_count": minimum_group_count,
        "quality_group_counts": counts,
        "root_labels": [*PITCH_NAMES, "N", "X"],
        "quality_labels": [*kept, "N", "X"],
        "bass_labels": [*BASS_INTERVALS, "N", "X"],
        "mapped_to_x": sorted(set(SUPPORTED_QUALITIES) - set(kept)),
    }
    return {**body, "vocabulary_sha256": canonical_sha256(body)}


def map_to_frozen_vocabulary(
    chord: CanonicalChord, vocabulary: ChordVocabulary
) -> CanonicalChord:
    if chord.root in {"N", "X"}:
        return chord
    if chord.quality not in vocabulary.quality_labels:
        return CanonicalChord(
            "X",
            "X",
            "X",
            f"plan-c-unsupported-quality:{chord.quality}",
        )
    return chord


def _validated_real_gold_train(
    manifest: Mapping[str, Any],
) -> Sequence[Mapping[str, Any]]:
    if not isinstance(manifest, Mapping):
        raise ValueError("vocabulary manifest must be an object")
    if manifest.get("split") != "train":
        raise PermissionError("vocabulary may read only the frozen train split")
    if manifest.get("corpus_role") != "real-gold":
        raise ValueError("vocabulary train manifest must contain real-gold tracks")
    split_sha256 = manifest.get("split_sha256")
    if not isinstance(split_sha256, str) or len(split_sha256) != 64:
        raise ValueError("vocabulary train split SHA-256 is invalid")
    tracks = manifest.get("tracks")
    if not isinstance(tracks, Sequence) or isinstance(tracks, (str, bytes)) or not tracks:
        raise ValueError("vocabulary train manifest must contain tracks")
    for track in tracks:
        if not isinstance(track, Mapping):
            raise ValueError("vocabulary train tracks must be objects")
        if any(
            not isinstance(track.get(field), str) or not track[field].strip()
            for field in ("dataset_id", "cover_group_id")
        ):
            raise ValueError("vocabulary train track identifiers are invalid")
    return tracks
