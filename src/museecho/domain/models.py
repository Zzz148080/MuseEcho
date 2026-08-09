from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Any


def _validate_finite(value: float, name: str) -> None:
    if not isfinite(value):
        raise ValueError(f"{name} must be finite")


def _validate_interval(start: float, end: float) -> None:
    _validate_finite(start, "start_seconds")
    _validate_finite(end, "end_seconds")
    if start < 0.0 or end <= start:
        raise ValueError("interval must satisfy 0 <= start_seconds < end_seconds")


def _validate_confidence(value: float | None, name: str = "confidence") -> None:
    if value is not None:
        _validate_finite(value, name)
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be between 0.0 and 1.0")


def _validate_utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be an aware UTC datetime")


def _validate_json(value: Any, name: str) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain valid JSON values") from exc


@dataclass
class AccessGrant:
    analysis_id: uuid.UUID
    token_hash: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None

    def __post_init__(self) -> None:
        _validate_utc(self.created_at, "created_at")
        _validate_utc(self.expires_at, "expires_at")
        if self.revoked_at is not None:
            _validate_utc(self.revoked_at, "revoked_at")
            if self.revoked_at < self.created_at:
                raise ValueError("revoked_at cannot be before created_at")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")


@dataclass(frozen=True)
class IssuedAccess:
    raw_token: str
    grant: AccessGrant

    def __post_init__(self) -> None:
        if not self.raw_token:
            raise ValueError("raw_token cannot be empty")


@dataclass
class EncryptedAudio:
    analysis_id: uuid.UUID
    cipher_path: str
    wrapped_data_key: bytes
    chunk_size: int
    chunk_count: int
    plaintext_size: int
    media_type: str
    sha256: str

    def __post_init__(self) -> None:
        if self.chunk_size <= 0 or self.chunk_count <= 0 or self.plaintext_size < 0:
            raise ValueError("encrypted audio sizes must be valid")


EncryptedAudioMetadata = EncryptedAudio


@dataclass(frozen=True)
class DecodedAudio:
    pcm: bytes
    sample_rate: int
    channels: int

    def __post_init__(self) -> None:
        if not self.pcm:
            raise ValueError("pcm cannot be empty")
        if self.sample_rate <= 0 or self.channels != 1:
            raise ValueError("decoded audio must be positive-rate mono PCM")
        if len(self.pcm) % 4 != 0:
            raise ValueError("decoded PCM must contain complete float32 samples")
        if sys.byteorder != "little":
            raise ValueError("decoded PCM requires a little-endian host")
        if not all(isfinite(sample) for sample in self.samples):
            raise ValueError("decoded PCM samples must be finite")

    @property
    def samples(self) -> memoryview[float]:
        return memoryview(self.pcm).cast("f")

    @property
    def duration_seconds(self) -> float:
        return len(self.pcm) / (4 * self.sample_rate)


@dataclass
class TrackAnalysis:
    analysis_id: uuid.UUID
    duration_seconds: float
    sample_rate: int
    channels: int
    bpm: float | None
    bpm_confidence: float | None
    key_tonic: str | None
    mode: str | None
    key_confidence: float | None
    time_signature: str | None
    time_signature_confidence: float | None
    summary_json: dict[str, Any] | None

    def __post_init__(self) -> None:
        _validate_finite(self.duration_seconds, "duration_seconds")
        if self.duration_seconds <= 0.0:
            raise ValueError("duration_seconds must be positive")
        if self.sample_rate <= 0 or self.channels <= 0:
            raise ValueError("sample_rate and channels must be positive")
        if self.bpm is not None:
            _validate_finite(self.bpm, "bpm")
            if self.bpm <= 0.0:
                raise ValueError("bpm must be positive")
        _validate_confidence(self.bpm_confidence, "bpm_confidence")
        _validate_confidence(self.key_confidence, "key_confidence")
        _validate_confidence(self.time_signature_confidence, "time_signature_confidence")
        if self.summary_json is not None:
            _validate_json(self.summary_json, "summary_json")


