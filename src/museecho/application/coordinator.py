from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from museecho.analysis.chords import estimate_chords
from museecho.analysis.decode import decode_audio
from museecho.analysis.signal_features import extract_signal_features
from museecho.analysis.structure import segment_structure
from museecho.analysis.tonality import estimate_tonality
from museecho.application.evidence import build_evidence
from museecho.domain.models import (
    AnalysisResult,
    ChordEvent,
    EncryptedAudioMetadata,
    SectionEvent,
    TimeSeries,
    TrackAnalysis,
)
from museecho.domain.ports import AnalysisRepository, EncryptedAudioStore
from museecho.domain.status import AnalysisJob, AnalysisStage
from museecho.theory.functions import explain_chord

PIPELINE_VERSION = "museecho-analysis-v1"
_TEMP_PREFIX = "museecho-analysis-"
_OWNER_MARKER = ".owner"
_OWNER_BYTES = b"MuseEcho analysis plaintext v1\n"
_TEMP_PATTERN = re.compile(r"^museecho-analysis-[0-9a-f]{32}-[a-z0-9_]{8}$")
_TEMP_ROOT_LOCK = threading.Lock()
_PREPARED_TEMP_ROOTS: set[Path] = set()


class AnalysisInputUnavailableError(RuntimeError):
    code = "analysis_input_unavailable"


class AnalysisWorkspaceError(RuntimeError):
    code = "analysis_workspace_unavailable"


class AnalysisCoordinator:
    """Run the deterministic analysis pipeline and persist one validated aggregate."""

    def __init__(
        self,
        *,
        repository: AnalysisRepository,
        audio_store: EncryptedAudioStore,
        temp_root: Path,
        ffprobe_executable: str = "ffprobe",
        ffmpeg_executable: str = "ffmpeg",
        stage_observer: Callable[[uuid.UUID, AnalysisStage, float], None] | None = None,
        timer: Callable[[], float] | None = None,
    ) -> None:
        self._repository = repository
        self._audio_store = audio_store
        self._temp_root = _prepare_temp_root(temp_root)
        self._ffprobe_executable = ffprobe_executable
        self._ffmpeg_executable = ffmpeg_executable
        self._stage_observer = stage_observer
        self._timer = timer or time.perf_counter

    def __call__(self, analysis_id: uuid.UUID) -> None:
        job = self._require_runnable_job(analysis_id)
        if job.status.is_terminal:
            return
        stage_started = self._timer()
        metadata = self._repository.get_encrypted_audio(analysis_id)
        if metadata is None or not metadata.wrapped_data_key:
            raise AnalysisInputUnavailableError("encrypted analysis input is unavailable")
        job.pipeline_version = PIPELINE_VERSION
        self._repository.update(job)
        self._checkpoint(job, AnalysisStage.VALIDATING, stage_started)

        stage_started = self._timer()
        suffix = ".mp3" if metadata.media_type == "audio/mpeg" else ".wav"
        prefix = f"{_TEMP_PREFIX}{uuid.uuid4().hex}-"
        with tempfile.TemporaryDirectory(prefix=prefix, dir=self._temp_root) as raw:
            _write_owner_marker(Path(raw))
            source_path = Path(raw) / f"source{suffix}"
            self._materialize(metadata, source_path)
            decoded = decode_audio(
                source_path,
                ffprobe_executable=self._ffprobe_executable,
                ffmpeg_executable=self._ffmpeg_executable,
            )
        self._checkpoint(job, AnalysisStage.DECODING, stage_started)

        stage_started = self._timer()
        signal = extract_signal_features(decoded.samples, decoded.sample_rate)
        self._checkpoint(job, AnalysisStage.RHYTHM, stage_started)
        stage_started = self._timer()
        tonality = estimate_tonality(decoded.samples, decoded.sample_rate)
        self._checkpoint(job, AnalysisStage.TONALITY, stage_started)
        stage_started = self._timer()
        structure = segment_structure(decoded.samples, decoded.sample_rate)
        self._checkpoint(job, AnalysisStage.STRUCTURE, stage_started)
        stage_started = self._timer()
        estimated_chords = estimate_chords(
            decoded.samples,
            decoded.sample_rate,
            key_tonic=tonality.tonic,
            key_mode=tonality.mode,
        )
        self._checkpoint(job, AnalysisStage.CHORDS, stage_started)

        stage_started = self._timer()
        sections = tuple(
            SectionEvent(
                id=uuid.uuid4(),
                analysis_id=analysis_id,
                start_seconds=item.start_seconds,
                end_seconds=item.end_seconds,
                label=item.label or "unknown",
                confidence=item.confidence or 0.0,
                algorithm=item.algorithm,
            )
            for item in structure
        )
        chords = tuple(
            ChordEvent(
                id=uuid.uuid4(),
                analysis_id=analysis_id,
                start_seconds=item.start_seconds,
                end_seconds=item.end_seconds,
                symbol=item.symbol or "unknown",
                confidence=item.confidence or 0.0,
                algorithm=item.algorithm,
                theory_json=(
                    explain_chord(item.symbol, tonality.tonic, tonality.mode).to_dict()
                    if item.symbol is not None
                    else None
                ),
            )
            for item in estimated_chords
        )
        summary = {
            "source_kind": job.source_kind.value,
            "pipeline_version": PIPELINE_VERSION,
            "signal_version": signal.config_version,
            "waveform": {
                "resolution_seconds": signal.waveform.resolution_seconds,
                "minimums": list(signal.waveform.minimums),
                "maximums": list(signal.waveform.maximums),
                "algorithm": signal.waveform.algorithm,
            },
            "beat_positions_seconds": list(signal.beat_positions_seconds),
            "energy_changes": [
                {
                    "timestamp_seconds": item.timestamp_seconds,
                    "direction": item.direction,
                    "magnitude": item.magnitude,
                    "confidence": item.confidence,
                    "algorithm": item.algorithm,
                }
                for item in signal.energy_changes
            ],
        }
        track = TrackAnalysis(
            analysis_id=analysis_id,
            duration_seconds=decoded.duration_seconds,
            sample_rate=decoded.sample_rate,
            channels=decoded.channels,
            bpm=signal.bpm,
            bpm_confidence=signal.bpm_confidence,
            key_tonic=tonality.tonic,
            mode=tonality.mode,
            key_confidence=tonality.confidence,
            time_signature=None,
            time_signature_confidence=None,
            summary_json=summary,
        )
        partial = AnalysisResult(
            track=track,
            sections=sections,
            chords=chords,
            time_series=(
                TimeSeries(
                    analysis_id,
                    "energy",
                    signal.energy.resolution_seconds,
                    list(signal.energy.points),
                    signal.energy.algorithm,
                ),
            ),
        )
        result = AnalysisResult(
            track=track,
            sections=sections,
            chords=chords,
            time_series=partial.time_series,
            evidence=build_evidence(partial),
        )
        self._checkpoint(job, AnalysisStage.EVIDENCE, stage_started)
        self._repository.save_result(result)

    def _require_runnable_job(self, analysis_id: uuid.UUID) -> AnalysisJob:
        job = self._repository.get(analysis_id)
        if job is None:
            raise KeyError(str(analysis_id))
        if job.status.is_terminal:
            return job
        return job

    def _checkpoint(
        self,
        job: AnalysisJob,
        stage: AnalysisStage,
        started_at: float,
    ) -> None:
        if job.status.is_terminal:
            return
        order = (
            AnalysisStage.QUEUED,
            AnalysisStage.VALIDATING,
            AnalysisStage.DECODING,
            AnalysisStage.RHYTHM,
            AnalysisStage.TONALITY,
            AnalysisStage.STRUCTURE,
            AnalysisStage.CHORDS,
            AnalysisStage.EVIDENCE,
        )
        if order.index(job.stage) < order.index(stage):
            job.advance_to(stage)
            self._repository.update(job)
        if self._stage_observer is not None:
            self._stage_observer(job.id, stage, max(0.0, self._timer() - started_at))

    def _materialize(self, metadata: EncryptedAudioMetadata, path: Path) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as target:
            for start in range(0, metadata.plaintext_size, metadata.chunk_size):
                end = min(metadata.plaintext_size, start + metadata.chunk_size)
                target.write(self._audio_store.read_range(metadata, start, end))
            target.flush()
            os.fsync(target.fileno())


