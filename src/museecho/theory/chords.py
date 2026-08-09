from __future__ import annotations

from dataclasses import dataclass

from museecho.theory.notes import Note, parse_note, spell_note

_NATURAL_NAMES = ("C", "D", "E", "F", "G", "A", "B")


@dataclass(frozen=True)
class ParsedChord:
    symbol: str
    root: Note
    quality: str
    pitch_classes: tuple[str, str, str]
    intervals: tuple[str, str, str]


def parse_chord(symbol: str | None) -> ParsedChord | None:
    if not isinstance(symbol, str):
        return None
    quality = "minor" if symbol.endswith("m") else "major"
    root_symbol = symbol[:-1] if quality == "minor" else symbol
    root = parse_note(root_symbol)
    if root is None:
        return None
    root_index = _NATURAL_NAMES.index(root.name[0])
    third_letter = _NATURAL_NAMES[(root_index + 2) % len(_NATURAL_NAMES)]
    fifth_letter = _NATURAL_NAMES[(root_index + 4) % len(_NATURAL_NAMES)]
    third_semitones = 3 if quality == "minor" else 4
    third = spell_note(third_letter, (root.pitch_class + third_semitones) % 12)
    fifth = spell_note(fifth_letter, (root.pitch_class + 7) % 12)
    third_interval = "minor third" if quality == "minor" else "major third"
    canonical_symbol = f"{root.name}{'m' if quality == 'minor' else ''}"
    return ParsedChord(
        canonical_symbol,
        root,
        quality,
        (root.name, third, fifth),
        ("root", third_interval, "perfect fifth"),
    )
