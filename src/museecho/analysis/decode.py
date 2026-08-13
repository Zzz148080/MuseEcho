from __future__ import annotations

import ctypes
import json
import math
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread
from typing import BinaryIO, Callable, Protocol, Sequence, cast

from museecho.domain.models import DecodedAudio

DEFAULT_TARGET_SAMPLE_RATE = 22_050
DEFAULT_MAX_DURATION_SECONDS = 600.0
DEFAULT_PROBE_TIMEOUT_SECONDS = 10.0
DEFAULT_DECODE_TIMEOUT_SECONDS = 90.0
MAX_PROBE_OUTPUT_BYTES = 64 * 1024
MAX_STDERR_BYTES = 64 * 1024
MAX_PCM_RESULT_BYTES = 64 * 1024 * 1024
MAX_PCM_PEAK_BYTES = 128 * 1024 * 1024
MAX_DIAGNOSTIC_LENGTH = 512
READ_CHUNK_BYTES = 64 * 1024
PROCESS_EXIT_TIMEOUT_SECONDS = 5.0
READER_JOIN_TIMEOUT_SECONDS = 5.0
INPUT_FORMAT_WHITELIST = "wav,mp3"
INPUT_PROTOCOL_WHITELIST = "file,pipe"
INPUT_CODEC_WHITELIST = "pcm_u8,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_f64le,mp3float,mp3"
SUPPORTED_INPUT_CODECS = frozenset(INPUT_CODEC_WHITELIST.split(","))
SUPPORTED_FORMATS = frozenset({"wav", "mp3"})


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class CommandRunner(Protocol):
    def run(
        self,
        arguments: Sequence[str],
        *,
        timeout: float,
        stdout_limit: int,
        stderr_limit: int,
    ) -> CommandResult: ...


