from __future__ import annotations

import json
from pathlib import Path

from museecho_ml.data.route_freeze import freeze_training_route


def _inventory(path: Path, dataset_id: str, hours: float) -> Path:
    path.write_text(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "corpus_role": "synthetic-supervised",
                "total_annotated_seconds": hours * 3600,
                "grouping_audit_passed": True,
                "label_audit_passed": True,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_freeze_training_route_serializes_decision_evidence(tmp_path: Path) -> None:
    first = _inventory(tmp_path / "first.json", "first", 40.0)
    second = _inventory(tmp_path / "second.json", "second", 19.0)

    report = freeze_training_route([first, second])

    assert report["route"] == "A"
    assert report["usable_synthetic_hours"] == 59.0
    assert report["included_datasets"] == ["first", "second"]
    assert report["inventory_paths"] == [str(first.resolve()), str(second.resolve())]
