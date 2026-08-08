from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from museecho.domain.models import DecodedAudio

DEFAULT_TARGET_SAMPLE_RATE = 22_050
DEFAULT_MAX_DURATION_SECONDS = 600.0
DEFAULT_PROBE_TIMEOUT_SECONDS = 10.0
DEFAULT_DECODE_TIMEOUT_SECONDS = 90.0
MAX_PROBE_OUTPUT_BYTES = 64 * 1024
MAX_DIAGNOSTIC_LENGTH = 512
SUPPORTED_FORMATS = frozenset({"wav", "mp3"})


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class CommandRunner(Protocol):
    def run(self, arguments: Sequence[str], *, timeout: float) -> CommandResult: ...


class SubprocessCommandRunner:
    def run(self, arguments: Sequence[str], *, timeout: float) -> CommandResult:
        try:
            completed = subprocess.run(
                list(arguments),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise AudioDecodeTimeoutError("audio tool timed out") from None
        except OSError:
            raise AudioToolUnavailableError("audio tool is unavailable") from None
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


class AudioDecodeError(RuntimeError):
    code = "audio_decode_failed"

    def __init__(self, message: str, *, diagnostic: str = "") -> None:
        super().__init__(message)
        self.diagnostic = diagnostic


class InvalidAudioError(AudioDecodeError):
    code = "invalid_audio"


class AudioDurationLimitError(AudioDecodeError):
    code = "audio_too_long"


class AudioDecodeTimeoutError(AudioDecodeError):
    code = "audio_decode_timeout"


class AudioToolUnavailableError(AudioDecodeError):
    code = "audio_tool_unavailable"


@dataclass(frozen=True)
class AudioProbe:
    format_name: str
    duration_seconds: float
    sample_rate: int
    channels: int


def decode_audio(
    path: Path,
    *,
    target_sample_rate: int = DEFAULT_TARGET_SAMPLE_RATE,
    max_duration_seconds: float = DEFAULT_MAX_DURATION_SECONDS,
    probe_timeout_seconds: float = DEFAULT_PROBE_TIMEOUT_SECONDS,
    decode_timeout_seconds: float = DEFAULT_DECODE_TIMEOUT_SECONDS,
    ffprobe_executable: str = "ffprobe",
    ffmpeg_executable: str = "ffmpeg",
    runner: CommandRunner | None = None,
) -> DecodedAudio:
    input_path = _validate_input(path)
    _validate_limits(
        target_sample_rate,
        max_duration_seconds,
        probe_timeout_seconds,
        decode_timeout_seconds,
    )
    command_runner = runner or SubprocessCommandRunner()
    probe = probe_audio(
        input_path,
        max_duration_seconds=max_duration_seconds,
        timeout_seconds=probe_timeout_seconds,
        ffprobe_executable=ffprobe_executable,
        runner=command_runner,
    )
    maximum_output_bytes = math.ceil(max_duration_seconds * target_sample_rate) * 4
    arguments = (
        ffmpeg_executable,
        "-v",
        "error",
        "-nostdin",
        "-i",
        str(input_path),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(target_sample_rate),
        "-t",
        _format_decimal_limit(max_duration_seconds),
        "-f",
        "f32le",
        "pipe:1",
    )
    try:
        result = command_runner.run(arguments, timeout=decode_timeout_seconds)
    except AudioDecodeTimeoutError:
        raise
    except AudioDecodeError:
        raise
    except Exception:
        raise AudioDecodeError("audio decoding failed") from None
    if result.returncode != 0:
        raise InvalidAudioError(
            "audio decoding failed",
            diagnostic=_safe_diagnostic(result.stderr, input_path),
        )
    if not result.stdout or len(result.stdout) % 4 != 0:
        raise InvalidAudioError("audio decoder returned invalid PCM")
    if len(result.stdout) > maximum_output_bytes:
        raise AudioDurationLimitError("audio duration exceeds the supported limit")

    decoded = DecodedAudio(result.stdout, target_sample_rate, channels=1)
    expected_duration = probe.duration_seconds
    tolerance = max(0.05, 2.0 / target_sample_rate)
    if decoded.duration_seconds > max_duration_seconds + tolerance:
        raise AudioDurationLimitError("audio duration exceeds the supported limit")
    if abs(decoded.duration_seconds - expected_duration) > max(0.25, expected_duration * 0.02):
        raise InvalidAudioError("audio duration changed unexpectedly during decoding")
    return decoded


def probe_audio(
    path: Path,
    *,
    max_duration_seconds: float = DEFAULT_MAX_DURATION_SECONDS,
    timeout_seconds: float = DEFAULT_PROBE_TIMEOUT_SECONDS,
    ffprobe_executable: str = "ffprobe",
    runner: CommandRunner | None = None,
) -> AudioProbe:
    input_path = _validate_input(path)
    if not math.isfinite(max_duration_seconds) or max_duration_seconds <= 0:
        raise ValueError("max_duration_seconds must be positive and finite")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive and finite")
    command_runner = runner or SubprocessCommandRunner()
    arguments = (
        ffprobe_executable,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "format=format_name,duration:stream=codec_type,sample_rate,channels,duration",
        "-of",
        "json=compact=1",
        str(input_path),
    )
    try:
        result = command_runner.run(arguments, timeout=timeout_seconds)
    except AudioDecodeTimeoutError:
        raise
    except AudioDecodeError:
        raise
    except Exception:
        raise AudioDecodeError("audio probing failed") from None
    if result.returncode != 0:
        raise InvalidAudioError(
            "file is not valid WAV or MP3 audio",
            diagnostic=_safe_diagnostic(result.stderr, input_path),
        )
    if not result.stdout or len(result.stdout) > MAX_PROBE_OUTPUT_BYTES:
        raise InvalidAudioError("audio probe returned invalid metadata")
    probe = _parse_probe(result.stdout)
    if probe.duration_seconds > max_duration_seconds:
        raise AudioDurationLimitError("audio duration exceeds the supported limit")
    return probe


def _parse_probe(value: bytes) -> AudioProbe:
    try:
        payload = json.loads(value)
        streams = payload["streams"]
        format_data = payload["format"]
        if not isinstance(streams, list) or len(streams) != 1:
            raise ValueError
        stream = streams[0]
        format_name = str(format_data["format_name"])
        formats = set(format_name.split(","))
        if not formats.intersection(SUPPORTED_FORMATS):
            raise ValueError
        duration_value = format_data.get("duration", stream.get("duration"))
        duration_seconds = float(duration_value)
        sample_rate = int(stream["sample_rate"])
        channels = int(stream["channels"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        raise InvalidAudioError("audio probe returned invalid metadata") from None
    if (
        not math.isfinite(duration_seconds)
        or duration_seconds <= 0
        or not 8_000 <= sample_rate <= 384_000
        or not 1 <= channels <= 32
    ):
        raise InvalidAudioError("audio probe returned invalid metadata")
    return AudioProbe(format_name, duration_seconds, sample_rate, channels)


def _validate_input(path: Path) -> Path:
    if path.is_symlink():
        raise InvalidAudioError("audio input must be a regular file")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise InvalidAudioError("audio input is unavailable") from None
    if not resolved.is_file() or resolved.is_symlink():
        raise InvalidAudioError("audio input must be a regular file")
    return resolved


def _validate_limits(
    target_sample_rate: int,
    max_duration_seconds: float,
    probe_timeout_seconds: float,
    decode_timeout_seconds: float,
) -> None:
    if not 8_000 <= target_sample_rate <= 192_000:
        raise ValueError("target_sample_rate is outside the supported range")
    for value, name in (
        (max_duration_seconds, "max_duration_seconds"),
        (probe_timeout_seconds, "probe_timeout_seconds"),
        (decode_timeout_seconds, "decode_timeout_seconds"),
    ):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be positive and finite")


def _safe_diagnostic(stderr: bytes, input_path: Path) -> str:
    value = stderr[: MAX_DIAGNOSTIC_LENGTH * 4].decode("utf-8", errors="replace")
    candidates = {
        str(input_path),
        input_path.as_posix(),
        str(input_path).replace("\\", "/"),
        input_path.name,
    }
    for candidate in sorted(candidates, key=len, reverse=True):
        if candidate:
            value = value.replace(candidate, "<input>")
    return value[:MAX_DIAGNOSTIC_LENGTH]


def _format_decimal_limit(value: float) -> str:
    return format(value, ".6f").rstrip("0").rstrip(".")


__all__ = [
    "AudioDecodeError",
    "AudioDecodeTimeoutError",
    "AudioDurationLimitError",
    "AudioProbe",
    "AudioToolUnavailableError",
    "CommandResult",
    "CommandRunner",
    "InvalidAudioError",
    "SubprocessCommandRunner",
    "decode_audio",
    "probe_audio",
]
