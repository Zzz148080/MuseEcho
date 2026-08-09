import json

import pytest

from museecho.theory import ChordTheory, explain_chord

MAJOR_TONICS = [
    ("C", ("C", "E", "G")),
    ("Db", ("Db", "F", "Ab")),
    ("D", ("D", "F#", "A")),
    ("Eb", ("Eb", "G", "Bb")),
    ("E", ("E", "G#", "B")),
    ("F", ("F", "A", "C")),
    ("Gb", ("Gb", "Bb", "Db")),
    ("G", ("G", "B", "D")),
    ("Ab", ("Ab", "C", "Eb")),
    ("A", ("A", "C#", "E")),
    ("Bb", ("Bb", "D", "F")),
    ("B", ("B", "D#", "F#")),
]

MINOR_TONICS = [
    ("C", ("C", "Eb", "G")),
    ("C#", ("C#", "E", "G#")),
    ("D", ("D", "F", "A")),
    ("Eb", ("Eb", "Gb", "Bb")),
    ("E", ("E", "G", "B")),
    ("F", ("F", "Ab", "C")),
    ("F#", ("F#", "A", "C#")),
    ("G", ("G", "Bb", "D")),
    ("Ab", ("Ab", "Cb", "Eb")),
    ("A", ("A", "C", "E")),
    ("Bb", ("Bb", "Db", "F")),
    ("B", ("B", "D", "F#")),
]

MAJOR_DOMINANTS = [
    ("C", "G"),
    ("Db", "Ab"),
    ("D", "A"),
    ("Eb", "Bb"),
    ("E", "B"),
    ("F", "C"),
    ("Gb", "Db"),
    ("G", "D"),
    ("Ab", "Eb"),
    ("A", "E"),
    ("Bb", "F"),
    ("B", "F#"),
]

MINOR_DOMINANTS = [
    ("C", "G"),
    ("C#", "G#"),
    ("D", "A"),
    ("Eb", "Bb"),
    ("E", "B"),
    ("F", "C"),
    ("F#", "C#"),
    ("G", "D"),
    ("Ab", "Eb"),
    ("A", "E"),
    ("Bb", "F"),
    ("B", "F#"),
]

DIATONIC_CONTEXTS = [
    ("C", "C", "major", "I", ("tonic",)),
    ("Dm", "C", "major", "ii", ("predominant",)),
    ("Em", "C", "major", "iii", ("tonic-prolongation",)),
    ("F", "C", "major", "IV", ("predominant",)),
    ("G", "C", "major", "V", ("dominant",)),
    ("Am", "C", "major", "vi", ("tonic-substitute",)),
    ("Am", "A", "minor", "i", ("tonic",)),
    ("C", "A", "minor", "III", ("tonic-substitute",)),
    ("Dm", "A", "minor", "iv", ("predominant",)),
    ("Em", "A", "minor", "v", ("dominant",)),
    ("F", "A", "minor", "VI", ("predominant", "tonic-substitute")),
    ("G", "A", "minor", "VII", ("dominant-substitute",)),
]


def test_g_major_in_c_major_is_dominant():
    theory = explain_chord("G", tonic="C", mode="major")

    assert isinstance(theory, ChordTheory)
    assert theory.pitch_classes == ("G", "B", "D")
    assert theory.roman_numeral == "V"
    assert "dominant" in theory.functions


def test_a_minor_in_c_major_is_a_diatonic_tonic_substitute():
    theory = explain_chord("Am", tonic="C", mode="major")

    assert theory.pitch_classes == ("A", "C", "E")
    assert theory.intervals == ("root", "minor third", "perfect fifth")
    assert theory.quality == "minor"
    assert theory.roman_numeral == "vi"
    assert theory.functions == ("tonic-substitute",)
    assert theory.is_diatonic is True


def test_flat_key_preserves_theoretical_chord_spelling():
    theory = explain_chord("Db", tonic="Db", mode="major")

    assert theory.pitch_classes == ("Db", "F", "Ab")
    assert theory.roman_numeral == "I"
    assert theory.functions == ("tonic",)
    assert theory.is_diatonic is True


def test_minor_key_tonic_uses_lowercase_roman_numeral():
    theory = explain_chord("Cm", tonic="C", mode="minor")

    assert theory.pitch_classes == ("C", "Eb", "G")
    assert theory.roman_numeral == "i"
    assert theory.functions == ("tonic",)
    assert theory.is_diatonic is True


def test_major_dominant_in_minor_key_is_explicitly_contextual():
    theory = explain_chord("G", tonic="C", mode="minor")

    assert theory.roman_numeral == "V"
    assert theory.functions == ("dominant",)
    assert theory.is_diatonic is False
    assert "raised-leading-tone" in theory.limitations


def test_non_diatonic_chord_does_not_invent_a_unique_function():
    theory = explain_chord("F#", tonic="C", mode="major")

    assert theory.pitch_classes == ("F#", "A#", "C#")
    assert theory.roman_numeral is None
    assert theory.functions == ()
    assert theory.is_diatonic is False
    assert theory.limitations == ("non-diatonic",)


@pytest.mark.parametrize("symbol", [None, "", "unknown", "C7", "H"])
def test_unknown_or_unsupported_chord_returns_no_music_facts(symbol):
    theory = explain_chord(symbol, tonic="C", mode="major")

    assert theory.pitch_classes == ()
    assert theory.quality is None
    assert theory.roman_numeral is None
    assert theory.functions == ()
    assert theory.is_diatonic is None
    assert theory.limitations == ("unsupported-chord",)