def _prepare_temp_root(root: Path) -> Path:
    with _TEMP_ROOT_LOCK:
        try:
            if _is_link(root):
                raise AnalysisWorkspaceError("analysis temporary root cannot be a link")
            root.mkdir(parents=True, exist_ok=True)
            resolved = root.resolve(strict=True)
            if not resolved.is_dir() or _is_link(root):
                raise AnalysisWorkspaceError("analysis temporary root is invalid")
            if resolved not in _PREPARED_TEMP_ROOTS:
                _remove_abandoned_plaintext(resolved)
                if os.name == "posix":
                    resolved.chmod(0o700)
                _PREPARED_TEMP_ROOTS.add(resolved)
            return resolved
        except AnalysisWorkspaceError:
            raise
        except OSError:
            raise AnalysisWorkspaceError("analysis temporary root could not be prepared") from None


def _write_owner_marker(directory: Path) -> None:
    marker = directory / _OWNER_MARKER
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(marker, flags, 0o600)
        with os.fdopen(descriptor, "wb") as target:
            target.write(_OWNER_BYTES)
            target.flush()
            os.fsync(target.fileno())
    except OSError:
        raise AnalysisWorkspaceError("analysis temporary ownership could not be recorded") from None


def _remove_abandoned_plaintext(root: Path) -> None:
    for entry in root.iterdir():
        if _TEMP_PATTERN.fullmatch(entry.name) is None:
            continue
        try:
            if _is_link(entry) or not entry.is_dir():
                continue
            marker = entry / _OWNER_MARKER
            if _is_link(marker) or not marker.is_file():
                continue
            with marker.open("rb") as source:
                marker_bytes = source.read(len(_OWNER_BYTES) + 1)
            if marker_bytes != _OWNER_BYTES:
                continue
            shutil.rmtree(entry)
        except FileNotFoundError:
            continue
        except OSError:
            raise AnalysisWorkspaceError(
                "abandoned analysis plaintext could not be removed"
            ) from None


def _is_link(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(checker is not None and checker())


__all__ = [
    "AnalysisCoordinator",
    "AnalysisInputUnavailableError",
    "AnalysisWorkspaceError",
    "PIPELINE_VERSION",
]
