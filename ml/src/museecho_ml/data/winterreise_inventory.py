from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from museecho_ml.data.adapters.winterreise import (
    WinterreiseAdapter,
    discover_winterreise_sources,
)
from museecho_ml.data.inventory import build_inventory, build_manifest, manifest_sha256
from museecho_ml.data.registry import DatasetRegistry


def generate_winterreise_inventory(
    dataset_root: Path, registry: DatasetRegistry
) -> tuple[dict[str, Any], dict[str, Any]]:
    record = registry.require_training_approval("schubert-winterreise")
    sources = discover_winterreise_sources(dataset_root)
    adapter = WinterreiseAdapter(dataset_id=record.dataset_id)
    tracks = tuple(adapter.adapt(source, dataset_root) for source in sources)

    manifest = build_manifest(tracks, dataset_root)
    manifest.update(
        {
            "dataset_version": record.version,
            "source_url": record.source_url,
            "annotation_license": record.annotation_license,
            "audio_license": record.audio_license,
            "citation": record.citation,
            "reviewed_at": record.reviewed_at,
            "review_evidence": list(record.review_evidence),
        }
    )
    report = build_inventory(tracks, dataset_root)
    report["dataset_version"] = record.version
    report["manifest_sha256"] = manifest_sha256(manifest)
    return manifest, report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the licensed Schubert Winterreise training manifest and inventory"
    )
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    args = parser.parse_args()

    registry = DatasetRegistry.load(args.registry)
    manifest, report = generate_winterreise_inventory(args.dataset_root, registry)
    _write_json(args.manifest_output, manifest)
    _write_json(args.report_output, report)
    print(
        json.dumps(
            {
                "track_count": report["track_count"],
                "work_count": report["work_count"],
                "total_audio_seconds": report["total_audio_seconds"],
                "manifest_sha256": report["manifest_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


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
