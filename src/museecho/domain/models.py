from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class AnalysisJobRecord:
    id: uuid.UUID
    status: str
    stage: str
    progress: float
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    error_code: str | None
    retry_count: int
    pipeline_version: str | None
    source_kind: str


@dataclass
class AccessGrant:
    analysis_id: uuid.UUID
    token_hash: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


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


@dataclass
class SectionEvent:
    id: uuid.UUID
    analysis_id: uuid.UUID
    start_seconds: float
    end_seconds: float
    label: str
    confidence: float
    algorithm: str


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


@dataclass
class TimeSeries:
    analysis_id: uuid.UUID
    kind: str
    resolution_seconds: float
    points_json: list[float]
    algorithm: str


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
