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


class DatasetAdapter(ABC):
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
        _validate_intervals(intervals, source.duration_seconds)
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
            reader = csv.DictReader(source)
            if reader.fieldnames is None or not {"start", "end", "chord"}.issubset(
                reader.fieldnames
            ):
                raise ValueError("annotation interval CSV must contain start, end, and chord")
            for line_number, row in enumerate(reader, start=2):
                yield _interval(row["start"], row["end"], row["chord"], line_number)


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
    for item in intervals:
        if (
            not math.isfinite(item.start_seconds)
            or not math.isfinite(item.end_seconds)
            or item.start_seconds < 0
            or item.start_seconds >= item.end_seconds
            or item.start_seconds < previous_end
            or item.end_seconds > duration_seconds + 1e-6
        ):
            raise ValueError("annotation interval is invalid or overlapping")
        previous_end = item.end_seconds


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
