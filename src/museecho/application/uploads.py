from __future__ import annotations

import math
import os
import re
import shutil
import struct
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import BinaryIO, ParamSpec, Protocol, TypeVar

from museecho.analysis.decode import AudioProbe, InvalidAudioError, decode_audio, probe_audio
from museecho.audio_formats import (
    AUDIO_FORMATS,
    AudioFormat,
    ValidatorKind,
    audio_format_for_suffix,
    probe_matches_audio_format,
)
from museecho.domain.models import EncryptedAudioMetadata, IssuedAccess
from museecho.domain.status import AnalysisJob

DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_DURATION_SECONDS = 600.0
COPY_CHUNK_BYTES = 64 * 1024
_UPLOAD_TEMP_PREFIX = "museecho-upload-"
_UPLOAD_OWNER_MARKER = ".owner"
_UPLOAD_OWNER_BYTES = b"MuseEcho temporary plaintext v1\n"
_UPLOAD_DIRECTORY_PATTERN = re.compile(rf"^{_UPLOAD_TEMP_PREFIX}[0-9a-f]{{32}}-[a-z0-9_]{{8}}$")
_MPEG1_LAYER_THREE_BITRATES_KBPS = (
    0,
    32,
    40,
    48,
    56,
    64,
    80,
    96,
    112,
    128,
    160,
    192,
    224,
    256,
    320,
)
_MPEG2_LAYER_THREE_BITRATES_KBPS = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)
_MPEG1_SAMPLE_RATES = (44_100, 48_000, 32_000)

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


@dataclass(frozen=True)
class _LayerThreeHeader:
    version: int
    sample_rate: int
    channels: int
    frame_size: int


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
    def __call__(self, path: Path, audio_format: AudioFormat) -> AudioProbe:
        _validate_audio_signature(path, audio_format)
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


def _validate_audio_signature(path: Path, audio_format: AudioFormat) -> None:
    try:
        with path.open("rb") as source:
            header = source.read(12)
            _SIGNATURE_VALIDATORS[audio_format.validator_kind](source, header)
    except InvalidAudioError:
        raise
    except OSError:
        raise InvalidAudioError("audio file signature could not be read") from None


def _validate_wave_signature(source: BinaryIO, header: bytes) -> None:
    if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
        raise InvalidAudioError("audio file signature is invalid")
    _validate_wave_format(source, header)


def _validate_flac_header(source: BinaryIO, header: bytes) -> None:
    if header[:4] != b"fLaC":
        raise InvalidAudioError("audio file signature is invalid")
    _validate_flac_signature(source)


def _validate_iso_bmff_header(source: BinaryIO, header: bytes) -> None:
    if len(header) < 12 or header[4:8] != b"ftyp":
        raise InvalidAudioError("audio file signature is invalid")
    _validate_iso_bmff_signature(source, header)


def _validate_adts_header(source: BinaryIO, header: bytes) -> None:
    if len(header) < 7 or header[0] != 0xFF or header[1] & 0xF6 != 0xF0:
        raise InvalidAudioError("audio file signature is invalid")
    _validate_adts_signature(source)


def _validate_ogg_header(source: BinaryIO, header: bytes) -> None:
    if header[:4] != b"OggS":
        raise InvalidAudioError("audio file signature is invalid")
    _validate_ogg_signature(source)


def _validate_mp3_signature(source: BinaryIO, header: bytes) -> None:
    if header[:3] == b"ID3":
        if len(header) < 10 or header[3] not in (2, 3, 4) or header[4] == 0xFF:
            raise InvalidAudioError("audio file signature is invalid")
        allowed_flags = {2: 0xC0, 3: 0xE0, 4: 0xF0}[header[3]]
        if header[5] & ~allowed_flags or any(value & 0x80 for value in header[6:10]):
            raise InvalidAudioError("audio file signature is invalid")
        tag_size = 0
        for value in header[6:10]:
            tag_size = (tag_size << 7) | value
        frame_offset = 10 + tag_size
        if header[3] == 4 and header[5] & 0x10:
            source.seek(frame_offset)
            footer = source.read(10)
            if footer[:3] != b"3DI" or footer[3:] != header[3:10]:
                raise InvalidAudioError("audio file signature is invalid")
            frame_offset += 10
    else:
        frame_offset = 0
    source.seek(0, os.SEEK_END)
    _validate_layer_three_frames(source, frame_offset, source.tell())


