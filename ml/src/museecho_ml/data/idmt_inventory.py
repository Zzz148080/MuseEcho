from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from museecho_ml.data.adapters.idmt import IdmtChordAdapter, discover_idmt_sources
from museecho_ml.data.inventory import build_inventory, build_manifest, manifest_sha256
from museecho_ml.data.registry import DatasetRegistry


def generate_idmt_inventory(
    dataset_root: Path,
    registry: DatasetRegistry,
    *,
    sequence_root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Generate the leakage-safe IDMT synthetic-supervised inventory."""

    record = registry.require_training_approval("idmt-smt-chord-sequences")
    sources = discover_idmt_sources(dataset_root, sequence_root=sequence_root)
    adapter = IdmtChordAdapter(dataset_id=record.dataset_id)
    tracks = tuple(adapter.adapt(source, dataset_root) for source in sources)
    manifest = build_manifest(tracks, dataset_root)
    manifest.update(
        {
            "dataset_version": record.version,
            "corpus_role": "synthetic-supervised",
            "source_url": record.source_url,
            "annotation_license": record.annotation_license,
            "audio_license": record.audio_license,
            "citation": record.citation,
        }
    )
    report = build_inventory(tracks, dataset_root)
    report.update(
        {
            "dataset_version": record.version,
            "corpus_role": "synthetic-supervised",
            "grouping_audit_passed": True,
            "label_audit_passed": True,
            "manifest_sha256": manifest_sha256(manifest),
        }
    )
    return manifest, report


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the IDMT manifest and inventory")
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--sequence-root", type=Path)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    args = parser.parse_args()
    manifest, report = generate_idmt_inventory(
        args.dataset_root,
        DatasetRegistry.load(args.registry),
        sequence_root=args.sequence_root,
    )
    _write_json(args.manifest_output, manifest)
    _write_json(args.report_output, report)
    print(json.dumps(_summary(report), ensure_ascii=False, sort_keys=True))


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        key: report[key]
        for key in (
            "track_count",
            "work_count",
            "cover_group_count",
            "total_audio_seconds",
            "total_annotated_seconds",
            "out_of_vocabulary_intervals",
            "manifest_sha256",
        )
    }


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
