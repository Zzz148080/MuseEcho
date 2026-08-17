from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from museecho_ml.labels import CanonicalChord


@dataclass(frozen=True)
class LocalTrackSource:
    dataset_id: str
    track_id: str
    work_id: str
    cover_group_id: str
    artist_id: str | None
    audio_path: Path
    annotation_path: Path
    duration_seconds: float

    def __post_init__(self) -> None:
        identifiers = (self.dataset_id, self.track_id, self.work_id, self.cover_group_id)
        if any(not isinstance(value, str) or not value.strip() for value in identifiers):
            raise ValueError("track manifest identifiers must be non-empty strings")
        if self.artist_id is not None and (
            not isinstance(self.artist_id, str) or not self.artist_id.strip()
        ):
            raise ValueError("track manifest artist_id must be null or a non-empty string")
        if not math.isfinite(self.duration_seconds) or self.duration_seconds <= 0:
            raise ValueError("track manifest duration must be finite and positive")


@dataclass(frozen=True)
class ChordInterval:
    start_seconds: float
    end_seconds: float
    chord: CanonicalChord


@dataclass(frozen=True)
class ConversionStats:
    total_intervals: int
    out_of_vocabulary_intervals: int
    clipped_intervals: int = 0


@dataclass(frozen=True)
class AdaptedTrack:
    source: LocalTrackSource
    audio_sha256: str
    annotation_sha256: str
    intervals: tuple[ChordInterval, ...]
    conversion: ConversionStats
