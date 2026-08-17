from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from museecho_ml.data.manifest import AdaptedTrack
from museecho_ml.labels import SUPPORTED_QUALITIES


def build_inventory(
    tracks: Iterable[AdaptedTrack], dataset_root: Path
) -> dict[str, Any]:
    """Build a deterministic, path-safe aggregate inventory for adapted tracks."""

    root = dataset_root.resolve(strict=True)
    ordered = sorted(tracks, key=lambda track: track.source.track_id)
    if not ordered:
        raise ValueError("dataset inventory requires at least one adapted track")
    dataset_ids = {track.source.dataset_id for track in ordered}
    if len(dataset_ids) != 1:
        raise ValueError("dataset inventory cannot mix dataset identifiers")
    track_ids = [track.source.track_id for track in ordered]
    if len(set(track_ids)) != len(track_ids):
        raise ValueError("dataset inventory track identifiers must be unique")

    manifest_tracks = [_manifest_track(track, root) for track in ordered]
    manifest = {
        "schema_version": 1,
        "dataset_id": next(iter(dataset_ids)),
        "tracks": manifest_tracks,
    }
    manifest_hash = manifest_sha256(manifest)

    quality_durations: defaultdict[str, float] = defaultdict(float)
    quality_intervals: defaultdict[str, int] = defaultdict(int)
    quality_works: defaultdict[str, set[str]] = defaultdict(set)
    for track in ordered:
        for interval in track.intervals:
            quality = interval.chord.quality
            quality_durations[quality] += interval.end_seconds - interval.start_seconds
            quality_intervals[quality] += 1
            quality_works[quality].add(track.source.work_id)

    published_qualities = set(SUPPORTED_QUALITIES) | {"N", "X"} | set(quality_durations)
    qualities = {
        quality: {
            "duration_seconds": _rounded(quality_durations[quality]),
            "interval_count": quality_intervals[quality],
            "work_count": len(quality_works[quality]),
        }
        for quality in sorted(published_qualities)
    }
    total_audio_seconds = sum(track.source.duration_seconds for track in ordered)
    total_annotated_seconds = sum(
        interval.end_seconds - interval.start_seconds
        for track in ordered
        for interval in track.intervals
    )
    return {
        "schema_version": 1,
        "dataset_id": next(iter(dataset_ids)),
        "manifest_sha256": manifest_hash,
        "track_count": len(ordered),
        "work_count": len({track.source.work_id for track in ordered}),
        "cover_group_count": len({track.source.cover_group_id for track in ordered}),
        "artist_count": len(
            {track.source.artist_id for track in ordered if track.source.artist_id is not None}
        ),
        "total_audio_seconds": _rounded(total_audio_seconds),
        "total_annotated_seconds": _rounded(total_annotated_seconds),
        "unannotated_seconds": _rounded(total_audio_seconds - total_annotated_seconds),
        "total_intervals": sum(len(track.intervals) for track in ordered),
        "out_of_vocabulary_intervals": sum(
            track.conversion.out_of_vocabulary_intervals for track in ordered
        ),
        "malformed_intervals": 0,
        "clipped_intervals": sum(track.conversion.clipped_intervals for track in ordered),
        "overlapping_intervals": 0,
        "discarded_intervals": 0,
        "qualities": qualities,
        "tracks": [
            {
                "track_id": track.source.track_id,
                "work_id": track.source.work_id,
                "cover_group_id": track.source.cover_group_id,
                "artist_id": track.source.artist_id,
                "duration_seconds": _rounded(track.source.duration_seconds),
                "interval_count": len(track.intervals),
                "audio_sha256": track.audio_sha256,
                "annotation_sha256": track.annotation_sha256,
            }
            for track in ordered
        ],
    }


def build_manifest(tracks: Iterable[AdaptedTrack], dataset_root: Path) -> dict[str, Any]:
    root = dataset_root.resolve(strict=True)
    ordered = sorted(tracks, key=lambda track: track.source.track_id)
    if not ordered:
        raise ValueError("dataset manifest requires at least one adapted track")
    return {
        "schema_version": 1,
        "dataset_id": ordered[0].source.dataset_id,
        "tracks": [_manifest_track(track, root) for track in ordered],
    }


def manifest_sha256(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(manifest)).hexdigest()


def _manifest_track(track: AdaptedTrack, root: Path) -> dict[str, Any]:
    try:
        audio_path = track.source.audio_path.resolve(strict=True).relative_to(root).as_posix()
        annotation_path = (
            track.source.annotation_path.resolve(strict=True).relative_to(root).as_posix()
        )
    except (OSError, ValueError):
        raise ValueError("adapted track path must remain inside the dataset root") from None
    return {
        "track_id": track.source.track_id,
        "work_id": track.source.work_id,
        "cover_group_id": track.source.cover_group_id,
        "artist_id": track.source.artist_id,
        "audio_path": audio_path,
        "annotation_path": annotation_path,
        "duration_seconds": track.source.duration_seconds,
        "audio_sha256": track.audio_sha256,
        "annotation_sha256": track.annotation_sha256,
        "intervals": [
            {
                "start_seconds": interval.start_seconds,
                "end_seconds": interval.end_seconds,
                "root": interval.chord.root,
                "quality": interval.chord.quality,
                "bass": interval.chord.bass,
                "mapping_reason": interval.chord.mapping_reason,
            }
            for interval in track.intervals
        ],
    }


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _rounded(value: float) -> float:
    return round(value, 6)
