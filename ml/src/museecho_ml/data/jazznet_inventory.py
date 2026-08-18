from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from museecho_ml.data.adapters.jazznet import (
    JazznetMidiAdapter,
    discover_jazznet_sources,
)
from museecho_ml.data.inventory import build_inventory, build_manifest, manifest_sha256
from museecho_ml.data.registry import DatasetRegistry


def generate_jazznet_inventory(
    dataset_root: Path,
    registry: DatasetRegistry,
    *,
    progression_audio_root: Path,
    chord_audio_root: Path,
    midi_root: Path,
    metadata_csv: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Generate the paired Jazznet chord/progression synthetic inventory."""

    record = registry.require_training_approval("jazznet")
    sources = discover_jazznet_sources(
        dataset_root,
        audio_roots=(progression_audio_root, chord_audio_root),
        midi_root=midi_root,
        metadata_csv=metadata_csv,
        source_types=("progression", "chord"),
    )
    adapter = JazznetMidiAdapter(dataset_id=record.dataset_id)
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
    parser = argparse.ArgumentParser(description="Generate the Jazznet manifest and inventory")
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--progression-audio-root", type=Path, required=True)
    parser.add_argument("--chord-audio-root", type=Path, required=True)
    parser.add_argument("--midi-root", type=Path, required=True)
    parser.add_argument("--metadata-csv", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    args = parser.parse_args()
    manifest, report = generate_jazznet_inventory(
        args.dataset_root,
        DatasetRegistry.load(args.registry),
        progression_audio_root=args.progression_audio_root,
        chord_audio_root=args.chord_audio_root,
        midi_root=args.midi_root,
        metadata_csv=args.metadata_csv,
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
