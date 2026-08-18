from __future__ import annotations

import csv
import math
import wave
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

import mido

from museecho_ml.data.adapters.base import DatasetAdapter
from museecho_ml.data.manifest import ChordInterval, LocalTrackSource
from museecho_ml.labels import BASS_INTERVALS, PITCH_NAMES, CanonicalChord

_TEMPLATES = (
    ("hdim7", frozenset((0, 3, 6, 10))),
    ("maj7", frozenset((0, 4, 7, 11))),
    ("min7", frozenset((0, 3, 7, 10))),
    ("7", frozenset((0, 4, 7, 10))),
    ("dim", frozenset((0, 3, 6))),
    ("sus2", frozenset((0, 2, 7))),
    ("sus4", frozenset((0, 5, 7))),
    ("maj", frozenset((0, 4, 7))),
    ("min", frozenset((0, 3, 7))),
)


class JazznetMidiAdapter(DatasetAdapter):
    """Read aligned Jazznet MIDI blocks and infer the supported chord state."""

    def _read_intervals(self, annotation: Path) -> Iterable[ChordInterval]:
        try:
            midi = mido.MidiFile(filename=annotation, clip=True)
        except (EOFError, OSError, ValueError) as error:
            raise ValueError("Jazznet annotation must be a readable MIDI file") from error
        tempo = 500_000
        current_seconds = 0.0
        active: Counter[int] = Counter()
        intervals: list[ChordInterval] = []
        try:
            messages = mido.merge_tracks(midi.tracks)
            for message in messages:
                delta = mido.tick2second(message.time, midi.ticks_per_beat, tempo)
                if not math.isfinite(delta) or delta < 0:
                    raise ValueError("Jazznet MIDI contains invalid timing")
                next_seconds = current_seconds + delta
                if delta > 0 and active:
                    _append_or_extend(
                        intervals,
                        ChordInterval(
                            current_seconds,
                            next_seconds,
                            _classify_chord(tuple(active.elements())),
                        ),
                    )
                current_seconds = next_seconds
                if message.type == "set_tempo":
                    tempo = message.tempo
                elif message.type == "note_on" and message.velocity > 0:
                    active[message.note] += 1
                elif message.type in {"note_off", "note_on"}:
                    if active[message.note] > 1:
                        active[message.note] -= 1
                    else:
                        active.pop(message.note, None)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Jazznet MIDI contains invalid chord events") from error
        if not intervals:
            raise ValueError("Jazznet MIDI does not contain timed chord notes")
        yield from intervals


def discover_jazznet_sources(
    dataset_root: Path,
    *,
    audio_root: Path | None = None,
    audio_roots: tuple[Path, ...] = (),
    midi_root: Path,
    metadata_csv: Path,
    source_types: tuple[str, ...] = ("progression",),
) -> tuple[LocalTrackSource, ...]:
    """Pair the bounded Jazznet progression subset and group template variants."""

    root = dataset_root.resolve(strict=True)
    if (audio_root is None) == (not audio_roots):
        raise ValueError("Jazznet requires exactly one audio_root input form")
    requested_audio_roots = (audio_root,) if audio_root is not None else audio_roots
    audio_directories = tuple(
        _resolve_within(path, root, directory=True) for path in requested_audio_roots
    )
    midi_directory = _resolve_within(midi_root, root, directory=True)
    metadata_path = _resolve_within(metadata_csv, root, directory=False)
    if not source_types or any(not isinstance(item, str) or not item for item in source_types):
        raise ValueError("Jazznet source_types must contain non-empty strings")
    requested_types = set(source_types)
    audio_by_stem = _index_unique_files_many(audio_directories, (".wav",))
    midi_by_stem = _index_unique_files(midi_directory, (".mid", ".midi"))

    sources: list[LocalTrackSource] = []
    seen_names: set[str] = set()
    with metadata_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"name", "type", "mode", "inversion"}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError("Jazznet metadata is missing progression grouping fields")
        for line_number, row in enumerate(reader, start=2):
            source_type = row["type"].strip()
            if source_type not in requested_types:
                continue
            name = row["name"].strip()
            mode = row["mode"].strip()
            inversion = row["inversion"].strip()
            if not name or not mode or not inversion or name in seen_names:
                raise ValueError(f"Jazznet metadata row {line_number} is invalid or duplicated")
            seen_names.add(name)
            audio = audio_by_stem.get(name)
            midi = midi_by_stem.get(name)
            if audio is None or midi is None:
                raise ValueError(f"Jazznet audio or MIDI is missing for {name}")
            template_group = f"{mode}:{inversion}"
            if source_type != "progression":
                template_group = f"{source_type}:{template_group}"
            sources.append(
                LocalTrackSource(
                    dataset_id="jazznet",
                    track_id=name,
                    work_id=template_group,
                    cover_group_id=template_group,
                    artist_id=None,
                    audio_path=audio,
                    annotation_path=midi,
                    duration_seconds=_wav_duration_seconds(audio),
                )
            )
    if not sources:
        raise ValueError("Jazznet metadata does not contain progression rows")
    return tuple(sorted(sources, key=lambda item: item.track_id))


