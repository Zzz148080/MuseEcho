from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class CorpusRole(StrEnum):
    REAL_GOLD = "real-gold"
    SYNTHETIC_SUPERVISED = "synthetic-supervised"
    WEAK_LABEL_VALIDATION = "weak-label-validation"


@dataclass(frozen=True)
class RouteDecision:
    route: str
    usable_synthetic_seconds: float
    threshold_seconds: float
    included_datasets: tuple[str, ...]
    excluded_datasets: tuple[str, ...]


def decide_training_route(
    inventories: list[dict[str, Any]], *, threshold_hours: float = 60.0
) -> RouteDecision:
    """Choose A or B from audited synthetic supervision, never from gold hours."""

    if (
        isinstance(threshold_hours, bool)
        or not isinstance(threshold_hours, (int, float))
        or not math.isfinite(threshold_hours)
        or threshold_hours <= 0
    ):
        raise ValueError("training route threshold_hours must be finite and positive")
    included: list[tuple[str, float]] = []
    excluded: list[str] = []
    seen: set[str] = set()
    for inventory in inventories:
        if not isinstance(inventory, dict):
            raise ValueError("training route inventory must be an object")
        dataset_id = inventory.get("dataset_id")
        if not isinstance(dataset_id, str) or not dataset_id.strip() or dataset_id in seen:
            raise ValueError("training route dataset_id must be unique and non-empty")
        seen.add(dataset_id)
        try:
            role = CorpusRole(inventory.get("corpus_role"))
        except (TypeError, ValueError):
            raise ValueError(f"dataset {dataset_id!r} has an invalid corpus_role") from None
        seconds = inventory.get("total_annotated_seconds")
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds)
            or seconds < 0
        ):
            raise ValueError(f"dataset {dataset_id!r} has invalid annotated duration")
        if role is not CorpusRole.SYNTHETIC_SUPERVISED:
            continue
        grouping_passed = inventory.get("grouping_audit_passed") is True
        label_passed = inventory.get("label_audit_passed") is True
        if grouping_passed and label_passed:
            included.append((dataset_id, float(seconds)))
        else:
            excluded.append(dataset_id)
    usable_seconds = math.fsum(seconds for _, seconds in included)
    threshold_seconds = float(threshold_hours) * 3600
    return RouteDecision(
        route="B" if usable_seconds >= threshold_seconds else "A",
        usable_synthetic_seconds=usable_seconds,
        threshold_seconds=threshold_seconds,
        included_datasets=tuple(sorted(dataset_id for dataset_id, _ in included)),
        excluded_datasets=tuple(sorted(excluded)),
    )


def select_manifest_role(
    manifest: dict[str, Any], *, role: CorpusRole
) -> dict[str, Any]:
    """Create a role-pure manifest so synthetic tracks cannot enter real evaluation."""

    tracks = manifest.get("tracks") if isinstance(manifest, dict) else None
    if not isinstance(tracks, list) or not tracks:
        raise ValueError("course manifest must contain tracks")
    if any(not isinstance(track, dict) for track in tracks):
        raise ValueError("course manifest tracks must be objects")
    selected = [track for track in tracks if track.get("corpus_role") == role.value]
    if not selected:
        raise ValueError(f"course manifest does not contain role {role.value!r}")
    return {
        "schema_version": 1,
        "corpus_role": role.value,
        "tracks": selected,
    }
