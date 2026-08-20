from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

_SPLIT_NAMES = ("train", "calibration", "validation", "test")


class SplitAuditRequired(ValueError):
    pass


@dataclass(frozen=True)
class SplitPolicy:
    train: float = 0.7
    calibration: float = 0.1
    validation: float = 0.1
    test: float = 0.1
    artist_disjoint: bool = False
    near_duplicate_threshold: float = 0.8

    def __post_init__(self) -> None:
        ratios = (self.train, self.calibration, self.validation, self.test)
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0
            for value in ratios
        ) or not math.isclose(sum(ratios), 1.0, abs_tol=1e-9):
            raise ValueError("split ratios must be positive and sum to one")
        if type(self.artist_disjoint) is not bool:
            raise ValueError("artist_disjoint must be boolean")
        if (
            isinstance(self.near_duplicate_threshold, bool)
            or not isinstance(self.near_duplicate_threshold, (int, float))
            or not 0 < self.near_duplicate_threshold <= 1
        ):
            raise ValueError("near_duplicate_threshold must be within (0, 1]")


def build_split(
    manifest: dict[str, Any], policy: SplitPolicy, *, seed: int
) -> dict[str, Any]:
    if type(seed) is not int:
        raise ValueError("split seed must be an integer")
    raw_tracks = manifest.get("tracks") if isinstance(manifest, dict) else None
    if not isinstance(raw_tracks, list) or not raw_tracks:
        raise ValueError("split manifest must contain tracks")
    tracks = [_validated_track(track) for track in raw_tracks]
    track_ids = [track["track_id"] for track in tracks]
    if len(set(track_ids)) != len(track_ids):
        raise ValueError("split track identifiers must be unique")
    _require_exact_collision_audit(tracks)

    cover_groups = sorted({track["cover_group_id"] for track in tracks})
    parent = {group: group for group in cover_groups}

    def find(group: str) -> str:
        while parent[group] != group:
            parent[group] = parent[parent[group]]
            group = parent[group]
        return group

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    first_group_by_work: dict[str, str] = {}
    for track in tracks:
        work = track["work_id"]
        assert isinstance(work, str)
        first = first_group_by_work.setdefault(work, track["cover_group_id"])
        union(first, track["cover_group_id"])

    if policy.artist_disjoint:
        first_group_by_artist: dict[str, str] = {}
        for track in tracks:
            artist = track["artist_id"]
            if artist is None:
                continue
            first = first_group_by_artist.setdefault(artist, track["cover_group_id"])
            union(first, track["cover_group_id"])

    components: dict[str, list[str]] = {}
    for group in cover_groups:
        components.setdefault(find(group), []).append(group)
    ordered_components = sorted(
        components.values(),
        key=lambda groups: hashlib.sha256(
            f"{seed}\0{','.join(sorted(groups))}".encode()
        ).hexdigest(),
    )
    component_counts = _allocate_counts(len(ordered_components), policy)
    group_assignment: dict[str, str] = {}
    cursor = 0
    for split_name in _SPLIT_NAMES:
        count = component_counts[split_name]
        for groups in ordered_components[cursor : cursor + count]:
            for group in groups:
                group_assignment[group] = split_name
        cursor += count

    assignments = {
        track["track_id"]: group_assignment[track["cover_group_id"]]
        for track in sorted(tracks, key=lambda item: item["track_id"])
    }
    splits = {
        split_name: sorted(
            track_id for track_id, assigned in assignments.items() if assigned == split_name
        )
        for split_name in _SPLIT_NAMES
    }
    serialized_policy = asdict(policy)
    policy_payload = {
        "ratios": {name: serialized_policy[name] for name in _SPLIT_NAMES},
        "artist_disjoint": policy.artist_disjoint,
        "near_duplicate_threshold": policy.near_duplicate_threshold,
        "seed": seed,
    }
    result: dict[str, Any] = {
        "schema_version": 1,
        "seed": seed,
        "policy_sha256": _sha256(policy_payload),
        "group_count": len(ordered_components),
        "assignments": assignments,
        "splits": splits,
    }
    result["split_sha256"] = _sha256(result)
    return result