@pytest.mark.parametrize(
    ("tonic", "mode"),
    [(None, None), ("H", "major"), ("C", "dorian")],
)
def test_unavailable_key_context_keeps_only_intrinsic_chord_facts(tonic, mode):
    theory = explain_chord("C", tonic=tonic, mode=mode)

    assert theory.pitch_classes == ("C", "E", "G")
    assert theory.quality == "major"
    assert theory.roman_numeral is None
    assert theory.functions == ()
    assert theory.is_diatonic is None
    assert theory.limitations == ("key-context-unavailable",)


def test_enharmonic_root_keeps_input_spelling_and_reports_key_candidate():
    theory = explain_chord("C#", tonic="Db", mode="major")

    assert theory.pitch_classes == ("C#", "E#", "G#")
    assert theory.roman_numeral == "I"
    assert theory.functions == ("tonic",)
    assert theory.is_diatonic is True
    assert theory.enharmonic_candidates == ("Db",)
    assert "enharmonic-key-spelling" in theory.limitations


def test_minor_dominant_reports_enharmonic_key_spelling_candidate():
    theory = explain_chord("Ab", tonic="C#", mode="minor")

    assert theory.roman_numeral == "V"
    assert theory.functions == ("dominant",)
    assert theory.is_diatonic is False
    assert theory.enharmonic_candidates == ("G#",)
    assert theory.limitations == (
        "raised-leading-tone",
        "enharmonic-key-spelling",
    )


def test_theory_payload_is_self_contained_strict_json_and_versioned():
    payload = explain_chord("G", tonic="C", mode="major").to_dict()

    assert payload == {
        "symbol": "G",
        "tonic": "C",
        "mode": "major",
        "pitch_classes": ["G", "B", "D"],
        "intervals": ["root", "major third", "perfect fifth"],
        "quality": "major",
        "roman_numeral": "V",
        "functions": ["dominant"],
        "is_diatonic": True,
        "enharmonic_candidates": [],
        "limitations": [],
        "algorithm": "deterministic-triad-theory-v1",
    }
    json.dumps(payload, allow_nan=False)


@pytest.mark.parametrize(("tonic", "expected_pitch_classes"), MAJOR_TONICS)
def test_all_twelve_major_tonics_are_spelled_and_classified_deterministically(
    tonic,
    expected_pitch_classes,
):
    theory = explain_chord(tonic, tonic=tonic, mode="major")

    assert theory.pitch_classes == expected_pitch_classes
    assert theory.roman_numeral == "I"
    assert theory.functions == ("tonic",)
    assert theory.is_diatonic is True
    assert theory == explain_chord(tonic, tonic=tonic, mode="major")


@pytest.mark.parametrize(("tonic", "expected_pitch_classes"), MINOR_TONICS)
def test_all_twelve_minor_tonics_are_spelled_and_classified_deterministically(
    tonic,
    expected_pitch_classes,
):
    theory = explain_chord(f"{tonic}m", tonic=tonic, mode="minor")

    assert theory.pitch_classes == expected_pitch_classes
    assert theory.roman_numeral == "i"
    assert theory.functions == ("tonic",)
    assert theory.is_diatonic is True
    assert theory == explain_chord(f"{tonic}m", tonic=tonic, mode="minor")


@pytest.mark.parametrize(("tonic", "dominant"), MAJOR_DOMINANTS)
def test_all_twelve_major_keys_classify_the_dominant(tonic, dominant):
    theory = explain_chord(dominant, tonic=tonic, mode="major")

    assert theory.roman_numeral == "V"
    assert theory.functions == ("dominant",)
    assert theory.is_diatonic is True


@pytest.mark.parametrize(("tonic", "dominant"), MINOR_DOMINANTS)
def test_all_twelve_minor_keys_classify_the_raised_leading_tone_dominant(
    tonic,
    dominant,
):
    theory = explain_chord(dominant, tonic=tonic, mode="minor")

    assert theory.roman_numeral == "V"
    assert theory.functions == ("dominant",)
    assert theory.is_diatonic is False
    assert theory.limitations == ("raised-leading-tone",)


@pytest.mark.parametrize(
    ("symbol", "tonic", "expected"),
    [("F♯m", "F♯", ("F#", "A", "C#")), ("B♭", "B♭", ("Bb", "D", "F"))],
)
def test_unicode_accidentals_normalize_without_changing_pitch(symbol, tonic, expected):
    theory = explain_chord(symbol, tonic=tonic, mode="minor" if symbol.endswith("m") else "major")

    assert theory.pitch_classes == expected
    assert theory.roman_numeral in {"I", "i"}
    assert theory.is_diatonic is True


@pytest.mark.parametrize(
    ("symbol", "tonic", "mode", "roman_numeral", "functions"),
    DIATONIC_CONTEXTS,
)
def test_supported_diatonic_degrees_have_table_driven_functions(
    symbol,
    tonic,
    mode,
    roman_numeral,
    functions,
):
    theory = explain_chord(symbol, tonic=tonic, mode=mode)

    assert theory.roman_numeral == roman_numeral
    assert theory.functions == functions
    assert theory.is_diatonic is True
