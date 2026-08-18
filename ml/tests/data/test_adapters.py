from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path

import mido
import pytest

from museecho_ml.data.adapters.billboard import BillboardAdapter
from museecho_ml.data.adapters.guitarset import (
    GuitarSetAdapter,
    discover_guitarset_sources,
)
from museecho_ml.data.adapters.idmt import IdmtChordAdapter, discover_idmt_sources
from museecho_ml.data.adapters.isophonics import IsophonicsAdapter
from museecho_ml.data.adapters.jazznet import (
    JazznetMidiAdapter,
    discover_jazznet_sources,
)
from museecho_ml.data.adapters.rwc import RwcAdapter
from museecho_ml.data.adapters.winterreise import WinterreiseAdapter
from museecho_ml.data.manifest import LocalTrackSource
from museecho_ml.data.registry import DatasetRegistry, LicenseStatus

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _write_wav(path: Path, duration_seconds: float = 2.0, sample_rate: int = 8000) -> None:
    frame_count = round(duration_seconds * sample_rate)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"\x00\x00" * frame_count)


def _source(
    root: Path, annotation_name: str, *, duration_seconds: float = 2.0
) -> LocalTrackSource:
    return LocalTrackSource(
        dataset_id="fixture",
        track_id="track-001",
        work_id="work-001",
        cover_group_id="cover-001",
        artist_id="artist-001",
        audio_path=root / "track.wav",
        annotation_path=root / annotation_name,
        duration_seconds=duration_seconds,
    )


