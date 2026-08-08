from __future__ import annotations

import math
import os
import re
import shutil
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO, ParamSpec, Protocol, TypeVar

from museecho.analysis.decode import AudioProbe, decode_audio, probe_audio
from museecho.domain.models import EncryptedAudioMetadata, IssuedAccess
from museecho.domain.status import AnalysisJob

DEFAULT_MAX_UPLOAD_BYTES = 30 * 1024 * 1024
DEFAULT_MAX_DURATION_SECONDS = 600.0
COPY_CHUNK_BYTES = 64 * 1024
_ALLOWED_EXTENSIONS = {".wav": "wav", ".mp3": "mp3"}
_CANONICAL_MEDIA_TYPES = {"wav": "audio/wav", "mp3": "audio/mpeg"}
_UPLOAD_TEMP_PREFIX = "museecho-upload-"
_UPLOAD_OWNER_MARKER = ".owner"
_UPLOAD_OWNER_BYTES = b"MuseEcho temporary plaintext v1\n"
_UPLOAD_DIRECTORY_PATTERN = re.compile(rf"^{_UPLOAD_TEMP_PREFIX}[0-9a-f]{{32}}-[a-z0-9_]{{8}}$")

_VALIDATION_GATE = threading.Lock()
_TEMP_ROOT_INIT_LOCK = threading.Lock()
_PREPARED_TEMP_ROOTS: set[Path] = set()

_P = ParamSpec("_P")
_R = TypeVar("_R")


