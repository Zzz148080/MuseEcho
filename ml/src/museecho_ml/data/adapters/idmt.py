from __future__ import annotations

import hashlib
import json
import math
import re
import wave
from collections.abc import Iterable
from pathlib import Path

from museecho_ml.data.adapters.base import DatasetAdapter
from museecho_ml.data.manifest import ChordInterval, LocalTrackSource
from museecho_ml.labels import parse_annotation

_IDMT_CHORD = re.compile(r"^(?P<letter>[A-G])(?P<accidental>[#-]?)(?P<minor>m?)$")
_IDMT_TRACK = re.compile(
    r"^(?P<seed>\d+)_(?P<triplet_type>anchor|positive|negative)$"
)


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


def discover_idmt_sources(
    dataset_root: Path, *, sequence_root: Path | None = None
) -> tuple[LocalTrackSource, ...]:
    """Pair the official triplets and form leakage-safe sequence components."""

    root = dataset_root.resolve(strict=True)
    sequences = (sequence_root or root / "chord_sequences").resolve(strict=True)
    if not sequences.is_dir() or not sequences.is_relative_to(root):
        raise ValueError("IDMT sequence root must be a directory inside the dataset root")

    records: list[tuple[str, str, tuple[str, ...], Path, Path, float]] = []
    triplet_members: dict[str, set[str]] = {}
    for annotation in sorted(sequences.glob("*.json"), key=lambda path: path.name):
        match = _IDMT_TRACK.fullmatch(annotation.stem)
        if match is None:
            raise ValueError(f"unexpected IDMT annotation filename: {annotation.name}")
        try:
            payload = json.loads(annotation.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(f"IDMT annotation is unreadable: {annotation.name}") from error
        if not isinstance(payload, dict):
            raise ValueError(f"IDMT annotation is not an object: {annotation.name}")
        seed = str(payload.get("seed"))
        triplet_type = payload.get("triplet_type")
        progression = payload.get("chord_prog")
        if (
            seed != match.group("seed")
            or triplet_type != match.group("triplet_type")
            or not isinstance(progression, list)
            or not progression
            or any(not isinstance(chord, str) for chord in progression)
        ):
            raise ValueError(f"IDMT triplet metadata is inconsistent: {annotation.name}")
        triplet_members.setdefault(seed, set()).add(str(triplet_type))
        audio = annotation.with_suffix(".wav")
        midi = annotation.with_suffix(".mid")
        if not audio.is_file() or not midi.is_file():
            raise ValueError(f"IDMT WAV or MIDI pair is missing: {annotation.stem}")
        records.append(
            (
                annotation.stem,
                seed,
                tuple(progression),
                audio,
                annotation,
                _wav_duration_seconds(audio),
            )
        )
    if not records:
        raise ValueError("IDMT does not contain chord-sequence annotations")
    expected = {"anchor", "positive", "negative"}
    if any(members != expected for members in triplet_members.values()):
        raise ValueError("IDMT official triplets are incomplete")

    parents = list(range(len(records)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    first_by_seed: dict[str, int] = {}
    first_by_progression: dict[tuple[str, ...], int] = {}
    for index, (_, seed, progression, *_rest) in enumerate(records):
        for key, lookup in ((seed, first_by_seed), (progression, first_by_progression)):
            previous = lookup.setdefault(key, index)
            union(index, previous)
    component_tracks: dict[int, list[str]] = {}
    for index, record in enumerate(records):
        component_tracks.setdefault(find(index), []).append(record[0])
    component_ids = {
        root_index: "idmt-component-"
        + hashlib.sha256("\n".join(sorted(track_ids)).encode()).hexdigest()[:16]
        for root_index, track_ids in component_tracks.items()
    }

    sources = []
    for index, (track_id, _seed, progression, audio, annotation, duration) in enumerate(
        records
    ):
        progression_id = hashlib.sha256(
            json.dumps(progression, separators=(",", ":")).encode()
        ).hexdigest()[:16]
        sources.append(
            LocalTrackSource(
                dataset_id="idmt-smt-chord-sequences",
                track_id=track_id,
                work_id=f"idmt-progression-{progression_id}",
                cover_group_id=component_ids[find(index)],
                artist_id=None,
                audio_path=audio,
                annotation_path=annotation,
                duration_seconds=duration,
            )
        )
    return tuple(sources)


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


def _wav_duration_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as audio:
            frame_rate = audio.getframerate()
            frame_count = audio.getnframes()
    except (EOFError, wave.Error):
        raise ValueError(f"IDMT audio is not a readable WAV file: {path.name}") from None
    if frame_rate <= 0 or frame_count <= 0:
        raise ValueError(f"IDMT audio has invalid duration: {path.name}")
    return frame_count / frame_rate
