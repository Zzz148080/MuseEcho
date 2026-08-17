from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class LicenseStatus(StrEnum):
    APPROVED = "approved"
    BLOCKED = "blocked"
    NEEDS_REVIEW = "needs-review"


@dataclass(frozen=True)
class DatasetRecord:
    dataset_id: str
    name: str
    version: str
    source_url: str
    status: LicenseStatus
    annotation_license: str
    audio_license: str
    training_allowed: bool | None
    weights_distribution_allowed: bool | None
    citation: str
    reviewed_at: str | None
    review_evidence: tuple[str, ...]


@dataclass(frozen=True)
class DatasetRegistry:
    records: tuple[DatasetRecord, ...]

    @classmethod
    def load(cls, path: Path) -> DatasetRegistry:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("dataset registry must be readable strict JSON") from error
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("dataset registry schema_version must be 1")
        datasets = payload.get("datasets")
        if not isinstance(datasets, list):
            raise ValueError("dataset registry datasets must be a list")
        records = tuple(_record_from_json(item) for item in datasets)
        identifiers = [record.dataset_id for record in records]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("dataset registry dataset_id values must be unique")
        return cls(records)

    def get(self, dataset_id: str) -> DatasetRecord:
        for record in self.records:
            if record.dataset_id == dataset_id:
                return record
        raise KeyError(dataset_id)

    def require_training_approval(self, dataset_id: str) -> DatasetRecord:
        record = self.get(dataset_id)
        if record.status is not LicenseStatus.APPROVED or record.training_allowed is not True:
            raise PermissionError(f"dataset {dataset_id!r} is not approved for formal training")
        return record


def _record_from_json(value: Any) -> DatasetRecord:
    if not isinstance(value, dict):
        raise ValueError("each dataset registry item must be an object")
    required = {
        "dataset_id",
        "name",
        "version",
        "source_url",
        "status",
        "annotation_license",
        "audio_license",
        "training_allowed",
        "weights_distribution_allowed",
        "citation",
        "reviewed_at",
        "review_evidence",
    }
    if set(value) != required:
        raise ValueError("dataset registry item is missing required license fields")
    text_fields = (
        "dataset_id",
        "name",
        "version",
        "source_url",
        "annotation_license",
        "audio_license",
        "citation",
    )
    if any(not isinstance(value[field], str) or not value[field].strip() for field in text_fields):
        raise ValueError("dataset registry license text fields must be non-empty strings")
    try:
        status = LicenseStatus(value["status"])
    except (TypeError, ValueError):
        raise ValueError("dataset registry status is invalid") from None
    for field in ("training_allowed", "weights_distribution_allowed"):
        if value[field] is not None and type(value[field]) is not bool:
            raise ValueError(f"dataset registry {field} must be boolean or null")
    if value["reviewed_at"] is not None and not isinstance(value["reviewed_at"], str):
        raise ValueError("dataset registry reviewed_at must be a string or null")
    evidence = value["review_evidence"]
    if not isinstance(evidence, list) or any(
        not isinstance(item, str) or not item.strip() for item in evidence
    ):
        raise ValueError("dataset registry review_evidence must contain non-empty strings")
    if status is LicenseStatus.APPROVED and (
        value["training_allowed"] is not True or value["reviewed_at"] is None or not evidence
    ):
        raise ValueError("approved dataset license must include approval evidence")
    return DatasetRecord(
        dataset_id=value["dataset_id"],
        name=value["name"],
        version=value["version"],
        source_url=value["source_url"],
        status=status,
        annotation_license=value["annotation_license"],
        audio_license=value["audio_license"],
        training_allowed=value["training_allowed"],
        weights_distribution_allowed=value["weights_distribution_allowed"],
        citation=value["citation"],
        reviewed_at=value["reviewed_at"],
        review_evidence=tuple(evidence),
    )