def _serialized_validation(function: Callable[_P, _R]) -> Callable[_P, _R]:
    @wraps(function)
    def locked(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with _VALIDATION_GATE:
            return function(*args, **kwargs)

    return locked


class UploadError(ValueError):
    code = "upload_failed"


class UploadTooLargeError(UploadError):
    code = "upload_too_large"


class UnsupportedAudioError(UploadError):
    code = "unsupported_audio"


class UploadRepository(Protocol):
    def add(self, job: AnalysisJob) -> None: ...
    def delete_cascade(self, analysis_id: uuid.UUID) -> None: ...


class UploadAudioStore(Protocol):
    def write(
        self, analysis_id: uuid.UUID, source: BinaryIO, media_type: str
    ) -> EncryptedAudioMetadata: ...
    def delete(self, metadata: EncryptedAudioMetadata) -> None: ...


class UploadAccessService(Protocol):
    def issue(self, analysis_id: uuid.UUID, expires_at: datetime) -> IssuedAccess: ...


class AnalysisQueue(Protocol):
    def submit(self, analysis_id: uuid.UUID) -> None: ...


@dataclass(frozen=True)
class SubmittedAnalysis:
    job: AnalysisJob
    access: IssuedAccess


class FFmpegAudioValidator:
    """Validate both container metadata and an actual bounded decode."""

    def __init__(
        self,
        *,
        max_duration_seconds: float = DEFAULT_MAX_DURATION_SECONDS,
        ffprobe_executable: str = "ffprobe",
        ffmpeg_executable: str = "ffmpeg",
    ) -> None:
        if (
            not math.isfinite(max_duration_seconds)
            or max_duration_seconds <= 0
            or max_duration_seconds > DEFAULT_MAX_DURATION_SECONDS
        ):
            raise ValueError("max_duration_seconds must be within the supported limit")
        self._max_duration_seconds = max_duration_seconds
        self._ffprobe_executable = ffprobe_executable
        self._ffmpeg_executable = ffmpeg_executable

    @_serialized_validation
    def __call__(self, path: Path) -> AudioProbe:
        probe = probe_audio(
            path,
            max_duration_seconds=self._max_duration_seconds,
            ffprobe_executable=self._ffprobe_executable,
        )
        decode_audio(
            path,
            max_duration_seconds=self._max_duration_seconds,
            ffprobe_executable=self._ffprobe_executable,
            ffmpeg_executable=self._ffmpeg_executable,
        )
        return probe


class UploadSubmissionService:
    def __init__(
        self,
        *,
        repository: UploadRepository,
        audio_store: UploadAudioStore,
        access_service: UploadAccessService,
        queue: AnalysisQueue,
        temp_root: Path,
        validator: Callable[[Path], AudioProbe] | None = None,
        max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
        access_ttl: timedelta = timedelta(hours=24),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if max_bytes <= 0 or max_bytes > DEFAULT_MAX_UPLOAD_BYTES:
            raise ValueError("max_bytes must be within the supported limit")
        if access_ttl <= timedelta(0):
            raise ValueError("access_ttl must be positive")
        self._repository = repository
        self._audio_store = audio_store
        self._access_service = access_service
        self._queue = queue
        self._temp_root = _prepare_temp_root(temp_root)
        self._validator = validator or FFmpegAudioValidator()
        self._max_bytes = max_bytes
        self._access_ttl = access_ttl
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def submit(
        self, source: BinaryIO, *, filename: str, media_type: str | None
    ) -> SubmittedAnalysis:
        expected_format = _expected_format(filename)
        prefix = f"{_UPLOAD_TEMP_PREFIX}{uuid.uuid4().hex}-"
        with TemporaryDirectory(prefix=prefix, dir=self._temp_root) as directory:
            isolated_directory = Path(directory)
            _write_upload_owner_marker(isolated_directory)
            isolated_path = isolated_directory / uuid.uuid4().hex
            _copy_bounded(source, isolated_path, self._max_bytes)
            probe = self._validator(isolated_path)
            detected_formats = set(probe.format_name.split(","))
            if expected_format not in detected_formats:
                from museecho.analysis.decode import InvalidAudioError

                raise InvalidAudioError("file extension does not match detected audio format")
            canonical_media_type = _CANONICAL_MEDIA_TYPES[expected_format]
            return self._persist_validated(
                isolated_path,
                canonical_media_type=canonical_media_type,
            )

    def _persist_validated(
        self,
        isolated_path: Path,
        *,
        canonical_media_type: str,
    ) -> SubmittedAnalysis:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise ValueError("clock must return an aware UTC datetime")
        expires_at = now + self._access_ttl
        job = AnalysisJob(created_at=now, expires_at=expires_at)
        self._repository.add(job)
        metadata: EncryptedAudioMetadata | None = None
        try:
            with isolated_path.open("rb") as source:
                metadata = self._audio_store.write(job.id, source, canonical_media_type)
            access = self._access_service.issue(job.id, expires_at)
            self._queue.submit(job.id)
            return SubmittedAnalysis(job=job, access=access)
        except Exception:
            if metadata is not None:
                try:
                    self._audio_store.delete(metadata)
                except Exception:
                    pass
            try:
                self._repository.delete_cascade(job.id)
            except Exception:
                pass
            raise


def _prepare_temp_root(root: Path) -> Path:
    with _TEMP_ROOT_INIT_LOCK:
        try:
            if _is_link(root):
                raise UploadError("temporary upload root cannot be a link")
            root.mkdir(parents=True, exist_ok=True)
            resolved = root.resolve(strict=True)
            if not resolved.is_dir() or _is_link(root):
                raise UploadError("temporary upload root is invalid")
            if resolved not in _PREPARED_TEMP_ROOTS:
                _remove_abandoned_uploads(resolved)
                if os.name == "posix":
                    resolved.chmod(0o700)
                _PREPARED_TEMP_ROOTS.add(resolved)
            return resolved
        except UploadError:
            raise
        except OSError:
            raise UploadError("temporary upload root could not be prepared") from None


def _write_upload_owner_marker(directory: Path) -> None:
    try:
        with (directory / _UPLOAD_OWNER_MARKER).open("xb") as marker:
            marker.write(_UPLOAD_OWNER_BYTES)
            marker.flush()
            os.fsync(marker.fileno())
    except OSError:
        raise UploadError("temporary upload ownership could not be recorded") from None


def _has_upload_owner_marker(directory: Path) -> bool:
    marker = directory / _UPLOAD_OWNER_MARKER
    try:
        if _is_link(marker) or not marker.is_file():
            return False
        with marker.open("rb") as source:
            return source.read(len(_UPLOAD_OWNER_BYTES) + 1) == _UPLOAD_OWNER_BYTES
    except OSError:
        return False


def _remove_abandoned_uploads(root: Path) -> None:
    for entry in root.iterdir():
        if _UPLOAD_DIRECTORY_PATTERN.fullmatch(entry.name) is None:
            continue
        try:
            if _is_link(entry) or not entry.is_dir():
                continue
            if not _has_upload_owner_marker(entry):
                continue
            shutil.rmtree(entry)
        except FileNotFoundError:
            continue
        except OSError:
            raise UploadError("abandoned plaintext upload could not be removed") from None


def _is_junction(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    return bool(checker is not None and checker())


def _is_link(path: Path) -> bool:
    return path.is_symlink() or _is_junction(path)


def _expected_format(filename: str) -> str:
    if (
        not filename
        or "\x00" in filename
        or len(filename) > 255
        or "/" in filename
        or "\\" in filename
        or Path(filename).name != filename
    ):
        raise UnsupportedAudioError("only unambiguous WAV and MP3 filenames are supported")
    path = Path(filename)
    if not path.stem or path.stem == ".":
        raise UnsupportedAudioError("only unambiguous WAV and MP3 filenames are supported")
    try:
        return _ALLOWED_EXTENSIONS[path.suffix.lower()]
    except KeyError:
        raise UnsupportedAudioError("only WAV and MP3 uploads are supported") from None


def _copy_bounded(source: BinaryIO, destination: Path, max_bytes: int) -> None:
    total = 0
    try:
        with destination.open("xb") as output:
            while True:
                chunk = source.read(COPY_CHUNK_BYTES)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise UploadError("upload stream must provide bytes")
                total += len(chunk)
                if total > max_bytes:
                    raise UploadTooLargeError("upload exceeds the supported size")
                output.write(chunk)
            if total == 0:
                from museecho.analysis.decode import InvalidAudioError

                raise InvalidAudioError("audio upload is empty")
            output.flush()
            os.fsync(output.fileno())
    except OSError:
        raise UploadError("upload could not be staged") from None


__all__ = [
    "DEFAULT_MAX_DURATION_SECONDS",
    "DEFAULT_MAX_UPLOAD_BYTES",
    "FFmpegAudioValidator",
    "SubmittedAnalysis",
    "UnsupportedAudioError",
    "UploadError",
    "UploadSubmissionService",
    "UploadTooLargeError",
]