def _validate_flac_signature(source: BinaryIO) -> None:
    source.seek(0, os.SEEK_END)
    file_size = source.tell()
    position = 4
    first = True
    found_last = False
    while position + 4 <= file_size:
        source.seek(position)
        block_header = source.read(4)
        block_type = block_header[0] & 0x7F
        block_length = int.from_bytes(block_header[1:4], "big")
        if first and (block_type != 0 or block_length != 34):
            raise InvalidAudioError("audio file signature is invalid")
        if block_type == 127 or position + 4 + block_length > file_size:
            raise InvalidAudioError("audio file signature is invalid")
        position += 4 + block_length
        first = False
        if block_header[0] & 0x80:
            found_last = True
            break
    if first or not found_last or position >= file_size:
        raise InvalidAudioError("audio file signature is invalid")


def _validate_iso_bmff_signature(source: BinaryIO, header: bytes) -> None:
    source.seek(0, os.SEEK_END)
    file_size = source.tell()
    box_size = int.from_bytes(header[:4], "big")
    header_size = 8
    if box_size == 1:
        source.seek(8)
        extended = source.read(8)
        if len(extended) != 8:
            raise InvalidAudioError("audio file signature is invalid")
        box_size = int.from_bytes(extended, "big")
        header_size = 16
    if box_size < header_size + 8 or box_size > file_size:
        raise InvalidAudioError("audio file signature is invalid")
    source.seek(header_size)
    brands = source.read(box_size - header_size)
    if len(brands) < 8 or (len(brands) - 8) % 4:
        raise InvalidAudioError("audio file signature is invalid")
    allowed_brands = {b"M4A ", b"M4B ", b"isom", b"iso2", b"mp41", b"mp42", b"qt  "}
    compatible_brands = (brands[index : index + 4] for index in range(8, len(brands), 4))
    declared_brands = {brands[:4], *compatible_brands}
    if not declared_brands & allowed_brands:
        raise InvalidAudioError("audio file signature is invalid")


def _validate_adts_signature(source: BinaryIO) -> None:
    source.seek(0, os.SEEK_END)
    file_size = source.tell()
    position = 0
    frame_count = 0
    while position < file_size:
        if position + 7 > file_size:
            raise InvalidAudioError("audio file signature is invalid")
        source.seek(position)
        header = source.read(7)
        if header[0] != 0xFF or header[1] & 0xF6 != 0xF0:
            raise InvalidAudioError("audio file signature is invalid")
        sample_rate_index = (header[2] >> 2) & 0x0F
        channel_configuration = ((header[2] & 1) << 2) | (header[3] >> 6)
        header_size = 7 if header[1] & 1 else 9
        frame_size = ((header[3] & 3) << 11) | (header[4] << 3) | (header[5] >> 5)
        if (
            sample_rate_index >= 13
            or channel_configuration == 0
            or frame_size < header_size
            or position + frame_size > file_size
        ):
            raise InvalidAudioError("audio file signature is invalid")
        position += frame_size
        frame_count += 1
    if frame_count < 2:
        raise InvalidAudioError("audio file signature is invalid")


def _validate_ogg_signature(source: BinaryIO) -> None:
    source.seek(0)
    header = source.read(27)
    if len(header) != 27 or header[:4] != b"OggS" or header[4] != 0 or not header[5] & 0x02:
        raise InvalidAudioError("audio file signature is invalid")
    segment_count = header[26]
    lacing = source.read(segment_count)
    if len(lacing) != segment_count or not lacing:
        raise InvalidAudioError("audio file signature is invalid")
    packet_size = 0
    complete = False
    for value in lacing:
        packet_size += value
        if value < 255:
            complete = True
            break
    packet = source.read(packet_size)
    if not complete or len(packet) != packet_size:
        raise InvalidAudioError("audio file signature is invalid")
    if not (packet.startswith(b"\x01vorbis") or packet.startswith(b"OpusHead")):
        raise InvalidAudioError("audio file signature is invalid")


