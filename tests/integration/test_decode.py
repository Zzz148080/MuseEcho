from __future__ import annotations

import hashlib
import json
import math
import shutil
import struct
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from typing import Sequence

import pytest

from museecho.analysis.decode import (
    AudioDecodeTimeoutError,
    AudioDurationLimitError,
    CommandResult,
    InvalidAudioError,
    SubprocessCommandRunner,
    _safe_diagnostic,
    decode_audio,
    probe_audio,
)
from museecho.application.uploads import _validate_audio_signature
from museecho.audio_formats import audio_format_for_suffix
from tests.fixtures.audio_factory import (
    encode_mp3,
    write_chord_progression_wav,
    write_chord_wav,
    write_corrupt_audio,
    write_metronome_wav,
    write_segmented_energy_wav,
    write_short_wav,
    write_silence_wav,
    write_sine_wav,
)


def _find_tool(name: str) -> str:
    discovered = shutil.which(name) or shutil.which(f"{name}.exe")
    if discovered:
        return discovered
    executable = f"{name}.exe" if (Path("tmp") / "ffmpeg-download").exists() else name
    matches = list(Path("tmp/ffmpeg-download/expanded").glob(f"**/{executable}"))
    if not matches:
        pytest.fail(f"{name} is required for real decoding integration tests", pytrace=False)
    return str(matches[0].resolve())


def _decode(path: Path, *, target_sample_rate: int = 22_050):
    return decode_audio(
        path,
        target_sample_rate=target_sample_rate,
        ffprobe_executable=_find_tool("ffprobe"),
        ffmpeg_executable=_find_tool("ffmpeg"),
    )


def test_decode_normalizes_to_target_rate(tmp_path: Path):
    sine_wav = write_sine_wav(tmp_path / "sine.wav")

    decoded = _decode(sine_wav)

    assert decoded.sample_rate == 22_050
    assert decoded.channels == 1
    assert decoded.samples.ndim == 1
    assert decoded.duration_seconds == pytest.approx(2.0, abs=0.03)


def test_real_mp3_decodes_to_controlled_mono_pcm(tmp_path: Path):
    wav_path = write_sine_wav(tmp_path / "source.wav", duration_seconds=1.25)
    mp3_path = encode_mp3(
        wav_path,
        tmp_path / "source.mp3",
        ffmpeg_executable=_find_tool("ffmpeg"),
    )

    _validate_audio_signature(mp3_path, audio_format_for_suffix(mp3_path.suffix))
    decoded = _decode(mp3_path, target_sample_rate=16_000)

    assert decoded.sample_rate == 16_000
    assert decoded.channels == 1
    assert decoded.duration_seconds == pytest.approx(1.25, abs=0.05)
    assert max(abs(value) for value in decoded.samples) > 0.1


