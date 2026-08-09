from __future__ import annotations

from dataclasses import dataclass

from museecho.theory.chords import parse_chord
from museecho.theory.notes import parse_note, spell_scale_degree

_MAJOR_INTERVALS = (0, 2, 4, 5, 7, 9, 11)
_MAJOR_ROMAN = ("I", "ii", "iii", "IV", "V", "vi", "vii°")
_MAJOR_QUALITIES = ("major", "minor", "minor", "major", "major", "minor", "diminished")
_MAJOR_FUNCTIONS: tuple[tuple[str, ...], ...] = (
    ("tonic",),
    ("predominant",),
    ("tonic-prolongation",),
    ("predominant",),
    ("dominant",),
    ("tonic-substitute",),
    ("dominant",),
)
_MINOR_INTERVALS = (0, 2, 3, 5, 7, 8, 10)
_MINOR_ROMAN = ("i", "ii°", "III", "iv", "v", "VI", "VII")
_MINOR_QUALITIES = ("minor", "diminished", "major", "minor", "minor", "major", "major")
_MINOR_FUNCTIONS: tuple[tuple[str, ...], ...] = (
    ("tonic",),
    ("predominant",),
    ("tonic-substitute",),
    ("predominant",),
    ("dominant",),
    ("predominant", "tonic-substitute"),
    ("dominant-substitute",),
)


@dataclass(frozen=True)
class ChordTheory:
    pitch_classes: tuple[str, ...]
    intervals: tuple[str, ...]
    quality: str | None
    roman_numeral: str | None
    functions: tuple[str, ...]
    is_diatonic: bool | None
    limitations: tuple[str, ...] = ()
    enharmonic_candidates: tuple[str, ...] = ()
    symbol: str | None = None
    tonic: str | None = None
    mode: str | None = None
    algorithm: str = "deterministic-triad-theory-v1"

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "tonic": self.tonic,
            "mode": self.mode,
            "pitch_classes": list(self.pitch_classes),
            "intervals": list(self.intervals),
            "quality": self.quality,
            "roman_numeral": self.roman_numeral,
            "functions": list(self.functions),
            "is_diatonic": self.is_diatonic,
            "enharmonic_candidates": list(self.enharmonic_candidates),
            "limitations": list(self.limitations),
            "algorithm": self.algorithm,
        }


def explain_chord(
    symbol: str | None,
    tonic: str | None,
    mode: str | None,
) -> ChordTheory:
    chord = parse_chord(symbol)
    if chord is None:
        return ChordTheory((), (), None, None, (), None, ("unsupported-chord",))
    key = parse_note(tonic)
    if key is None or mode not in {"major", "minor"}:
        return ChordTheory(
            chord.pitch_classes,
            chord.intervals,
            chord.quality,
            None,
            (),
            None,
            ("key-context-unavailable",),
            symbol=chord.symbol,
        )
    if mode == "major":
        scale_intervals = _MAJOR_INTERVALS
        roman_numerals = _MAJOR_ROMAN
        qualities = _MAJOR_QUALITIES
        functions = _MAJOR_FUNCTIONS
    else:
        scale_intervals = _MINOR_INTERVALS
        roman_numerals = _MINOR_ROMAN
        qualities = _MINOR_QUALITIES
        functions = _MINOR_FUNCTIONS
    relative_root = (chord.root.pitch_class - key.pitch_class) % 12
    if relative_root not in scale_intervals:
        return ChordTheory(
            chord.pitch_classes,
            chord.intervals,
            chord.quality,
            None,
            (),
            False,
            ("non-diatonic",),
            symbol=chord.symbol,
            tonic=key.name,
            mode=mode,
        )
    degree = scale_intervals.index(relative_root)
    if mode == "minor" and degree == 4 and chord.quality == "major":
        return ChordTheory(
            chord.pitch_classes,
            chord.intervals,
            chord.quality,
            "V",
            ("dominant",),
            False,
            ("raised-leading-tone",),
            symbol=chord.symbol,
            tonic=key.name,
            mode=mode,
        )
    if chord.quality != qualities[degree]:
        return ChordTheory(
            chord.pitch_classes,
            chord.intervals,
            chord.quality,
            None,
            (),
            False,
            ("non-diatonic",),
            symbol=chord.symbol,
            tonic=key.name,
            mode=mode,
        )
    expected_root = spell_scale_degree(key, degree, scale_intervals[degree])
    if chord.root.name != expected_root:
        suffix = "m" if chord.quality == "minor" else ""
        limitations: tuple[str, ...] = ("enharmonic-key-spelling",)
        enharmonic_candidates: tuple[str, ...] = (f"{expected_root}{suffix}",)
    else:
        limitations = ()
        enharmonic_candidates = ()
    return ChordTheory(
        chord.pitch_classes,
        chord.intervals,
        chord.quality,
        roman_numerals[degree],
        functions[degree],
        True,
        limitations,
        enharmonic_candidates,
        symbol=chord.symbol,
        tonic=key.name,
        mode=mode,
    )