def freeze_real_gold_splits(
    manifests: Sequence[dict[str, Any]], policy: SplitPolicy, *, seed: int
) -> dict[str, Any]:
    """Combine approved real-gold manifests into deterministic frozen split manifests."""

    if not manifests:
        raise ValueError("at least one real-gold manifest is required")
    ordered_manifests: list[tuple[str, dict[str, Any]]] = []
    for manifest in manifests:
        if not isinstance(manifest, dict) or manifest.get("corpus_role") != "real-gold":
            raise ValueError("frozen evaluation splits require real-gold manifests")
        dataset_id = manifest.get("dataset_id")
        tracks = manifest.get("tracks")
        if not isinstance(dataset_id, str) or not dataset_id.strip():
            raise ValueError("real-gold manifest dataset_id must be a non-empty string")
        if not isinstance(tracks, list) or not tracks:
            raise ValueError("real-gold manifest must contain tracks")
        ordered_manifests.append((dataset_id, manifest))
    ordered_manifests.sort(key=lambda item: item[0])
    dataset_ids = [dataset_id for dataset_id, _ in ordered_manifests]
    if len(set(dataset_ids)) != len(dataset_ids):
        raise ValueError("real-gold manifest dataset identifiers must be unique")

    combined_tracks: list[dict[str, Any]] = []
    source_hashes: dict[str, str] = {}
    for dataset_id, manifest in ordered_manifests:
        source_hashes[dataset_id] = _sha256(manifest)
        for raw_track in manifest["tracks"]:
            if not isinstance(raw_track, dict):
                raise ValueError("real-gold manifest tracks must be objects")
            track = dict(raw_track)
            source_track_id = track.get("track_id")
            work_id = track.get("work_id")
            cover_group_id = track.get("cover_group_id")
            artist_id = track.get("artist_id")
            if any(
                not isinstance(value, str) or not value.strip()
                for value in (source_track_id, work_id, cover_group_id)
            ):
                raise ValueError("real-gold track identifiers must be non-empty strings")
            track.update(
                {
                    "dataset_id": dataset_id,
                    "source_track_id": source_track_id,
                    "track_id": f"{dataset_id}:{source_track_id}",
                    "work_id": f"{dataset_id}:{work_id}",
                    "cover_group_id": f"{dataset_id}:{cover_group_id}",
                    "artist_id": (
                        f"{dataset_id}:{artist_id}" if artist_id is not None else None
                    ),
                }
            )
            combined_tracks.append(track)
    combined_tracks.sort(key=lambda track: track["track_id"])
    combined_manifest = {
        "schema_version": 1,
        "dataset_id": "real-gold-combined",
        "corpus_role": "real-gold",
        "tracks": combined_tracks,
    }
    split = build_split(combined_manifest, policy, seed=seed)
    frozen_manifests: dict[str, dict[str, Any]] = {}
    for split_name in _SPLIT_NAMES:
        assigned = set(split["splits"][split_name])
        frozen_manifests[split_name] = {
            "schema_version": 1,
            "dataset_id": "real-gold-combined",
            "corpus_role": "real-gold",
            "split": split_name,
            "split_sha256": split["split_sha256"],
            "policy_sha256": split["policy_sha256"],
            "source_manifest_sha256s": source_hashes,
            "tracks": [
                track for track in combined_tracks if track["track_id"] in assigned
            ],
        }
    return {
        "audit": {
            "schema_version": 1,
            "source_dataset_ids": dataset_ids,
            "source_manifest_sha256s": source_hashes,
            "combined_manifest_sha256": _sha256(combined_manifest),
            "policy_sha256": split["policy_sha256"],
            "split_sha256": split["split_sha256"],
            "group_count": split["group_count"],
            "split_track_counts": {
                name: len(split["splits"][name]) for name in _SPLIT_NAMES
            },
            "splits": {
                name: _split_statistics(frozen_manifests[name]["tracks"])
                for name in _SPLIT_NAMES
            },
        },
        "manifests": frozen_manifests,
    }