def _classify_chord(notes: tuple[int, ...]) -> CanonicalChord:
    if not notes or any(type(note) is not int or not 0 <= note <= 127 for note in notes):
        raise ValueError("Jazznet MIDI chord notes are invalid")
    pitch_classes = frozenset(note % 12 for note in notes)
    for root in range(12):
        relative = frozenset((pitch - root) % 12 for pitch in pitch_classes)
        for quality, template in _TEMPLATES:
            if relative == template:
                bass = BASS_INTERVALS[(min(notes) - root) % 12]
                return CanonicalChord(PITCH_NAMES[root], quality, bass)
    return CanonicalChord("X", "X", "X", "unsupported-midi-pitch-set")


def _append_or_extend(intervals: list[ChordInterval], item: ChordInterval) -> None:
    if (
        intervals
        and intervals[-1].chord == item.chord
        and math.isclose(intervals[-1].end_seconds, item.start_seconds, abs_tol=1e-9)
    ):
        previous = intervals[-1]
        intervals[-1] = ChordInterval(
            previous.start_seconds, item.end_seconds, previous.chord
        )
    else:
        intervals.append(item)


def _resolve_within(path: Path, root: Path, *, directory: bool) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise ValueError("Jazznet source path does not exist") from None
    correct_type = resolved.is_dir() if directory else resolved.is_file()
    if not resolved.is_relative_to(root) or not correct_type:
        raise ValueError("Jazznet source path must remain inside the dataset root")
    return resolved


def _index_unique_files(root: Path, suffixes: tuple[str, ...]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in sorted(
        (item for item in root.rglob("*") if item.is_file() and item.suffix.lower() in suffixes),
        key=lambda item: item.as_posix(),
    ):
        if path.stem in result:
            raise ValueError(f"Jazznet source filename is ambiguous: {path.stem}")
        result[path.stem] = path
    return result


def _index_unique_files_many(
    roots: tuple[Path, ...], suffixes: tuple[str, ...]
) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for root in roots:
        for stem, path in _index_unique_files(root, suffixes).items():
            if stem in result:
                raise ValueError(f"Jazznet source filename is ambiguous: {stem}")
            result[stem] = path
    return result


def _wav_duration_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as audio:
            frame_rate = audio.getframerate()
            frame_count = audio.getnframes()
    except (EOFError, wave.Error):
        raise ValueError(f"Jazznet audio is not a readable WAV file: {path.name}") from None
    if frame_rate <= 0 or frame_count <= 0:
        raise ValueError(f"Jazznet audio has invalid duration: {path.name}")
    return frame_count / frame_rate