def test_registry_requires_explicit_license_review_fields(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "datasets": [
                    {
                        "dataset_id": "incomplete",
                        "name": "Incomplete",
                        "version": "1",
                        "source_url": "https://example.invalid",
                        "status": "approved",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="license"):
        DatasetRegistry.load(registry_path)


def test_needs_review_dataset_cannot_enter_formal_training(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "datasets": [
                    {
                        "dataset_id": "candidate",
                        "name": "Candidate",
                        "version": "unknown",
                        "source_url": "https://example.invalid",
                        "status": "needs-review",
                        "annotation_license": "needs-review",
                        "audio_license": "needs-review",
                        "training_allowed": None,
                        "weights_distribution_allowed": None,
                        "citation": "needs-review",
                        "reviewed_at": None,
                        "review_evidence": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    registry = DatasetRegistry.load(registry_path)

    assert registry.get("candidate").status is LicenseStatus.NEEDS_REVIEW
    with pytest.raises(PermissionError, match="approved"):
        registry.require_training_approval("candidate")


def test_shipped_candidate_registry_only_approves_evidenced_training_data() -> None:
    registry = DatasetRegistry.load(
        REPOSITORY_ROOT / "docs" / "ml" / "dataset-registry.example.json"
    )

    assert {record.dataset_id for record in registry.records} == {
        "babyslakh",
        "guitarset",
        "idmt-smt-chord-sequences",
        "isophonics",
        "jazznet",
        "mcgill-billboard",
        "rwc-popular",
        "schubert-winterreise",
    }
    assert {
        record.dataset_id for record in registry.records if record.status is LicenseStatus.APPROVED
    } == {
        "babyslakh",
        "guitarset",
        "idmt-smt-chord-sequences",
        "jazznet",
        "rwc-popular",
        "schubert-winterreise",
    }
    assert registry.require_training_approval("babyslakh").training_allowed is True
    assert registry.require_training_approval("guitarset").training_allowed is True
    assert (
        registry.require_training_approval("idmt-smt-chord-sequences").training_allowed
        is True
    )
    assert registry.require_training_approval("jazznet").training_allowed is True
    assert registry.require_training_approval("rwc-popular").training_allowed is True
    assert registry.require_training_approval("schubert-winterreise").training_allowed is True
    for dataset_id in ("isophonics", "mcgill-billboard"):
        with pytest.raises(PermissionError, match="approved"):
            registry.require_training_approval(dataset_id)


@pytest.mark.parametrize("adapter_type", [IsophonicsAdapter, BillboardAdapter, RwcAdapter])
def test_lab_adapters_canonicalize_without_copying_audio(
    adapter_type: type[IsophonicsAdapter] | type[BillboardAdapter] | type[RwcAdapter],
    tmp_path: Path,
) -> None:
    audio = tmp_path / "track.wav"
    annotation = tmp_path / "track.lab"
    _write_wav(audio)
    annotation.write_text(
        "0.0 0.5 C:maj\n0.5 1.0 Bbm7/Db\n1.0 1.5 C:aug\n1.5 2.0 N\n", encoding="utf-8"
    )
    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in tmp_path.iterdir()
    }

    result = adapter_type(dataset_id="fixture").adapt(_source(tmp_path, "track.lab"), tmp_path)

    assert [
        (item.chord.display_symbol, item.start_seconds, item.end_seconds)
        for item in result.intervals
    ] == [
        ("C", 0.0, 0.5),
        ("A#m7/C#", 0.5, 1.0),
        ("X", 1.0, 1.5),
        ("N", 1.5, 2.0),
    ]
    assert result.conversion.total_intervals == 4
    assert result.conversion.out_of_vocabulary_intervals == 1
    assert result.audio_sha256 == before["track.wav"]
    assert result.annotation_sha256 == before["track.lab"]
    after = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in tmp_path.iterdir()
    }
    assert after == before


def test_winterreise_csv_adapter_uses_named_columns(tmp_path: Path) -> None:
    _write_wav(tmp_path / "track.wav")
    (tmp_path / "track.csv").write_text(
        "start,end,chord\n0.0,1.0,F:maj7\n1.0,2.0,G:7\n",
        encoding="utf-8",
    )

    result = WinterreiseAdapter(dataset_id="fixture").adapt(
        _source(tmp_path, "track.csv"), tmp_path
    )

    assert [item.chord.display_symbol for item in result.intervals] == ["Fmaj7", "G7"]


def test_winterreise_adapter_reads_official_semicolon_shorthand_format(
    tmp_path: Path,
) -> None:
    _write_wav(tmp_path / "track.wav")
    (tmp_path / "track.csv").write_text(
        "start;end;shorthand;extended;majmin;majmin_inv\n"
        '0.0;1.0;"F:maj7";"F:(3,5,7)";"F:maj";"F:maj"\n'
        '1.0;2.0;"G:7/B";"G:(3,5,b7)/B";"G:maj";"G:maj/B"\n',
        encoding="utf-8",
    )

    result = WinterreiseAdapter(dataset_id="fixture").adapt(
        _source(tmp_path, "track.csv"), tmp_path
    )

    assert [item.chord.display_symbol for item in result.intervals] == ["Fmaj7", "G7/B"]


def test_rwc_adapter_reads_official_semicolon_time_columns(tmp_path: Path) -> None:
    _write_wav(tmp_path / "track.wav")
    (tmp_path / "track.csv").write_text(
        "t_start;t_end;chord\n"
        "0.0;1.0;Ab:min\n"
        "1.0;2.0;Gb:maj6\n",
        encoding="utf-8",
    )

    result = RwcAdapter(dataset_id="fixture").adapt(
        _source(tmp_path, "track.csv"), tmp_path
    )

    assert [item.chord.display_symbol for item in result.intervals] == ["G#m", "X"]


def test_guitarset_adapter_uses_verified_performed_chords(tmp_path: Path) -> None:
    _write_wav(tmp_path / "track.wav")
    (tmp_path / "track.jams").write_text(
        json.dumps(
            {
                "annotations": [
                    {
                        "namespace": "chord",
                        "annotation_metadata": {"data_source": "lead sheet"},
                        "data": {
                            "time": [0.0, 1.0],
                            "duration": [1.0, 1.0],
                            "value": ["C:maj", "G:7"],
                        },
                    },
                    {
                        "namespace": "chord",
                        "annotation_metadata": {
                            "data_source": (
                                "Semi-automatic chord transcription with manual verification"
                            )
                        },
                        "data": [
                            {
                                "time": 0.0,
                                "duration": 1.0,
                                "value": "C:min7",
                                "confidence": None,
                            },
                            {
                                "time": 1.0,
                                "duration": 1.0,
                                "value": "G:sus2(7)/1",
                                "confidence": None,
                            },
                        ],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = GuitarSetAdapter(dataset_id="fixture").adapt(
        _source(tmp_path, "track.jams"), tmp_path
    )

    assert [item.chord.display_symbol for item in result.intervals] == ["Cm7", "X"]
    assert result.conversion.out_of_vocabulary_intervals == 1


def test_guitarset_discovery_groups_players_and_versions_by_lead_sheet(
    tmp_path: Path,
) -> None:
    annotations = tmp_path / "annotations"
    audio = tmp_path / "audio_mono-mic"
    annotations.mkdir()
    audio.mkdir()
    for stem in ("00_BN1-129-Eb_comp", "01_BN1-129-Eb_solo"):
        _write_wav(audio / f"{stem}_mic.wav")
        (annotations / f"{stem}.jams").write_text(
            json.dumps(
                {
                    "annotations": [
                        {
                            "namespace": "chord",
                            "annotation_metadata": {
                                "data_source": (
                                    "Semi-automatic chord transcription with manual verification"
                                )
                            },
                            "data": {
                                "time": [0.0],
                                "duration": [2.0],
                                "value": ["D#:maj"],
                            },
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    sources = discover_guitarset_sources(tmp_path)

    assert len(sources) == 2
    assert {source.work_id for source in sources} == {"BN1-129-Eb"}
    assert {source.cover_group_id for source in sources} == {"BN1-129-Eb"}
    assert {source.artist_id for source in sources} == {"00", "01"}


def test_guitarset_discovery_accepts_separate_roots_inside_dataset(
    tmp_path: Path,
) -> None:
    annotations = tmp_path / "annotation-package" / "annotations"
    audio = tmp_path / "audio-package"
    annotations.mkdir(parents=True)
    audio.mkdir()
    stem = "00_BN1-129-Eb_comp"
    _write_wav(audio / f"{stem}_mic.wav")
    (annotations / f"{stem}.jams").write_text("{}", encoding="utf-8")

    sources = discover_guitarset_sources(
        tmp_path, annotation_root=annotations, audio_root=audio
    )

    assert [source.track_id for source in sources] == [stem]


def test_idmt_adapter_derives_aligned_intervals_from_json_metadata(
    tmp_path: Path,
) -> None:
    _write_wav(tmp_path / "track.wav", duration_seconds=4.0)
    (tmp_path / "track.json").write_text(
        json.dumps(
            {
                "tempo": 120,
                "meter": [4, 4],
                "chord_prog": ["C", "E-m", "B-", "F#m"],
                "chords_per_bar": 2,
                "duration_in_bars": 2,
                "midi_instrument": 41,
                "seed": 123,
                "triplet_type": "anchor",
            }
        ),
        encoding="utf-8",
    )

    result = IdmtChordAdapter(dataset_id="fixture").adapt(
        _source(tmp_path, "track.json", duration_seconds=4.0), tmp_path
    )

    assert [item.chord.display_symbol for item in result.intervals] == [
        "C",
        "D#m",
        "A#",
        "F#m",
    ]
    assert [
        (item.start_seconds, item.end_seconds) for item in result.intervals
    ] == [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, 4.0)]


def test_idmt_adapter_rejects_progression_length_mismatch(tmp_path: Path) -> None:
    _write_wav(tmp_path / "track.wav", duration_seconds=4.0)
    (tmp_path / "track.json").write_text(
        json.dumps(
            {
                "tempo": 120,
                "meter": [4, 4],
                "chord_prog": ["C", "G"],
                "chords_per_bar": 2,
                "duration_in_bars": 2,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="progression length"):
        IdmtChordAdapter(dataset_id="fixture").adapt(
            _source(tmp_path, "track.json", duration_seconds=4.0), tmp_path
        )


def test_idmt_discovery_groups_triplets_and_shared_progressions(tmp_path: Path) -> None:
    sequence_root = tmp_path / "chord_sequences"
    sequence_root.mkdir()
    progressions = {
        "101": {
            "anchor": ["C", "G"],
            "positive": ["D", "A"],
            "negative": ["F", "C"],
        },
        "202": {
            "anchor": ["F", "C"],
            "positive": ["E", "B"],
            "negative": ["A", "E"],
        },
    }
    for seed, triplet in progressions.items():
        for triplet_type, progression in triplet.items():
            stem = f"{seed}_{triplet_type}"
            _write_wav(sequence_root / f"{stem}.wav")
            (sequence_root / f"{stem}.mid").write_bytes(b"midi")
            (sequence_root / f"{stem}.json").write_text(
                json.dumps(
                    {
                        "seed": int(seed),
                        "triplet_type": triplet_type,
                        "chord_prog": progression,
                    }
                ),
                encoding="utf-8",
            )

    sources = discover_idmt_sources(tmp_path)

    assert len(sources) == 6
    assert len({source.cover_group_id for source in sources}) == 1
    shared = [source for source in sources if source.track_id.endswith(("negative", "anchor"))]
    assert len({source.work_id for source in shared}) < len(shared)


def test_jazznet_adapter_reads_chord_boundaries_and_inversion_from_midi(
    tmp_path: Path,
) -> None:
    _write_wav(tmp_path / "track.wav", duration_seconds=4.0)
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=1_000_000, time=0))
    for note in (60, 64, 67, 71):
        track.append(mido.Message("note_on", note=note, velocity=100, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, time=960))
    for note in (64, 67, 71):
        track.append(mido.Message("note_off", note=note, velocity=0, time=0))
    for note in (52, 53, 57, 60):
        track.append(mido.Message("note_on", note=note, velocity=100, time=0))
    track.append(mido.Message("note_off", note=52, velocity=0, time=960))
    for note in (53, 57, 60):
        track.append(mido.Message("note_off", note=note, velocity=0, time=0))
    midi.save(tmp_path / "track.mid")

    result = JazznetMidiAdapter(dataset_id="fixture").adapt(
        _source(tmp_path, "track.mid", duration_seconds=4.0), tmp_path
    )

    assert [item.chord.display_symbol for item in result.intervals] == [
        "Cmaj7",
        "Fmaj7/E",
    ]
    assert [
        (item.start_seconds, item.end_seconds) for item in result.intervals
    ] == [(0.0, 2.0), (2.0, 4.0)]


def test_jazznet_discovery_groups_transposed_templates_together(
    tmp_path: Path,
) -> None:
    audio_root = tmp_path / "audio"
    midi_root = tmp_path / "midi"
    audio_root.mkdir()
    midi_root.mkdir()
    names = ("C-4-I-IV7-iii-VI7-52", "D-5-I-IV7-iii-VI7-52")
    for name in names:
        _write_wav(audio_root / f"{name}.wav")
        (midi_root / f"{name}.mid").write_bytes(b"fixture")
    metadata = tmp_path / "small.csv"
    metadata.write_text(
        "id,name,type,mode,octave,inversion,split\n"
        f"1,{names[0]},progression,I-IV7-iii-VI7,4,52,train\n"
        f"2,{names[1]},progression,I-IV7-iii-VI7,5,52,test\n"
        "3,C-4-maj7-chord-0,chord,maj7-chord,4,0,train\n",
        encoding="utf-8",
    )

    sources = discover_jazznet_sources(
        tmp_path,
        audio_root=audio_root,
        midi_root=midi_root,
        metadata_csv=metadata,
    )

    assert [source.track_id for source in sources] == list(names)
    assert {source.work_id for source in sources} == {"I-IV7-iii-VI7:52"}
    assert {source.cover_group_id for source in sources} == {"I-IV7-iii-VI7:52"}
    assert {source.artist_id for source in sources} == {None}


def test_adapter_rejects_source_paths_outside_declared_dataset_root(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    outside_root = tmp_path / "outside"
    dataset_root.mkdir()
    outside_root.mkdir()
    _write_wav(outside_root / "track.wav")
    (outside_root / "track.lab").write_text("0 2 C:maj\n", encoding="utf-8")

    with pytest.raises(ValueError, match="dataset root"):
        IsophonicsAdapter(dataset_id="fixture").adapt(
            _source(outside_root, "track.lab"), dataset_root
        )


@pytest.mark.parametrize(
    "content",
    [
        "0.0 1.5 C:maj\n1.0 2.0 G:maj\n",
        "0.0 0.0 C:maj\n",
        "-0.1 1.0 C:maj\n",
        "0.0 nan C:maj\n",
        "0.0 3.0 C:maj\n",
    ],
)
def test_adapter_rejects_invalid_or_overlapping_intervals(tmp_path: Path, content: str) -> None:
    _write_wav(tmp_path / "track.wav")
    (tmp_path / "track.lab").write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match="interval"):
        IsophonicsAdapter(dataset_id="fixture").adapt(_source(tmp_path, "track.lab"), tmp_path)


def test_adapter_clips_and_records_small_final_annotation_rounding_overrun(
    tmp_path: Path,
) -> None:
    _write_wav(tmp_path / "track.wav")
    (tmp_path / "track.lab").write_text("0.0 2.009 C:maj\n", encoding="utf-8")

    result = IsophonicsAdapter(dataset_id="fixture").adapt(
        _source(tmp_path, "track.lab"), tmp_path
    )

    assert result.intervals[-1].end_seconds == 2.0
    assert result.conversion.clipped_intervals == 1


def test_rwc_adapter_clips_documented_final_grid_overrun(tmp_path: Path) -> None:
    _write_wav(tmp_path / "track.wav")
    (tmp_path / "track.csv").write_text(
        "t_start;t_end;chord\n0.0;1.0;C:maj\n1.0;4.04;G:7\n",
        encoding="utf-8",
    )

    result = RwcAdapter(dataset_id="fixture").adapt(
        _source(tmp_path, "track.csv"), tmp_path
    )

    assert result.intervals[-1].end_seconds == 2.0
    assert result.conversion.clipped_intervals == 1