def _validate_wave_format(source: BinaryIO, header: bytes) -> None:
    source.seek(0, os.SEEK_END)
    file_size = source.tell()
    riff_end = struct.unpack_from("<I", header, 4)[0] + 8
    if riff_end != file_size or riff_end < 44:
        raise InvalidAudioError("audio file signature is invalid")

    found_format = False
    found_data = False
    source.seek(12)
    while source.tell() < riff_end:
        chunk_header = source.read(8)
        if len(chunk_header) != 8:
            raise InvalidAudioError("audio file signature is invalid")
        chunk_name = chunk_header[:4]
        chunk_size = struct.unpack_from("<I", chunk_header, 4)[0]
        chunk_start = source.tell()
        chunk_end = chunk_start + chunk_size
        padded_end = chunk_end + (chunk_size & 1)
        if padded_end > riff_end:
            raise InvalidAudioError("audio file signature is invalid")
        if chunk_name == b"fmt ":
            if found_format or found_data or chunk_size < 16 or chunk_size > 64:
                raise InvalidAudioError("audio file signature is invalid")
            format_data = source.read(chunk_size)
            if len(format_data) != chunk_size:
                raise InvalidAudioError("audio file signature is invalid")
            _validate_pcm_wave_format(format_data)
            found_format = True
        elif chunk_name == b"data":
            if not found_format or found_data:
                raise InvalidAudioError("audio file signature is invalid")
            found_data = True
        source.seek(padded_end)
    if not found_format or not found_data:
        raise InvalidAudioError("audio file signature is invalid")


def _validate_pcm_wave_format(format_data: bytes) -> None:
    format_tag, channels, sample_rate, byte_rate, block_align, bits_per_sample = struct.unpack_from(
        "<HHIIHH", format_data
    )
    if format_tag == 0xFFFE:
        if len(format_data) < 18:
            raise InvalidAudioError("audio file signature is invalid")
        extension_size = struct.unpack_from("<H", format_data, 16)[0]
        if extension_size < 22 or len(format_data) != 18 + extension_size:
            raise InvalidAudioError("audio file signature is invalid")
        valid_bits = struct.unpack_from("<H", format_data, 18)[0]
        subformat = format_data[24:40]
        pcm_guid_tail = b"\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
        if subformat[4:] != pcm_guid_tail:
            raise InvalidAudioError("audio file signature is invalid")
        format_tag = struct.unpack_from("<I", subformat)[0]
        if not 0 < valid_bits <= bits_per_sample:
            raise InvalidAudioError("audio file signature is invalid")
    elif len(format_data) != 16 and (
        len(format_data) < 18
        or struct.unpack_from("<H", format_data, 16)[0] != 0
        or any(format_data[18:])
    ):
        raise InvalidAudioError("audio file signature is invalid")

    allowed_widths = {0x0001: {8, 16, 24, 32}, 0x0003: {32, 64}}
    bytes_per_sample = (bits_per_sample + 7) // 8
    expected_block_align = channels * bytes_per_sample
    if (
        format_tag not in allowed_widths
        or bits_per_sample not in allowed_widths[format_tag]
        or not 1 <= channels <= 32
        or not 1 <= sample_rate <= 384_000
        or block_align != expected_block_align
        or byte_rate != sample_rate * expected_block_align
    ):
        raise InvalidAudioError("audio file signature is invalid")


