from __future__ import annotations

import wave
from pathlib import Path

import pytest

from museecho_ml.data.adapters.rwc import discover_rwc_sources
from museecho_ml.data.adapters.winterreise import (
    WinterreiseAdapter,
    discover_winterreise_sources,
)
from museecho_ml.data.inventory import build_inventory, manifest_sha256
from museecho_ml.data.registry import DatasetRegistry
from museecho_ml.data.rwc_inventory import generate_rwc_inventory
from museecho_ml.data.winterreise_inventory import generate_winterreise_inventory


def _write_wav(path: Path, duration_seconds: float = 2.0, sample_rate: int = 8000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame_count = round(duration_seconds * sample_rate)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"\x00\x00" * frame_count)


def _write_annotation(path: Path, first_chord: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "start;end;shorthand;extended;majmin;majmin_inv\n"
        f'0.0;1.0;"{first_chord}";"";"";""\n'
        '1.0;2.0;"C:(3,5,b7,b9)";"";"";""\n',
        encoding="utf-8",
    )


def _winterreise_fixture(root: Path) -> None:
    audio_root = root / "01_RawData" / "audio_wav"
    annotation_root = root / "02_Annotations" / "ann_audio_chord"
    for performance, chord in (("HU33", "C:maj"), ("SC06", "A:min7")):
        stem = f"Schubert_D911-01_{performance}"
        _write_wav(audio_root / f"{stem}.wav")
        _write_annotation(annotation_root / f"{stem}.csv", chord)


def _rwc_fixture(root: Path) -> tuple[Path, Path]:
    audio_root = root / "rwc-audio"
    annotations_root = root / "rwc-annotations"
    _write_wav(audio_root / "nested" / "RWC_P001.wav")
    chord_path = (
        annotations_root
        / "01_annotations_preprocessed"
        / "chords"
        / "RWC-P"
        / "RWC_P001.csv"
    )
    chord_path.parent.mkdir(parents=True, exist_ok=True)
    chord_path.write_text(
        "t_start;t_end;chord\n0.0;1.0;N\n1.0;2.0;Bb:maj7\n",
        encoding="utf-8",
    )
    (annotations_root / "metadata.csv").write_text(
        "RWCID;CollID;PieceNo;Title;Artist;duration\n"
        "RWC_P001;P;1;Fixture Song;Fixture Artist;2.0\n",
        encoding="utf-8",
    )
    return audio_root, annotations_root


def test_winterreise_discovery_pairs_only_packaged_audio_and_annotations(
    tmp_path: Path,
) -> None:
    _winterreise_fixture(tmp_path)
    annotation_root = tmp_path / "02_Annotations" / "ann_audio_chord"
    _write_annotation(annotation_root / "Schubert_D911-01_AL98.csv", "G:maj")

    sources = discover_winterreise_sources(tmp_path)

    assert [source.track_id for source in sources] == [
        "Schubert_D911-01_HU33",
        "Schubert_D911-01_SC06",
    ]
    assert {source.work_id for source in sources} == {"Schubert_D911-01"}
    assert {source.cover_group_id for source in sources} == {"Schubert_D911-01"}
    assert {source.artist_id for source in sources} == {"HU33", "SC06"}
    assert all(source.duration_seconds == 2.0 for source in sources)


def test_inventory_is_deterministic_and_reports_quality_coverage(tmp_path: Path) -> None:
    _winterreise_fixture(tmp_path)
    adapter = WinterreiseAdapter(dataset_id="schubert-winterreise")
    tracks = tuple(
        adapter.adapt(source, tmp_path) for source in discover_winterreise_sources(tmp_path)
    )

    first = build_inventory(tracks, tmp_path)
    second = build_inventory(tuple(reversed(tracks)), tmp_path)

    assert first == second
    assert first["dataset_id"] == "schubert-winterreise"
    assert first["track_count"] == 2
    assert first["work_count"] == 1
    assert first["artist_count"] == 2
    assert first["total_audio_seconds"] == 4.0
    assert first["total_annotated_seconds"] == 4.0
    assert first["unannotated_seconds"] == 0.0
    assert first["qualities"]["maj"] == {
        "duration_seconds": 1.0,
        "interval_count": 1,
        "work_count": 1,
    }
    assert first["qualities"]["min7"]["work_count"] == 1
    assert first["qualities"]["X"] == {
        "duration_seconds": 2.0,
        "interval_count": 2,
        "work_count": 1,
    }
    assert first["qualities"]["sus2"] == {
        "duration_seconds": 0.0,
        "interval_count": 0,
        "work_count": 0,
    }
    assert len(first["manifest_sha256"]) == 64


def test_winterreise_discovery_rejects_missing_paired_annotation(tmp_path: Path) -> None:
    stem = "Schubert_D911-01_HU33"
    _write_wav(tmp_path / "01_RawData" / "audio_wav" / f"{stem}.wav")

    with pytest.raises(ValueError, match="annotation"):
        discover_winterreise_sources(tmp_path)


def test_rwc_discovery_pairs_audio_annotations_and_metadata(tmp_path: Path) -> None:
    audio_root, annotations_root = _rwc_fixture(tmp_path)

    sources = discover_rwc_sources(audio_root, annotations_root)

    assert len(sources) == 1
    assert sources[0].track_id == "RWC_P001"
    assert sources[0].work_id == "RWC_P001"
    assert sources[0].cover_group_id == "RWC_P001"
    assert sources[0].artist_id == "Fixture Artist"
    assert sources[0].duration_seconds == 2.0


def test_rwc_inventory_uses_license_gate_and_official_csv(tmp_path: Path) -> None:
    audio_root, annotations_root = _rwc_fixture(tmp_path)
    registry = DatasetRegistry.load(
        Path(__file__).resolve().parents[3]
        / "docs"
        / "ml"
        / "dataset-registry.example.json"
    )

    manifest, report = generate_rwc_inventory(
        tmp_path, audio_root, annotations_root, registry
    )

    assert manifest["dataset_id"] == "rwc-popular"
    assert manifest["dataset_version"] == "2026-02-16 re-release"
    assert report["track_count"] == 1
    assert report["qualities"]["N"]["duration_seconds"] == 1.0
    assert report["qualities"]["maj7"]["duration_seconds"] == 1.0
    assert report["manifest_sha256"] == manifest_sha256(manifest)


def test_formal_winterreise_manifest_requires_registry_approval(tmp_path: Path) -> None:
    _winterreise_fixture(tmp_path)
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        """{
          "schema_version": 1,
          "datasets": [{
            "dataset_id": "schubert-winterreise",
            "name": "fixture",
            "version": "test",
            "source_url": "https://example.invalid",
            "status": "needs-review",
            "annotation_license": "needs-review",
            "audio_license": "needs-review",
            "training_allowed": null,
            "weights_distribution_allowed": null,
            "citation": "needs-review",
            "reviewed_at": null,
            "review_evidence": []
          }]
        }""",
        encoding="utf-8",
    )

    with pytest.raises(PermissionError, match="approved"):
        generate_winterreise_inventory(tmp_path, DatasetRegistry.load(registry_path))