class _ProcessTree:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process
        self._windows_job = _assign_windows_job(process) if os.name == "nt" else None

    def terminate(self) -> None:
        if self._windows_job is not None:
            kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
            kernel32.TerminateJobObject(ctypes.c_void_p(self._windows_job), 1)
            return
        if os.name == "posix":
            try:
                kill_process_group = cast(Callable[[int, int], None], getattr(os, "killpg"))
                kill_signal = cast(int, getattr(signal, "SIGKILL"))
                kill_process_group(self._process.pid, kill_signal)
            except ProcessLookupError:
                pass
            return
        try:
            subprocess.run(
                ["taskkill", "/PID", str(self._process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=PROCESS_EXIT_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            try:
                self._process.kill()
            except OSError:
                pass

    def close(self) -> None:
        if self._windows_job is None:
            return
        kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
        kernel32.CloseHandle(ctypes.c_void_p(self._windows_job))
        self._windows_job = None


class SubprocessCommandRunner:
    def run(
        self,
        arguments: Sequence[str],
        *,
        timeout: float,
        stdout_limit: int,
        stderr_limit: int,
    ) -> CommandResult:
        if timeout <= 0 or stdout_limit <= 0 or stderr_limit <= 0:
            raise ValueError("subprocess limits must be positive")
        process = _spawn_process(arguments)
        process_tree = _ProcessTree(process)
        stdout = bytearray()
        stderr = bytearray()
        output_limit_exceeded = Event()
        readers = (
            Thread(
                target=_read_limited,
                args=(process.stdout, stdout_limit, stdout, process_tree, output_limit_exceeded),
                daemon=True,
            ),
            Thread(
                target=_read_limited,
                args=(process.stderr, stderr_limit, stderr, process_tree, output_limit_exceeded),
                daemon=True,
            ),
        )
        for reader in readers:
            reader.start()
        try:
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process_tree.terminate()
                _wait_for_exit(process)
                _finish_readers(process, readers)
                raise AudioDecodeTimeoutError("audio tool timed out") from None

            # A direct process may exit while a wrapper descendant still holds a pipe.
            process_tree.terminate()
            _finish_readers(process, readers)
            if output_limit_exceeded.is_set():
                raise InvalidAudioError("audio tool output limit exceeded")
            return CommandResult(returncode, bytes(stdout), bytes(stderr))
        finally:
            process_tree.close()


def _spawn_process(arguments: Sequence[str]) -> subprocess.Popen[bytes]:
    try:
        if os.name == "nt":
            return subprocess.Popen(
                list(arguments),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=cast(int, getattr(subprocess, "CREATE_NEW_PROCESS_GROUP")),
            )
        return subprocess.Popen(
            list(arguments),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError:
        raise AudioToolUnavailableError("audio tool is unavailable") from None


def _assign_windows_job(process: subprocess.Popen[bytes]) -> int | None:
    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    job_handle = kernel32.CreateJobObjectW(None, None)
    if not job_handle:
        return None
    process_handle = ctypes.c_void_p(int(getattr(process, "_handle")))
    if not kernel32.AssignProcessToJobObject(ctypes.c_void_p(job_handle), process_handle):
        kernel32.CloseHandle(ctypes.c_void_p(job_handle))
        return None
    return int(job_handle)


def _wait_for_exit(process: subprocess.Popen[bytes]) -> None:
    try:
        process.wait(timeout=PROCESS_EXIT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=PROCESS_EXIT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            raise AudioDecodeError("audio tool process cleanup failed") from None


def _finish_readers(process: subprocess.Popen[bytes], readers: Sequence[Thread]) -> None:
    for reader in readers:
        reader.join(timeout=READER_JOIN_TIMEOUT_SECONDS)
    if not any(reader.is_alive() for reader in readers):
        return
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
    for reader in readers:
        reader.join(timeout=1.0)
    if any(reader.is_alive() for reader in readers):
        raise AudioDecodeError("audio tool pipe cleanup failed")


def _read_limited(
    stream: BinaryIO | None,
    limit: int,
    target: bytearray,
    process_tree: _ProcessTree,
    output_limit_exceeded: Event,
) -> None:
    if stream is None:
        return
    try:
        while True:
            remaining = limit - len(target)
            chunk = stream.read(min(READ_CHUNK_BYTES, remaining + 1))
            if not chunk:
                return
            target.extend(chunk[:remaining])
            if len(chunk) > remaining:
                output_limit_exceeded.set()
                process_tree.terminate()
                return
    except (OSError, ValueError):
        output_limit_exceeded.set()
        process_tree.terminate()
    finally:
        try:
            stream.close()
        except OSError:
            pass


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
    maximum_output_bytes = math.ceil(max_duration_seconds * target_sample_rate) * 4
    if maximum_output_bytes > MAX_PCM_RESULT_BYTES or maximum_output_bytes * 2 > MAX_PCM_PEAK_BYTES:
        raise ValueError("configured decode exceeds the PCM memory budget")

    probe = probe_audio(
        input_path,
        max_duration_seconds=max_duration_seconds,
        timeout_seconds=probe_timeout_seconds,
        ffprobe_executable=ffprobe_executable,
        runner=command_runner,
    )
    arguments = (
        ffmpeg_executable,
        "-v",
        "error",
        "-nostdin",
        "-protocol_whitelist",
        INPUT_PROTOCOL_WHITELIST,
        "-format_whitelist",
        INPUT_FORMAT_WHITELIST,
        "-codec_whitelist",
        INPUT_CODEC_WHITELIST,
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
        result = command_runner.run(
            arguments,
            timeout=decode_timeout_seconds,
            stdout_limit=maximum_output_bytes,
            stderr_limit=MAX_STDERR_BYTES,
        )
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

    try:
        decoded = DecodedAudio(result.stdout, target_sample_rate, channels=1)
    except ValueError:
        raise InvalidAudioError("audio decoder returned invalid PCM") from None
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
        "-protocol_whitelist",
        INPUT_PROTOCOL_WHITELIST,
        "-format_whitelist",
        INPUT_FORMAT_WHITELIST,
        "-select_streams",
        "a:0",
        "-show_entries",
        "format=format_name,duration:stream=codec_name,codec_type,sample_rate,channels,duration",
        "-of",
        "json=compact=1",
        str(input_path),
    )
    try:
        result = command_runner.run(
            arguments,
            timeout=timeout_seconds,
            stdout_limit=MAX_PROBE_OUTPUT_BYTES,
            stderr_limit=MAX_STDERR_BYTES,
        )
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
        codec_name = str(stream["codec_name"])
        sample_rate = int(stream["sample_rate"])
        channels = int(stream["channels"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        raise InvalidAudioError("audio probe returned invalid metadata") from None
    if (
        not math.isfinite(duration_seconds)
        or duration_seconds <= 0
        or codec_name not in SUPPORTED_INPUT_CODECS
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
    value = stderr.decode("utf-8", errors="replace")
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
