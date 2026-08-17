from __future__ import annotations

import csv
import hashlib
import math
from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path

from museecho_ml.data.manifest import (
    AdaptedTrack,
    ChordInterval,
    ConversionStats,
    LocalTrackSource,
)
from museecho_ml.labels import parse_annotation

_MAX_FINAL_ROUNDING_OVERRUN_SECONDS = 0.05


class DatasetAdapter(ABC):
    max_final_overrun_seconds = _MAX_FINAL_ROUNDING_OVERRUN_SECONDS

    def __init__(self, *, dataset_id: str) -> None:
        if not isinstance(dataset_id, str) or not dataset_id.strip():
            raise ValueError("dataset_id must be a non-empty string")
        self.dataset_id = dataset_id

    def adapt(self, source: LocalTrackSource, dataset_root: Path) -> AdaptedTrack:
        if source.dataset_id != self.dataset_id:
            raise ValueError("track dataset_id does not match the adapter")
        root = dataset_root.resolve(strict=True)
        audio = _resolve_local_file(source.audio_path, root)
        annotation = _resolve_local_file(source.annotation_path, root)
        intervals = tuple(self._read_intervals(annotation))
        intervals, clipped_intervals = _clip_final_rounding_overrun(
            intervals, source.duration_seconds, self.max_final_overrun_seconds
        )
        try:
            _validate_intervals(intervals, source.duration_seconds)
        except ValueError as error:
            raise ValueError(f"track {source.track_id}: {error}") from None
        return AdaptedTrack(
            source=source,
            audio_sha256=_sha256(audio),
            annotation_sha256=_sha256(annotation),
            intervals=intervals,
            conversion=ConversionStats(
                total_intervals=len(intervals),
                out_of_vocabulary_intervals=sum(
                    item.chord.root == "X" and item.chord.mapping_reason is not None
                    for item in intervals
                ),
                clipped_intervals=clipped_intervals,
            ),
        )

    @abstractmethod
    def _read_intervals(self, annotation: Path) -> Iterable[ChordInterval]:
        raise NotImplementedError


class LabChordAdapter(DatasetAdapter):
    def _read_intervals(self, annotation: Path) -> Iterable[ChordInterval]:
        for line_number, raw_line in enumerate(
            annotation.read_text(encoding="utf-8-sig").splitlines(), start=1
        ):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split(maxsplit=2)
            if len(fields) != 3:
                raise ValueError(f"annotation interval on line {line_number} is malformed")
            yield _interval(fields[0], fields[1], fields[2], line_number)


class CsvChordAdapter(DatasetAdapter):
    def _read_intervals(self, annotation: Path) -> Iterable[ChordInterval]:
        with annotation.open("r", encoding="utf-8-sig", newline="") as source:
            header = source.readline()
            source.seek(0)
            delimiter = ";" if header.count(";") > header.count(",") else ","
            reader = csv.DictReader(source, delimiter=delimiter)
            fieldnames = set(reader.fieldnames or ())
            start_column = "start" if "start" in fieldnames else "t_start"
            end_column = "end" if "end" in fieldnames else "t_end"
            chord_column = "chord" if "chord" in fieldnames else "shorthand"
            if not {start_column, end_column, chord_column}.issubset(fieldnames):
                raise ValueError(
                    "annotation interval CSV must contain start/end or t_start/t_end "
                    "and chord or shorthand"
                )
            for line_number, row in enumerate(reader, start=2):
                yield _interval(
                    row[start_column], row[end_column], row[chord_column], line_number
                )


def _interval(start: str, end: str, chord: str, line_number: int) -> ChordInterval:
    try:
        start_seconds = float(start)
        end_seconds = float(end)
        parsed = parse_annotation(chord)
    except (TypeError, ValueError):
        raise ValueError(f"annotation interval on line {line_number} is invalid") from None
    return ChordInterval(start_seconds, end_seconds, parsed)


def _resolve_local_file(path: Path, root: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise ValueError("dataset source file does not exist") from None
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError("dataset source path must remain inside the declared dataset root")
    return resolved


def _validate_intervals(intervals: tuple[ChordInterval, ...], duration_seconds: float) -> None:
    if not intervals:
        raise ValueError("annotation intervals cannot be empty")
    previous_end = 0.0
    for index, item in enumerate(intervals, start=1):
        if (
            not math.isfinite(item.start_seconds)
            or not math.isfinite(item.end_seconds)
            or item.start_seconds < 0
            or item.start_seconds >= item.end_seconds
            or item.start_seconds < previous_end
            or item.end_seconds > duration_seconds + 1e-6
        ):
            raise ValueError(
                "annotation interval "
                f"{index} is invalid or overlapping "
                f"({item.start_seconds}, {item.end_seconds}, previous_end={previous_end}, "
                f"duration={duration_seconds})"
            )
        previous_end = item.end_seconds


def _clip_final_rounding_overrun(
    intervals: tuple[ChordInterval, ...],
    duration_seconds: float,
    maximum_overrun_seconds: float,
) -> tuple[tuple[ChordInterval, ...], int]:
    if not intervals:
        return intervals, 0
    final = intervals[-1]
    overrun = final.end_seconds - duration_seconds
    if (
        0 < overrun <= maximum_overrun_seconds
        and final.start_seconds < duration_seconds
    ):
        return (
            intervals[:-1]
            + (ChordInterval(final.start_seconds, duration_seconds, final.chord),),
            1,
        )
    return intervals, 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