@pytest.mark.parametrize(
    ("suffix", "encoder_arguments"),
    (
        (".wav", ("-c:a", "pcm_s16le")),
        (".mp3", ("-c:a", "mp3")),
        (".flac", ("-c:a", "flac")),
        ("-aac.m4a", ("-c:a", "aac")),
        ("-alac.m4a", ("-c:a", "alac")),
        (".aac", ("-c:a", "aac", "-f", "adts")),
        (".ogg", ("-c:a", "libvorbis")),
        (".opus", ("-c:a", "libopus")),
    ),
)
def test_real_common_audio_formats_validate_and_decode(
    tmp_path: Path, suffix: str, encoder_arguments: tuple[str, ...]
):
    source = write_sine_wav(tmp_path / "source.wav", duration_seconds=0.25)
    encoded = tmp_path / f"encoded{suffix}"
    completed = subprocess.run(
        [
            _find_tool("ffmpeg"),
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(source),
            *encoder_arguments,
            "-y",
            str(encoded),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")

    _validate_audio_signature(encoded, audio_format_for_suffix(encoded.suffix))
    decoded = _decode(encoded)

    assert decoded.sample_rate == 22_050
    assert decoded.channels == 1
    assert decoded.duration_seconds == pytest.approx(0.25, abs=0.08)
    assert max(abs(value) for value in decoded.samples) > 0.05


def test_real_mp3_with_attached_cover_art_decodes_to_controlled_mono_pcm(tmp_path: Path):
    source = write_sine_wav(tmp_path / "source.wav", duration_seconds=1.0)
    audio = encode_mp3(
        source,
        tmp_path / "source.mp3",
        ffmpeg_executable=_find_tool("ffmpeg"),
    )
    artwork = tmp_path / "cover.jpg"
    attached = tmp_path / "with-cover.mp3"
    cover = subprocess.run(
        [
            _find_tool("ffmpeg"),
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=32x32:d=0.1",
            "-frames:v",
            "1",
            "-y",
            str(artwork),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert cover.returncode == 0, cover.stderr.decode(errors="replace")
    mux = subprocess.run(
        [
            _find_tool("ffmpeg"),
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(audio),
            "-i",
            str(artwork),
            "-map",
            "0:a:0",
            "-map",
            "1:v:0",
            "-c:a",
            "copy",
            "-c:v",
            "mjpeg",
            "-disposition:v:0",
            "attached_pic",
            "-y",
            str(attached),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert mux.returncode == 0, mux.stderr.decode(errors="replace")

    _validate_audio_signature(attached, audio_format_for_suffix(attached.suffix))
    decoded = _decode(attached)

    assert decoded.sample_rate == 22_050
    assert decoded.channels == 1
    assert decoded.duration_seconds == pytest.approx(1.0, abs=0.05)


@pytest.mark.parametrize(
    "codec_name",
    (
        "pcm_u8",
        "pcm_s16le",
        "pcm_s24le",
        "pcm_s32le",
        "pcm_f32le",
        "pcm_f64le",
    ),
)
def test_real_uncompressed_pcm_wav_widths_remain_supported(tmp_path: Path, codec_name: str):
    source = write_sine_wav(tmp_path / "source.wav", duration_seconds=0.1)
    encoded = tmp_path / f"{codec_name}.wav"
    completed = subprocess.run(
        [
            _find_tool("ffmpeg"),
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(source),
            "-codec:a",
            codec_name,
            "-y",
            str(encoded),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")

    _validate_audio_signature(encoded, audio_format_for_suffix(encoded.suffix))
    decoded = _decode(encoded)

    assert decoded.duration_seconds == pytest.approx(0.1, abs=0.03)


def test_real_ima_adpcm_wav_is_rejected_by_decoder_allowlist(tmp_path: Path):
    source = write_sine_wav(tmp_path / "source.wav", duration_seconds=0.1)
    encoded = tmp_path / "compressed.wav"
    completed = subprocess.run(
        [
            _find_tool("ffmpeg"),
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(source),
            "-codec:a",
            "adpcm_ima_wav",
            "-y",
            str(encoded),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")

    with pytest.raises(InvalidAudioError):
        probe_audio(encoded, ffprobe_executable=_find_tool("ffprobe"))


def test_corrupt_audio_is_rejected_without_exposing_input_path(tmp_path: Path):
    corrupt = write_corrupt_audio(tmp_path / "private-upload-name.mp3")

    with pytest.raises(InvalidAudioError) as captured:
        _decode(corrupt)

    assert captured.value.code == "invalid_audio"
    assert str(corrupt.resolve()) not in captured.value.diagnostic
    assert corrupt.name not in captured.value.diagnostic
    assert len(captured.value.diagnostic) <= 512


def test_probe_rejects_duration_over_limit_before_decode(tmp_path: Path):
    input_path = write_corrupt_audio(tmp_path / "placeholder.wav")
    runner = ScriptedRunner(CommandResult(0, _probe_json(duration=600.01), b""))

    with pytest.raises(AudioDurationLimitError) as captured:
        probe_audio(input_path, max_duration_seconds=600.0, runner=runner)

    assert captured.value.code == "audio_too_long"
    assert len(runner.calls) == 1


def test_subprocess_timeout_maps_to_stable_domain_error():
    with pytest.raises(AudioDecodeTimeoutError) as captured:
        SubprocessCommandRunner().run(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            timeout=0.05,
            stdout_limit=64,
            stderr_limit=64,
        )

    assert captured.value.code == "audio_decode_timeout"
    assert captured.value.__suppress_context__


def test_factory_outputs_are_repeatable_and_cover_analysis_boundaries(tmp_path: Path):
    factories = (
        lambda path: write_metronome_wav(path),
        lambda path: write_chord_wav(path, quality="major"),
        lambda path: write_chord_wav(path, quality="minor"),
        lambda path: write_chord_progression_wav(path),
        lambda path: write_segmented_energy_wav(path),
        lambda path: write_silence_wav(path),
        lambda path: write_short_wav(path),
        lambda path: write_corrupt_audio(path),
    )
    expected_hashes = (
        "55f9f7b80311bb37724ab8d5cf2bce030b1c211e11693468b8550d37dcd490dc",
        "0a4699f53e47688995f0f3caf4f93728c81d6283c54121f1a0e8f271c99851c4",
        "a44b14571bbf4a73cdc88f49c64d9c9c661a520df01cb02cc324429d1526a667",
        "974f25d4a6da9afc53659447f074f039ed9540b4a8ce237a577412c0b6cc111a",
        "8714624f0e96a01b3fb519e8d8d7b83146cb32ce57fd9991d62ea5d61633188b",
        "842d8ff3d950813e85a6f5cd2e3c0639ea69070ca01766ad47184befd309b8ec",
        "1c61dc0cb00d52ebb9fc644bdb3a33f6784193eef8ce091c9c168544da4cfe1f",
        "a0cbf1d517bc3861bbeb5d5bb63dddc86df35aa1dd219a3f4f4c4b99ef1d6261",
    )

    for index, (factory, expected_hash) in enumerate(zip(factories, expected_hashes)):
        first = factory(tmp_path / f"first-{index}.wav")
        second = factory(tmp_path / f"second-{index}.wav")
        first_hash = hashlib.sha256(first.read_bytes()).hexdigest()
        second_hash = hashlib.sha256(second.read_bytes()).hexdigest()
        assert first_hash == expected_hash
        assert second_hash == expected_hash


class ScriptedRunner:
    def __init__(self, *results: CommandResult) -> None:
        self._results = iter(results)
        self.calls: list[tuple[tuple[str, ...], float, int, int]] = []

    def run(
        self,
        arguments: Sequence[str],
        *,
        timeout: float,
        stdout_limit: int,
        stderr_limit: int,
    ) -> CommandResult:
        self.calls.append((tuple(arguments), timeout, stdout_limit, stderr_limit))
        return next(self._results)


def _probe_json(
    *, duration: float, format_name: str = "wav", codec_name: str = "pcm_s16le"
) -> bytes:
    return json.dumps(
        {
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": codec_name,
                    "sample_rate": "44100",
                    "channels": 2,
                    "duration": str(duration),
                }
            ],
            "format": {"format_name": format_name, "duration": str(duration)},
        }
    ).encode()


def _probe_streams_json(*, format_name: str, streams: list[dict[str, object]]) -> bytes:
    return json.dumps(
        {
            "streams": streams,
            "format": {"format_name": format_name, "duration": "1.0"},
        }
    ).encode()


def test_symbolic_link_input_is_rejected(tmp_path: Path):
    target = write_sine_wav(tmp_path / "target.wav", duration_seconds=0.1)
    link = tmp_path / "upload.wav"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("current Windows session cannot create symbolic links")

    with pytest.raises(InvalidAudioError, match="regular file"):
        decode_audio(link)


def test_decode_uses_bounded_mono_float_pipeline(tmp_path: Path):
    input_path = write_corrupt_audio(tmp_path / "placeholder.wav")
    pcm = struct.pack("<100f", *([0.25] * 100))
    runner = ScriptedRunner(
        CommandResult(0, _probe_json(duration=0.0125), b""),
        CommandResult(0, pcm, b""),
    )

    decoded = decode_audio(
        input_path,
        target_sample_rate=8_000,
        max_duration_seconds=1.0,
        ffprobe_executable="safe-ffprobe",
        ffmpeg_executable="safe-ffmpeg",
        runner=runner,
    )

    decode_arguments, decode_timeout, stdout_limit, stderr_limit = runner.calls[1]
    assert decoded.duration_seconds == pytest.approx(0.0125)
    assert decode_arguments[0] == "safe-ffmpeg"
    assert decode_arguments[decode_arguments.index("-ac") + 1] == "1"
    assert decode_arguments[decode_arguments.index("-ar") + 1] == "8000"
    assert decode_arguments[decode_arguments.index("-t") + 1] == "1"
    assert decode_arguments[-2:] == ("f32le", "pipe:1")
    assert decode_timeout == 90.0
    probe_arguments = runner.calls[0][0]
    assert probe_arguments[probe_arguments.index("-protocol_whitelist") + 1] == "file,pipe"
    assert (
        probe_arguments[probe_arguments.index("-format_whitelist") + 1]
        == (decode_arguments[decode_arguments.index("-format_whitelist") + 1])
    )
    assert (
        probe_arguments[probe_arguments.index("-codec_whitelist") + 1]
        == (decode_arguments[decode_arguments.index("-codec_whitelist") + 1])
    )
    assert "-select_streams" not in probe_arguments
    assert probe_arguments.index("-protocol_whitelist") < len(probe_arguments) - 1
    assert decode_arguments[decode_arguments.index("-protocol_whitelist") + 1] == "file,pipe"
    assert decode_arguments[decode_arguments.index("-format_whitelist") + 1] == (
        "wav,mp3,flac,mov,mp4,m4a,3gp,3g2,mj2,aac,ogg"
    )
    assert decode_arguments[decode_arguments.index("-codec_whitelist") + 1] == (
        "pcm_u8,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_f64le,"
        "mp3float,mp3,flac,aac,alac,vorbis,opus,mjpeg"
    )
    assert decode_arguments.index("-protocol_whitelist") < decode_arguments.index("-i")
    assert decode_arguments.index("-format_whitelist") < decode_arguments.index("-i")
    assert decode_arguments.index("-codec_whitelist") < decode_arguments.index("-i")
    assert stdout_limit == 32_000
    assert stderr_limit == 64 * 1024


def test_probe_accepts_only_mp3_attached_mjpeg_cover_art(tmp_path: Path):
    input_path = write_corrupt_audio(tmp_path / "placeholder.mp3")
    payload = _probe_streams_json(
        format_name="mp3",
        streams=[
            {
                "codec_type": "audio",
                "codec_name": "mp3",
                "sample_rate": "44100",
                "channels": 2,
                "duration": "1.0",
                "disposition": {"attached_pic": 0},
            },
            {
                "codec_type": "video",
                "codec_name": "mjpeg",
                "disposition": {"attached_pic": 1},
            },
        ],
    )

    probe = probe_audio(input_path, runner=ScriptedRunner(CommandResult(0, payload, b"")))

    assert probe.format_name == "mp3"
    assert probe.codec_name == "mp3"


@pytest.mark.parametrize(
    "streams",
    (
        [
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "44100",
                "channels": 2,
                "duration": "1.0",
                "disposition": {"attached_pic": 0},
            },
            {
                "codec_type": "video",
                "codec_name": "h264",
                "disposition": {"attached_pic": 0},
            },
        ],
        [
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "44100",
                "channels": 2,
                "duration": "1.0",
                "disposition": {"attached_pic": 0},
            },
            {
                "codec_type": "audio",
                "codec_name": "ac3",
                "sample_rate": "44100",
                "channels": 2,
                "duration": "1.0",
                "disposition": {"attached_pic": 0},
            },
        ],
    ),
)
def test_probe_rejects_m4a_with_video_or_unapproved_audio_stream(
    tmp_path: Path, streams: list[dict[str, object]]
):
    input_path = write_corrupt_audio(tmp_path / "placeholder.m4a")
    payload = _probe_streams_json(
        format_name="mov,mp4,m4a,3gp,3g2,mj2",
        streams=streams,
    )

    with pytest.raises(InvalidAudioError, match="invalid metadata"):
        probe_audio(input_path, runner=ScriptedRunner(CommandResult(0, payload, b"")))


def test_decode_rejects_output_beyond_configured_duration(tmp_path: Path):
    input_path = write_corrupt_audio(tmp_path / "placeholder.wav")
    runner = ScriptedRunner(
        CommandResult(0, _probe_json(duration=0.001), b""),
        CommandResult(0, b"\x00" * 36, b""),
    )

    with pytest.raises(AudioDurationLimitError):
        decode_audio(
            input_path,
            target_sample_rate=8_000,
            max_duration_seconds=0.001,
            runner=runner,
        )


def test_probe_rejects_unsupported_container_metadata(tmp_path: Path):
    input_path = write_corrupt_audio(tmp_path / "placeholder.m4a")
    runner = ScriptedRunner(
        CommandResult(0, _probe_json(duration=1.0, format_name="mov,mp4,m4a"), b"")
    )

    with pytest.raises(InvalidAudioError, match="invalid metadata"):
        probe_audio(input_path, runner=runner)


def test_decode_failure_diagnostic_is_bounded_and_path_redacted(tmp_path: Path):
    input_path = write_corrupt_audio(tmp_path / "private-upload.wav")
    stderr = (f"failure at {input_path.resolve()} " + "x" * 4_000).encode()
    runner = ScriptedRunner(
        CommandResult(0, _probe_json(duration=1.0), b""),
        CommandResult(1, b"", stderr),
    )

    with pytest.raises(InvalidAudioError) as captured:
        decode_audio(input_path, runner=runner)

    assert str(input_path.resolve()) not in captured.value.diagnostic
    assert input_path.name not in captured.value.diagnostic
    assert len(captured.value.diagnostic) <= 512


def test_non_finite_pcm_is_rejected(tmp_path: Path):
    input_path = write_corrupt_audio(tmp_path / "nan.wav")
    pcm = struct.pack("<3f", 0.0, math.nan, 0.0)
    runner = ScriptedRunner(
        CommandResult(0, _probe_json(duration=3 / 8_000), b""),
        CommandResult(0, pcm, b""),
    )

    with pytest.raises(InvalidAudioError, match="invalid PCM"):
        decode_audio(input_path, target_sample_rate=8_000, runner=runner)


@pytest.mark.parametrize("stream_name", ["stdout", "stderr"])
def test_subprocess_runner_enforces_hard_output_limits(stream_name: str):
    command = f"import sys; sys.{stream_name}.buffer.write(b'x' * 4096); sys.{stream_name}.flush()"

    with pytest.raises(InvalidAudioError, match="output limit"):
        SubprocessCommandRunner().run(
            [sys.executable, "-c", command],
            timeout=5.0,
            stdout_limit=64,
            stderr_limit=64,
        )


def test_decode_rejects_configuration_over_pcm_memory_budget(tmp_path: Path):
    input_path = write_corrupt_audio(tmp_path / "placeholder.wav")

    with pytest.raises(ValueError, match="PCM memory budget"):
        decode_audio(
            input_path,
            target_sample_rate=48_000,
            max_duration_seconds=400.0,
            runner=ScriptedRunner(),
        )


def test_diagnostic_redacts_long_path_before_truncating():
    long_path = Path("/").joinpath(*(["private-segment"] * 180), "upload.wav")
    diagnostic = _safe_diagnostic(str(long_path).encode(), long_path)

    assert "private-segment" not in diagnostic
    assert "upload.wav" not in diagnostic
    assert diagnostic == "<input>"


def test_playlist_cannot_trigger_nested_http_request(tmp_path: Path):
    requested = Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requested.set()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"not audio")

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    playlist = tmp_path / "disguised.wav"
    playlist.write_text(
        "#EXTM3U\n"
        "#EXT-X-TARGETDURATION:1\n"
        "#EXTINF:1,\n"
        f"http://127.0.0.1:{server.server_port}/segment.wav\n"
        "#EXT-X-ENDLIST\n",
        encoding="utf-8",
    )
    try:
        with pytest.raises(InvalidAudioError):
            probe_audio(playlist, ffprobe_executable=_find_tool("ffprobe"))
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)

    assert not requested.is_set()


def test_timeout_terminates_descendant_holding_output_pipes():
    wrapper = (
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], "
        "stdout=sys.stdout, stderr=sys.stderr); "
        "time.sleep(30)"
    )
    started = time.monotonic()

    with pytest.raises(AudioDecodeTimeoutError):
        SubprocessCommandRunner().run(
            [sys.executable, "-c", wrapper],
            timeout=0.1,
            stdout_limit=64,
            stderr_limit=64,
        )

    assert time.monotonic() - started < 5.0
