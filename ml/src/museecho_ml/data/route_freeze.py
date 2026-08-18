from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from museecho_ml.data.course import decide_training_route


def freeze_training_route(
    inventory_paths: list[Path], *, threshold_hours: float = 60.0
) -> dict[str, Any]:
    """Load audited inventories and serialize the deterministic A/B decision."""

    inventories = [_read_json(path) for path in inventory_paths]
    decision = decide_training_route(inventories, threshold_hours=threshold_hours)
    return {
        "schema_version": 1,
        "route": decision.route,
        "usable_synthetic_seconds": decision.usable_synthetic_seconds,
        "usable_synthetic_hours": round(decision.usable_synthetic_seconds / 3600, 6),
        "threshold_seconds": decision.threshold_seconds,
        "threshold_hours": threshold_hours,
        "included_datasets": list(decision.included_datasets),
        "excluded_datasets": list(decision.excluded_datasets),
        "inventory_paths": [str(path.resolve(strict=True)) for path in inventory_paths],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze the audited A/B training route")
    parser.add_argument("--inventory", action="append", type=Path, required=True)
    parser.add_argument("--threshold-hours", type=float, default=60.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = freeze_training_route(args.inventory, threshold_hours=args.threshold_hours)
    _write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"inventory is not readable strict JSON: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"inventory must be a JSON object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    main()
