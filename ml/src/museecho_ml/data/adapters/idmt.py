from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from pathlib import Path

from museecho_ml.data.adapters.base import DatasetAdapter
from museecho_ml.data.manifest import ChordInterval
from museecho_ml.labels import parse_annotation

_IDMT_CHORD = re.compile(r"^(?P<letter>[A-G])(?P<accidental>[#-]?)(?P<minor>m?)$")


class IdmtChordAdapter(DatasetAdapter):
    """Convert IDMT symbolic progression metadata into exact time intervals."""

    def _read_intervals(self, annotation: Path) -> Iterable[ChordInterval]:
        try:
            payload = json.loads(annotation.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("IDMT annotation must be readable JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("IDMT annotation must be an object")

        tempo = _positive_number(payload.get("tempo"), "tempo")
        meter = payload.get("meter")
        if (
            not isinstance(meter, list)
            or len(meter) != 2
            or any(type(value) is not int or value <= 0 for value in meter)
        ):
            raise ValueError("IDMT meter must contain two positive integers")
        chords_per_bar = _positive_integer(
            payload.get("chords_per_bar"), "chords_per_bar"
        )
        duration_in_bars = _positive_integer(
            payload.get("duration_in_bars"), "duration_in_bars"
        )
        progression = payload.get("chord_prog")
        expected_chords = chords_per_bar * duration_in_bars
        if (
            not isinstance(progression, list)
            or len(progression) != expected_chords
            or any(not isinstance(chord, str) for chord in progression)
        ):
            raise ValueError(
                "IDMT chord progression length must equal bars times chords_per_bar"
            )

        quarter_beats_per_bar = meter[0] * 4 / meter[1]
        chord_seconds = quarter_beats_per_bar * 60 / tempo / chords_per_bar
        for index, raw_chord in enumerate(progression):
            start = index * chord_seconds
            end = (index + 1) * chord_seconds
            yield ChordInterval(
                start,
                end,
                parse_annotation(_normalize_idmt_chord(raw_chord)),
            )


def _normalize_idmt_chord(raw: str) -> str:
    match = _IDMT_CHORD.fullmatch(raw.strip())
    if match is None:
        raise ValueError("IDMT chord symbol is invalid")
    accidental = "b" if match.group("accidental") == "-" else match.group("accidental")
    quality = "min" if match.group("minor") else "maj"
    return f"{match.group('letter')}{accidental}:{quality}"


def _positive_number(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"IDMT {field} must be finite and positive")
    return float(value)


def _positive_integer(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"IDMT {field} must be a positive integer")
    return value