def _split_statistics(tracks: list[dict[str, Any]]) -> dict[str, Any]:
    quality_intervals: dict[str, int] = {}
    quality_durations: dict[str, float] = {}
    quality_works: dict[str, set[str]] = {}
    total_annotated_seconds = 0.0
    for track in tracks:
        work_id = track["work_id"]
        intervals = track.get("intervals")
        if not isinstance(intervals, list):
            raise ValueError("frozen split tracks must contain intervals")
        for interval in intervals:
            if not isinstance(interval, dict):
                raise ValueError("frozen split intervals must be objects")
            quality = interval.get("quality")
            start = interval.get("start_seconds")
            end = interval.get("end_seconds")
            if (
                not isinstance(quality, str)
                or isinstance(start, bool)
                or isinstance(end, bool)
                or not isinstance(start, (int, float))
                or not isinstance(end, (int, float))
                or end <= start
            ):
                raise ValueError("frozen split intervals must contain valid labels and times")
            duration = end - start
            total_annotated_seconds += duration
            quality_intervals[quality] = quality_intervals.get(quality, 0) + 1
            quality_durations[quality] = quality_durations.get(quality, 0.0) + duration
            quality_works.setdefault(quality, set()).add(work_id)
    dataset_track_counts: dict[str, int] = {}
    for track in tracks:
        dataset_id = track["dataset_id"]
        dataset_track_counts[dataset_id] = dataset_track_counts.get(dataset_id, 0) + 1
    return {
        "track_count": len(tracks),
        "group_count": len({track["cover_group_id"] for track in tracks}),
        "total_audio_seconds": round(
            sum(float(track["duration_seconds"]) for track in tracks), 6
        ),
        "total_annotated_seconds": round(total_annotated_seconds, 6),
        "dataset_track_counts": dict(sorted(dataset_track_counts.items())),
        "qualities": {
            quality: {
                "interval_count": quality_intervals[quality],
                "duration_seconds": round(quality_durations[quality], 6),
                "work_count": len(quality_works[quality]),
            }
            for quality in sorted(quality_intervals)
        },
    }


def _validated_track(value: Any) -> dict[str, str | None]:
    if not isinstance(value, dict):
        raise ValueError("split track must be an object")
    required = ("track_id", "work_id", "cover_group_id", "audio_sha256")
    if any(not isinstance(value.get(field), str) or not value[field].strip() for field in required):
        raise ValueError("split track identifiers and audio hash must be non-empty strings")
    artist = value.get("artist_id")
    if artist is not None and (not isinstance(artist, str) or not artist.strip()):
        raise ValueError("split artist identifier must be null or a non-empty string")
    return {
        "track_id": value["track_id"],
        "work_id": value["work_id"],
        "cover_group_id": value["cover_group_id"],
        "artist_id": artist,
        "audio_sha256": value["audio_sha256"],
    }


def _require_exact_collision_audit(tracks: list[dict[str, str | None]]) -> None:
    covers_by_hash: dict[str, set[str]] = {}
    for track in tracks:
        audio_hash = track["audio_sha256"]
        cover_group = track["cover_group_id"]
        assert isinstance(audio_hash, str) and isinstance(cover_group, str)
        covers_by_hash.setdefault(audio_hash, set()).add(cover_group)
    collisions = [
        audio_hash for audio_hash, groups in covers_by_hash.items() if len(groups) > 1
    ]
    if collisions:
        raise SplitAuditRequired(
            f"audio hash appears in multiple cover groups: {sorted(collisions)[0]}"
        )


def _allocate_counts(total: int, policy: SplitPolicy) -> dict[str, int]:
    ratios = {
        "train": policy.train,
        "calibration": policy.calibration,
        "validation": policy.validation,
        "test": policy.test,
    }
    raw = {name: total * ratio for name, ratio in ratios.items()}
    counts = {name: math.floor(value) for name, value in raw.items()}
    remainder = total - sum(counts.values())
    ranked = sorted(
        _SPLIT_NAMES,
        key=lambda name: (-(raw[name] - counts[name]), _SPLIT_NAMES.index(name)),
    )
    for name in ranked[:remainder]:
        counts[name] += 1
    return counts


def _sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