def _parse_layer_three_header(value: bytes) -> _LayerThreeHeader | None:
    if len(value) != 4 or value[0] != 0xFF or value[1] & 0xE0 != 0xE0:
        return None
    version = (value[1] >> 3) & 0x03
    layer = (value[1] >> 1) & 0x03
    bitrate_index = (value[2] >> 4) & 0x0F
    sample_rate_index = (value[2] >> 2) & 0x03
    emphasis = value[3] & 0x03
    if (
        version == 0x01
        or layer != 0x01
        or bitrate_index in (0x00, 0x0F)
        or sample_rate_index == 0x03
        or emphasis == 0x02
    ):
        return None

    rate_shift = 0 if version == 0x03 else 1 if version == 0x02 else 2
    sample_rate = _MPEG1_SAMPLE_RATES[sample_rate_index] >> rate_shift
    padding = (value[2] >> 1) & 0x01
    channels = 1 if value[3] >> 6 == 0x03 else 2
    bitrates = (
        _MPEG1_LAYER_THREE_BITRATES_KBPS if version == 0x03 else _MPEG2_LAYER_THREE_BITRATES_KBPS
    )
    coefficient = 144 if version == 0x03 else 72
    frame_size = coefficient * bitrates[bitrate_index] * 1000 // sample_rate + padding
    return _LayerThreeHeader(
        version=version,
        sample_rate=sample_rate,
        channels=channels,
        frame_size=frame_size,
    )


def _matching_layer_three_header(
    candidate: _LayerThreeHeader | None,
    first: _LayerThreeHeader,
) -> bool:
    return bool(
        candidate is not None
        and candidate.version == first.version
        and candidate.sample_rate == first.sample_rate
        and candidate.channels == first.channels
    )


def _read_layer_three_header(source: BinaryIO, offset: int) -> _LayerThreeHeader | None:
    source.seek(offset)
    return _parse_layer_three_header(source.read(4))


def _validate_layer_three_frames(source: BinaryIO, frame_offset: int, file_size: int) -> None:
    if frame_offset < 0 or frame_offset + 4 > file_size:
        raise InvalidAudioError("audio file signature is invalid")
    first = _read_layer_three_header(source, frame_offset)
    if first is None:
        raise InvalidAudioError("audio file signature is invalid")
    second_offset = frame_offset + first.frame_size
    second = _read_layer_three_header(source, second_offset)
    if (
        not _matching_layer_three_header(second, first)
        or second is None
        or second_offset + second.frame_size > file_size
    ):
        raise InvalidAudioError("audio file signature is invalid")


_SIGNATURE_VALIDATORS = MappingProxyType(
    {
        ValidatorKind.WAVE: _validate_wave_signature,
        ValidatorKind.MP3: _validate_mp3_signature,
        ValidatorKind.FLAC: _validate_flac_header,
        ValidatorKind.ISO_BMFF: _validate_iso_bmff_header,
        ValidatorKind.ADTS: _validate_adts_header,
        ValidatorKind.OGG_VORBIS: _validate_ogg_header,
        ValidatorKind.OGG_OPUS: _validate_ogg_header,
    }
)


def registered_signature_validator_kinds() -> frozenset[ValidatorKind]:
    return frozenset(_SIGNATURE_VALIDATORS)


if registered_signature_validator_kinds() != frozenset(
    audio_format.validator_kind for audio_format in AUDIO_FORMATS
):
    raise RuntimeError("audio format registry has incomplete signature validator coverage")


class UploadSubmissionService:
    def __init__(
        self,
        *,
        repository: UploadRepository,
        audio_store: UploadAudioStore,
        access_service: UploadAccessService,
        queue: AnalysisQueue,
        temp_root: Path,
        validator: Callable[[Path, AudioFormat], AudioProbe] | None = None,
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
            probe = self._validator(isolated_path, expected_format)
            if not probe_matches_audio_format(
                expected_format,
                format_name=probe.format_name,
                codec_name=probe.codec_name,
            ):
                from museecho.analysis.decode import InvalidAudioError

                raise InvalidAudioError(
                    "file extension does not match detected audio format and codec"
                )
            return self._persist_validated(
                isolated_path,
                canonical_media_type=expected_format.canonical_media_type,
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


def _expected_format(filename: str) -> AudioFormat:
    if (
        not filename
        or "\x00" in filename
        or len(filename) > 255
        or "/" in filename
        or "\\" in filename
        or Path(filename).name != filename
    ):
        raise UnsupportedAudioError("only unambiguous supported audio filenames are accepted")
    path = Path(filename)
    if not path.stem or path.stem == ".":
        raise UnsupportedAudioError("only unambiguous supported audio filenames are accepted")
    try:
        return audio_format_for_suffix(path.suffix)
    except KeyError:
        raise UnsupportedAudioError("audio filename extension is not supported") from None


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