@dataclass
class SectionEvent:
    id: uuid.UUID
    analysis_id: uuid.UUID
    start_seconds: float
    end_seconds: float
    label: str
    confidence: float
    algorithm: str

    def __post_init__(self) -> None:
        _validate_interval(self.start_seconds, self.end_seconds)
        _validate_confidence(self.confidence)


@dataclass
class ChordEvent:
    id: uuid.UUID
    analysis_id: uuid.UUID
    start_seconds: float
    end_seconds: float
    symbol: str
    confidence: float
    algorithm: str
    theory_json: dict[str, Any] | None

    def __post_init__(self) -> None:
        _validate_interval(self.start_seconds, self.end_seconds)
        _validate_confidence(self.confidence)
        if self.theory_json is not None:
            _validate_json(self.theory_json, "theory_json")


@dataclass
class TimeSeries:
    analysis_id: uuid.UUID
    kind: str
    resolution_seconds: float
    points_json: list[float]
    algorithm: str

    def __post_init__(self) -> None:
        _validate_finite(self.resolution_seconds, "resolution_seconds")
        if self.resolution_seconds <= 0.0:
            raise ValueError("resolution_seconds must be positive")
        for point in self.points_json:
            _validate_finite(point, "points_json value")


@dataclass
class Evidence:
    id: uuid.UUID
    analysis_id: uuid.UUID
    kind: str
    start_seconds: float
    end_seconds: float
    value_json: dict[str, Any] | None
    confidence: float
    algorithm: str
    eligible_for_llm: bool

    def __post_init__(self) -> None:
        _validate_interval(self.start_seconds, self.end_seconds)
        _validate_confidence(self.confidence)
        if self.value_json is not None:
            _validate_json(self.value_json, "value_json")

    @property
    def public_value(self) -> object:
        if self.value_json is None:
            return "unknown"
        return self.value_json.get("public_value", self.value_json)


@dataclass
class Explanation:
    id: uuid.UUID
    analysis_id: uuid.UUID
    segment_start: float
    segment_end: float
    question_digest: str
    evidence_ids_json: list[str]
    mode: str
    text: str
    created_at: datetime

    def __post_init__(self) -> None:
        _validate_interval(self.segment_start, self.segment_end)
        _validate_utc(self.created_at, "created_at")


@dataclass(frozen=True)
class ExplanationDraft:
    mode: str
    text: str
    evidence_ids: tuple[uuid.UUID, ...]

    def __post_init__(self) -> None:
        if not self.mode or not self.text:
            raise ValueError("mode and text cannot be empty")


@dataclass(frozen=True)
class AnalysisResult:
    track: TrackAnalysis
    sections: tuple[SectionEvent, ...] = ()
    chords: tuple[ChordEvent, ...] = ()
    time_series: tuple[TimeSeries, ...] = ()
    evidence: tuple[Evidence, ...] = ()

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        self.track.__post_init__()
        for section in self.sections:
            section.__post_init__()
        for chord in self.chords:
            chord.__post_init__()
        for series in self.time_series:
            series.__post_init__()
        for evidence in self.evidence:
            evidence.__post_init__()

        mismatched = (
            any(child.analysis_id != self.track.analysis_id for child in self.sections)
            or any(child.analysis_id != self.track.analysis_id for child in self.chords)
            or any(child.analysis_id != self.track.analysis_id for child in self.time_series)
            or any(child.analysis_id != self.track.analysis_id for child in self.evidence)
        )
        if mismatched:
            raise ValueError("every result child must have the track analysis_id")

        out_of_bounds = (
            any(child.end_seconds > self.track.duration_seconds for child in self.sections)
            or any(child.end_seconds > self.track.duration_seconds for child in self.chords)
            or any(child.end_seconds > self.track.duration_seconds for child in self.evidence)
        )
        if out_of_bounds:
            raise ValueError("result interval cannot exceed track duration")
