from __future__ import annotations

import json
from pathlib import Path

import pytest

from museecho_ml.labels import CanonicalChord, parse_annotation
from museecho_ml.vocabulary import BASS_LABELS, QUALITY_LABELS, ROOT_LABELS, ChordVocabulary

ML_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("raw", "root", "quality", "bass", "symbol"),
    [
        ("C", "C", "maj", "1", "C"),
        ("C:maj", "C", "maj", "1", "C"),
        ("Cm", "C", "min", "1", "Cm"),
        ("C:min", "C", "min", "1", "Cm"),
        ("G:7", "G", "7", "1", "G7"),
        ("F:maj7", "F", "maj7", "1", "Fmaj7"),
        ("A:min7", "A", "min7", "1", "Am7"),
        ("B:dim", "B", "dim", "1", "Bdim"),
        ("B:hdim7", "B", "hdim7", "1", "Bm7b5"),
        ("D:sus2", "D", "sus2", "1", "Dsus2"),
        ("D:sus4", "D", "sus4", "1", "Dsus4"),
        ("C:maj/3", "C", "maj", "3", "C/E"),
        ("Cmaj7/E", "C", "maj7", "3", "Cmaj7/E"),
        ("Bbm7/Db", "A#", "min7", "b3", "A#m7/C#"),
        ("F♯:min7", "F#", "min7", "1", "F#m7"),
        ("Cb:maj", "B", "maj", "1", "B"),
    ],
)
def test_supported_annotations_are_canonicalized(
    raw: str,
    root: str,
    quality: str,
    bass: str,
    symbol: str,
) -> None:
    chord = parse_annotation(raw)

    assert chord == CanonicalChord(root, quality, bass)
    assert chord.display_symbol == symbol
    assert chord.mapping_reason is None


@pytest.mark.parametrize(
    ("raw", "state"),
    [("N", "N"), ("no_chord", "N"), ("X", "X")],
)
def test_no_chord_and_unsupported_states_remain_distinct(raw: str, state: str) -> None:
    chord = parse_annotation(raw)

    assert chord.root == state
    assert chord.quality == state
    assert chord.bass == state
    assert chord.display_symbol == state


@pytest.mark.parametrize(
    "raw",
    [
        "C:aug",
        "C:dim7",
        "C:6",
        "C:maj6",
        "C:min6",
        "C:9",
        "C:add9",
        "C:(3,5,b7,b9)",
        "C:(b9)",
        "C:min(*3)",
    ],
)
def test_valid_but_out_of_vocabulary_chords_map_to_x(raw: str) -> None:
    chord = parse_annotation(raw)

    assert (chord.root, chord.quality, chord.bass) == ("X", "X", "X")
    assert chord.mapping_reason is not None
    assert chord.mapping_reason.startswith("unsupported-quality:")


@pytest.mark.parametrize(
    "raw",
    ["", " ", "H:maj", "C:not-a-chord", "C:maj/garbage", "C:maj/E/G", "<script>", "C" * 65],
)
def test_malformed_annotations_are_rejected(raw: str) -> None:
    with pytest.raises(ValueError, match="annotation"):
        parse_annotation(raw)


def test_non_string_annotations_are_rejected() -> None:
    with pytest.raises(TypeError, match="string"):
        parse_annotation(None)  # type: ignore[arg-type]


def test_transposition_preserves_quality_and_relative_bass() -> None:
    original = parse_annotation("Bbm7/Db")

    assert original.transpose(2) == CanonicalChord("C", "min7", "b3")
    assert original.transpose(-10) == CanonicalChord("C", "min7", "b3")
    assert original.transpose(12) == original
    assert parse_annotation("N").transpose(5) == parse_annotation("N")
    assert parse_annotation("X").transpose(5) == parse_annotation("X")


def test_every_supported_chord_round_trips_through_hierarchical_heads() -> None:
    vocabulary = ChordVocabulary.default()

    for root in ROOT_LABELS[:-2]:
        for quality in QUALITY_LABELS[:-2]:
            for bass in BASS_LABELS[:-2]:
                chord = CanonicalChord(root, quality, bass)
                assert vocabulary.decode(vocabulary.encode(chord)) == chord

    for state in ("N", "X"):
        chord = CanonicalChord(state, state, state)
        assert vocabulary.decode(vocabulary.encode(chord)) == chord


@pytest.mark.parametrize(
    "chord",
    [
        CanonicalChord("N", "maj", "1"),
        CanonicalChord("C", "X", "1"),
        CanonicalChord("C", "maj", "N"),
    ],
)
def test_mixed_special_states_are_rejected(chord: CanonicalChord) -> None:
    with pytest.raises(ValueError, match="state"):
        ChordVocabulary.default().encode(chord)


def test_versioned_vocabulary_config_matches_code() -> None:
    payload = json.loads((ML_ROOT / "configs" / "vocabulary-v2.json").read_text(encoding="utf-8"))

    assert payload == {
        "schema_version": 1,
        "vocabulary_version": "2.0.0",
        "root_labels": list(ROOT_LABELS),
        "quality_labels": list(QUALITY_LABELS),
        "bass_labels": list(BASS_LABELS),
    }
