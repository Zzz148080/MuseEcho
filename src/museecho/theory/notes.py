from __future__ import annotations

from dataclasses import dataclass

_NATURAL_PITCH_CLASSES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_ACCIDENTAL_OFFSETS = {"": 0, "#": 1, "b": -1}
_NOTE_LETTERS = ("C", "D", "E", "F", "G", "A", "B")


@dataclass(frozen=True)
class Note:
    name: str
    pitch_class: int


def parse_note(value: str | None) -> Note | None:
    if not isinstance(value, str) or len(value) not in {1, 2}:
        return None
    value = value.replace("♯", "#").replace("♭", "b")
    letter = value[0]
    accidental = value[1:] if len(value) == 2 else ""
    if letter not in _NATURAL_PITCH_CLASSES or accidental not in _ACCIDENTAL_OFFSETS:
        return None
    pitch_class = (_NATURAL_PITCH_CLASSES[letter] + _ACCIDENTAL_OFFSETS[accidental]) % 12
    return Note(value, pitch_class)


def spell_note(letter: str, pitch_class: int) -> str:
    difference = (pitch_class - _NATURAL_PITCH_CLASSES[letter] + 6) % 12 - 6
    if difference == 0:
        return letter
    accidental = "#" if difference > 0 else "b"
    return letter + accidental * abs(difference)


def spell_scale_degree(tonic: Note, degree: int, semitone_interval: int) -> str:
    tonic_letter = _NOTE_LETTERS.index(tonic.name[0])
    degree_letter = _NOTE_LETTERS[(tonic_letter + degree) % len(_NOTE_LETTERS)]
    return spell_note(degree_letter, (tonic.pitch_class + semitone_interval) % 12)
