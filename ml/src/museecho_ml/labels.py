from __future__ import annotations

import re
from dataclasses import dataclass, field

PITCH_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
SUPPORTED_QUALITIES = ("maj", "min", "7", "maj7", "min7", "dim", "hdim7", "sus2", "sus4")
BASS_INTERVALS = ("1", "b2", "2", "b3", "3", "4", "b5", "5", "b6", "6", "b7", "7")

_NATURAL_PITCH_CLASSES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_BASS_TO_SEMITONES = {name: index for index, name in enumerate(BASS_INTERVALS)}
_SEMITONES_TO_BASS = {value: name for name, value in _BASS_TO_SEMITONES.items()}
_QUALITY_SUFFIXES = {
    "maj": "",
    "min": "m",
    "7": "7",
    "maj7": "maj7",
    "min7": "m7",
    "dim": "dim",
    "hdim7": "m7b5",
    "sus2": "sus2",
    "sus4": "sus4",
}
_QUALITY_ALIASES = {
    "": "maj",
    "M": "maj",
    "maj": "maj",
    "major": "maj",
    "m": "min",
    "min": "min",
    "minor": "min",
    "7": "7",
    "M7": "maj7",
    "maj7": "maj7",
    "major7": "maj7",
    "m7": "min7",
    "min7": "min7",
    "minor7": "min7",
    "dim": "dim",
    "hdim7": "hdim7",
    "ø7": "hdim7",
    "m7b5": "hdim7",
    "sus2": "sus2",
    "sus4": "sus4",
}
_OUT_OF_VOCABULARY_QUALITIES = {
    "aug",
    "dim7",
    "6",
    "min6",
    "m6",
    "9",
    "add9",
}
_ANNOTATION_PATTERN = re.compile(
    r"^(?P<root>[A-G](?:[#b♯♭]{0,2}))"
    r"(?::(?P<colon_quality>[^/]+)|(?P<compact_quality>[^/]*))"
    r"(?:/(?P<bass>[^/]+))?$"
)


@dataclass(frozen=True)
class CanonicalChord:
    root: str
    quality: str
    bass: str
    mapping_reason: str | None = field(default=None, compare=False)

    @property
    def display_symbol(self) -> str:
        if self.root in {"N", "X"}:
            return self.root
        suffix = _QUALITY_SUFFIXES.get(self.quality)
        if suffix is None or self.root not in PITCH_NAMES or self.bass not in BASS_INTERVALS:
            raise ValueError("chord state is not displayable")
        symbol = f"{self.root}{suffix}"
        if self.bass != "1":
            root_pitch = PITCH_NAMES.index(self.root)
            bass_pitch = (root_pitch + _BASS_TO_SEMITONES[self.bass]) % len(PITCH_NAMES)
            symbol = f"{symbol}/{PITCH_NAMES[bass_pitch]}"
        return symbol

    def transpose(self, semitones: int) -> CanonicalChord:
        if type(semitones) is not int:
            raise TypeError("semitones must be an integer")
        if self.root in {"N", "X"}:
            return self
        if self.root not in PITCH_NAMES:
            raise ValueError("chord state has an invalid root")
        root = PITCH_NAMES[(PITCH_NAMES.index(self.root) + semitones) % len(PITCH_NAMES)]
        return CanonicalChord(root, self.quality, self.bass, self.mapping_reason)


def parse_annotation(raw: str) -> CanonicalChord:
    if not isinstance(raw, str):
        raise TypeError("chord annotation must be a string")
    annotation = raw.strip()
    if not annotation or len(annotation) > 64:
        raise ValueError("chord annotation must contain between 1 and 64 characters")
    if annotation in {"N", "no_chord"}:
        return CanonicalChord("N", "N", "N")
    if annotation == "X":
        return CanonicalChord("X", "X", "X")

    match = _ANNOTATION_PATTERN.fullmatch(annotation)
    if match is None:
        raise ValueError("chord annotation has an invalid shape")

    root = _canonical_pitch(match.group("root"))
    raw_quality = match.group("colon_quality")
    if raw_quality is None:
        raw_quality = match.group("compact_quality") or ""
    quality = _QUALITY_ALIASES.get(raw_quality)
    if quality is None:
        unsupported = _canonical_unsupported_quality(raw_quality)
        if unsupported is not None:
            return CanonicalChord("X", "X", "X", f"unsupported-quality:{unsupported}")
        raise ValueError("chord annotation has an invalid quality")

    raw_bass = match.group("bass")
    bass = "1" if raw_bass is None else _canonical_bass(raw_bass, root)
    return CanonicalChord(root, quality, bass)


def _canonical_pitch(raw: str) -> str:
    normalized = raw.replace("♯", "#").replace("♭", "b")
    match = re.fullmatch(r"([A-G])([#b]{0,2})", normalized)
    if match is None:
        raise ValueError("chord annotation has an invalid pitch")
    pitch_class = _NATURAL_PITCH_CLASSES[match.group(1)]
    for accidental in match.group(2):
        pitch_class += 1 if accidental == "#" else -1
    return PITCH_NAMES[pitch_class % len(PITCH_NAMES)]


def _canonical_bass(raw: str, root: str) -> str:
    normalized = raw.replace("♯", "#").replace("♭", "b")
    interval_aliases = {"#1": "b2", "#2": "b3", "#4": "b5", "#5": "b6", "#6": "b7"}
    normalized = interval_aliases.get(normalized, normalized)
    if normalized in BASS_INTERVALS:
        return normalized
    try:
        bass_pitch = _canonical_pitch(normalized)
    except ValueError:
        raise ValueError("chord annotation has an invalid bass") from None
    semitones = (PITCH_NAMES.index(bass_pitch) - PITCH_NAMES.index(root)) % len(PITCH_NAMES)
    return _SEMITONES_TO_BASS[semitones]


def _canonical_unsupported_quality(raw: str) -> str | None:
    if raw in _OUT_OF_VOCABULARY_QUALITIES:
        return "min6" if raw == "m6" else raw
    return None
