from __future__ import annotations

import hashlib
import json
import math
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
