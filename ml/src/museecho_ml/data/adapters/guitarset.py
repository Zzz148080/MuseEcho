from __future__ import annotations

import json
import math
import re
import wave
from collections.abc import Iterable
from pathlib import Path

from museecho_ml.data.adapters.base import DatasetAdapter
from museecho_ml.data.manifest import ChordInterval, LocalTrackSource
from museecho_ml.labels import parse_annotation

_TRACK_PATTERN = re.compile(
    r"^(?P<player>\d{2})_(?P<lead_sheet>.+)_(?P<version>comp|solo)$"
)
_PERFORMED_SOURCE = "Semi-automatic chord transcription with manual verification"


class GuitarSetAdapter(DatasetAdapter):
    """Read GuitarSet's manually verified performed-chord JAMS annotation."""

    def _read_intervals(self, annotation: Path) -> Iterable[ChordInterval]:
        try:
            payload = json.loads(annotation.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("GuitarSet annotation must be readable JSON") from error
        annotations = payload.get("annotations") if isinstance(payload, dict) else None
        if not isinstance(annotations, list):
            raise ValueError("GuitarSet annotation must contain an annotations list")
        performed = [
            item
            for item in annotations
            if isinstance(item, dict)
            and item.get("namespace") == "chord"
            and _PERFORMED_SOURCE
            in str(item.get("annotation_metadata", {}).get("data_source", ""))
        ]
        if len(performed) != 1:
            raise ValueError(
                "GuitarSet annotation must contain exactly one verified performed chord track"
            )
        data = performed[0].get("data")
        observations = _observations(data)
        for index, (start, duration, value) in enumerate(observations, start=1):
            if (
                isinstance(start, bool)
                or not isinstance(start, (int, float))
                or isinstance(duration, bool)
                or not isinstance(duration, (int, float))
                or not math.isfinite(start)
                or not math.isfinite(duration)
                or duration <= 0
                or not isinstance(value, str)
            ):
                raise ValueError(f"GuitarSet chord item {index} is invalid")
            try:
                chord = parse_annotation(value)
            except (TypeError, ValueError):
                raise ValueError(f"GuitarSet chord item {index} is invalid") from None
            yield ChordInterval(float(start), float(start + duration), chord)


def _observations(data: object) -> tuple[tuple[object, object, object], ...]:
    if isinstance(data, list):
        if not data or any(not isinstance(item, dict) for item in data):
            raise ValueError("GuitarSet chord observations must be non-empty objects")
        return tuple(
            (item.get("time"), item.get("duration"), item.get("value"))
            for item in data
        )
    if isinstance(data, dict):
        times = data.get("time")
        durations = data.get("duration")
        values = data.get("value")
        if (
            not isinstance(times, list)
            or not isinstance(durations, list)
            or not isinstance(values, list)
            or not times
            or len(times) != len(durations)
            or len(times) != len(values)
        ):
            raise ValueError("GuitarSet chord vectors must be non-empty and equally sized")
        return tuple(zip(times, durations, values, strict=True))
    raise ValueError("GuitarSet performed chord data has an unsupported JAMS shape")


def discover_guitarset_sources(
    dataset_root: Path,
    *,
    annotation_root: Path | None = None,
    audio_root: Path | None = None,
) -> tuple[LocalTrackSource, ...]:
    """Pair mono microphone audio with JAMS and group repeated lead sheets."""

    root = dataset_root.resolve(strict=True)
    annotations = _resolve_directory(annotation_root or root / "annotations", root)
    audio = _resolve_directory(audio_root or root / "audio_mono-mic", root)
    if annotations is None or audio is None:
        raise ValueError("GuitarSet is missing its annotation or mono microphone directory")

    sources: list[LocalTrackSource] = []
    for annotation_path in sorted(annotations.glob("*.jams"), key=lambda path: path.name):
        match = _TRACK_PATTERN.fullmatch(annotation_path.stem)
        if match is None:
            raise ValueError(f"unexpected GuitarSet annotation filename: {annotation_path.name}")
        candidates = (
            audio / f"{annotation_path.stem}_mic.wav",
            audio / f"{annotation_path.stem}.wav",
        )
        audio_paths = [path for path in candidates if path.is_file()]
        if len(audio_paths) != 1:
            raise ValueError(f"GuitarSet audio is missing or ambiguous for {annotation_path.name}")
        lead_sheet = match.group("lead_sheet")
        sources.append(
            LocalTrackSource(
                dataset_id="guitarset",
                track_id=annotation_path.stem,
                work_id=lead_sheet,
                cover_group_id=lead_sheet,
                artist_id=match.group("player"),
                audio_path=audio_paths[0],
                annotation_path=annotation_path,
                duration_seconds=_wav_duration_seconds(audio_paths[0]),
            )
        )
    if not sources:
        raise ValueError("GuitarSet does not contain JAMS annotations")
    return tuple(sources)


def _resolve_directory(path: Path, root: Path) -> Path | None:
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return None
    if not resolved.is_dir() or not resolved.is_relative_to(root):
        return None
    return resolved


def _wav_duration_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as audio:
            frame_rate = audio.getframerate()
            frame_count = audio.getnframes()
    except (EOFError, wave.Error):
        raise ValueError(f"GuitarSet audio is not a readable WAV file: {path.name}") from None
    if frame_rate <= 0 or frame_count <= 0:
        raise ValueError(f"GuitarSet audio has an invalid duration: {path.name}")
    return frame_count / frame_rate
