from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from museecho_ml.artifacts import canonical_sha256
from museecho_ml.data.registry import DatasetRegistry

_SPLITS = ("train", "calibration", "validation", "test")
_SPECIAL_QUALITIES = {"N", "X"}


def evaluate_data_gates(
    registry: DatasetRegistry,
    manifests: Mapping[str, Mapping[str, Any]],
    split_audit: Mapping[str, Any],
    *,
    minimum_works: int = 500,
    minimum_seconds: float = 80 * 3600,
    minimum_quality_works: int = 20,
    production_scale_exclusions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    _validate_thresholds(minimum_works, minimum_seconds, minimum_quality_works)
    tracks = _validated_real_gold_tracks(manifests, split_audit)
    dataset_ids = tuple(sorted({str(track["dataset_id"]) for track in tracks}))
    for dataset_id in dataset_ids:
        registry.require_training_approval(dataset_id)
    exclusions = _validated_exclusions(production_scale_exclusions, dataset_ids)
    scale_tracks = [
        track for track in tracks if track["dataset_id"] not in exclusions
    ]

    work_ids = {
        (str(track["dataset_id"]), str(track["work_id"])) for track in scale_tracks
    }
    quality_works: dict[str, set[tuple[str, str]]] = {}
    interval_count = 0
    annotated_durations: list[float] = []
    for track in scale_tracks:
        work_id = (str(track["dataset_id"]), str(track["work_id"]))
        intervals = track.get("intervals")
        if not isinstance(intervals, list):
            raise ValueError("G1 real-gold tracks must contain interval lists")
        for interval in intervals:
            if not isinstance(interval, Mapping):
                raise ValueError("G1 real-gold intervals must be objects")
            quality = interval.get("quality")
            start = interval.get("start_seconds")
            end = interval.get("end_seconds")
            if (
                not isinstance(quality, str)
                or not quality
                or isinstance(start, bool)
                or isinstance(end, bool)
                or not isinstance(start, (int, float))
                or not isinstance(end, (int, float))
                or not math.isfinite(float(start))
                or not math.isfinite(float(end))
                or float(start) < 0
                or float(end) <= float(start)
            ):
                raise ValueError("G1 real-gold intervals contain invalid labels or bounds")
            interval_count += 1
            annotated_durations.append(float(end) - float(start))
            quality_works.setdefault(quality, set()).add(work_id)

    annotated_seconds = round(math.fsum(annotated_durations), 6)
    quality_work_counts = {
        quality: len(works) for quality, works in sorted(quality_works.items())
    }
    under_supported = {
        quality: count
        for quality, count in quality_work_counts.items()
        if quality not in _SPECIAL_QUALITIES and count < minimum_quality_works
    }
    reason_codes: list[str] = []
    if len(work_ids) < minimum_works:
        reason_codes.append("real-gold-work-count-below-target")
    if annotated_seconds < minimum_seconds:
        reason_codes.append("real-gold-duration-below-target")
    if under_supported:
        reason_codes.append("published-quality-work-count-below-target")

    return {
        "schema_version": 1,
        "gate_version": "plan-c-g1-v1",
        "g1a": {
            "status": "passed",
            "dataset_ids": list(dataset_ids),
            "split_sha256": split_audit["split_sha256"],
            "split_audit_sha256": canonical_sha256(split_audit),
            "reason_codes": [],
        },
        "g1b": {
            "status": "passed" if not reason_codes else "not-met",
            "observed": {
                "work_count": len(work_ids),
                "annotated_seconds": annotated_seconds,
                "annotated_hours": round(annotated_seconds / 3600, 6),
                "interval_count": interval_count,
                "quality_work_counts": quality_work_counts,
            },
            "required": {
                "work_count": minimum_works,
                "annotated_seconds": float(minimum_seconds),
                "annotated_hours": round(float(minimum_seconds) / 3600, 6),
                "minimum_quality_work_count": minimum_quality_works,
            },
            "under_supported_qualities": under_supported,
            "excluded_datasets": exclusions,
            "reason_codes": reason_codes,
        },
    }


def _validate_thresholds(
    minimum_works: int, minimum_seconds: float, minimum_quality_works: int
) -> None:
    if type(minimum_works) is not int or minimum_works <= 0:
        raise ValueError("G1 minimum works must be a positive integer")
    if (
        isinstance(minimum_seconds, bool)
        or not isinstance(minimum_seconds, (int, float))
        or not math.isfinite(float(minimum_seconds))
        or minimum_seconds <= 0
    ):
        raise ValueError("G1 minimum seconds must be finite and positive")
    if type(minimum_quality_works) is not int or minimum_quality_works <= 0:
        raise ValueError("G1 minimum quality works must be a positive integer")


def _validated_exclusions(
    value: Mapping[str, str] | None, dataset_ids: Sequence[str]
) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or any(
        not isinstance(dataset_id, str)
        or dataset_id not in dataset_ids
        or not isinstance(reason, str)
        or not reason.strip()
        for dataset_id, reason in value.items()
    ):
        raise ValueError("G1 production-scale exclusions must name audited datasets and reasons")
    if len(value) == len(dataset_ids):
        raise ValueError("G1 production-scale exclusions cannot remove every real-gold dataset")
    return dict(sorted(value.items()))


def _validated_real_gold_tracks(
    manifests: Mapping[str, Mapping[str, Any]], split_audit: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    if set(manifests) != set(_SPLITS):
        raise ValueError("G1 requires exactly train, calibration, validation and test manifests")
    if not isinstance(split_audit, Mapping) or split_audit.get("schema_version") != 1:
        raise ValueError("G1 split audit schema_version must be 1")
    near_duplicates = split_audit.get("near_duplicate_audit")
    if not isinstance(near_duplicates, Mapping) or near_duplicates.get("status") != "passed":
        raise ValueError("G1 near-duplicate audit must have passed")
    split_sha256 = split_audit.get("split_sha256")
    manifest_hashes = split_audit.get("split_manifest_sha256s")
    if not isinstance(split_sha256, str) or len(split_sha256) != 64:
        raise ValueError("G1 split audit SHA-256 is invalid")
    if not isinstance(manifest_hashes, Mapping) or set(manifest_hashes) != set(_SPLITS):
        raise ValueError("G1 split audit manifest hashes are incomplete")

    all_tracks: list[Mapping[str, Any]] = []
    track_splits: dict[tuple[str, str], str] = {}
    work_splits: dict[tuple[str, str], str] = {}
    cover_splits: dict[tuple[str, str], str] = {}
    for split in _SPLITS:
        manifest = manifests[split]
        if not isinstance(manifest, Mapping):
            raise ValueError(f"G1 {split} manifest must be an object")
        if manifest.get("split") != split:
            raise ValueError(f"G1 {split} manifest split identity does not match")
        if manifest.get("corpus_role") != "real-gold":
            raise ValueError(f"G1 {split} manifest must contain real-gold tracks")
        if manifest.get("split_sha256") != split_sha256:
            raise ValueError(f"G1 {split} manifest uses a different frozen split")
        if canonical_sha256(manifest) != manifest_hashes[split]:
            raise ValueError(f"G1 {split} manifest SHA-256 does not match its audit")
        tracks = manifest.get("tracks")
        if not isinstance(tracks, Sequence) or isinstance(tracks, (str, bytes)) or not tracks:
            raise ValueError(f"G1 {split} manifest must contain tracks")
        for track in tracks:
            if not isinstance(track, Mapping):
                raise ValueError(f"G1 {split} tracks must be objects")
            identifiers = tuple(
                track.get(field)
                for field in ("dataset_id", "track_id", "work_id", "cover_group_id")
            )
            if any(not isinstance(value, str) or not value.strip() for value in identifiers):
                raise ValueError(f"G1 {split} track identifiers must be non-empty strings")
            dataset_id, track_id, work_id, cover_group_id = identifiers
            _claim_split(
                track_splits,
                (dataset_id, track_id),
                split,
                "track appears in multiple splits",
            )
            _claim_split(
                work_splits,
                (dataset_id, work_id),
                split,
                "work appears in multiple splits",
            )
            _claim_split(
                cover_splits,
                (dataset_id, cover_group_id),
                split,
                "cover group appears in multiple splits",
            )
            all_tracks.append(track)
    return all_tracks


def _claim_split(
    assignments: dict[tuple[str, str], str],
    identifier: tuple[str, str],
    split: str,
    message: str,
) -> None:
    previous = assignments.setdefault(identifier, split)
    if previous != split:
        raise ValueError(message)
