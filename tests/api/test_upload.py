from __future__ import annotations

import io
import shutil
import struct
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from museecho.analysis.decode import AudioDurationLimitError, AudioProbe, InvalidAudioError
from museecho.api.analyses import install_analyses_api
from museecho.application.uploads import (
    FFmpegAudioValidator,
    UploadSubmissionService,
)
from museecho.domain.models import AccessGrant, EncryptedAudioMetadata, IssuedAccess
from museecho.domain.status import AnalysisJob
from tests.fixtures.audio_factory import write_sine_wav


class MemoryRepository:
    def __init__(self) -> None:
        self.jobs: dict[uuid.UUID, AnalysisJob] = {}

    def add(self, job: AnalysisJob) -> None:
        self.jobs[job.id] = job

    def delete_cascade(self, analysis_id: uuid.UUID) -> None:
        self.jobs.pop(analysis_id, None)


class RecordingStore:
    def __init__(self) -> None:
        self.writes: list[tuple[uuid.UUID, bytes, str]] = []
        self.deleted: list[uuid.UUID] = []

    def write(
        self, analysis_id: uuid.UUID, source: io.BufferedIOBase, media_type: str
    ) -> EncryptedAudioMetadata:
        payload = source.read()
        self.writes.append((analysis_id, payload, media_type))
        return EncryptedAudioMetadata(
            analysis_id=analysis_id,
            cipher_path=f"{analysis_id}.meaf",
            wrapped_data_key=b"wrapped",
            chunk_size=1024,
            chunk_count=1,
            plaintext_size=len(payload),
            media_type=media_type,
            sha256="0" * 64,
        )

    def delete(self, metadata: EncryptedAudioMetadata) -> None:
        self.deleted.append(metadata.analysis_id)


class RecordingAccessService:
    def issue(self, analysis_id: uuid.UUID, expires_at: datetime) -> IssuedAccess:
        now = datetime.now(timezone.utc)
        return IssuedAccess(
            raw_token=f"token-{analysis_id}",
            grant=AccessGrant(
                analysis_id=analysis_id,
                token_hash="hash",
                created_at=now,
                expires_at=expires_at,
                revoked_at=None,
            ),
        )


class RecordingQueue:
    def __init__(self) -> None:
        self.submitted: list[uuid.UUID] = []

    def submit(self, analysis_id: uuid.UUID) -> None:
        self.submitted.append(analysis_id)


def _client(
    tmp_path: Path,
    validator: Any,
    *,
    max_bytes: int = 30 * 1024 * 1024,
    max_body_bytes: int | None = None,
) -> tuple[TestClient, MemoryRepository, RecordingStore, RecordingQueue]:
    repository = MemoryRepository()
    store = RecordingStore()
    queue = RecordingQueue()
    service = UploadSubmissionService(
        repository=repository,
        audio_store=store,
        access_service=RecordingAccessService(),
        queue=queue,
        temp_root=tmp_path,
        validator=validator,
        max_bytes=max_bytes,
        access_ttl=timedelta(hours=24),
    )
    app = FastAPI()
    if max_body_bytes is None:
        install_analyses_api(app, service)
    else:
        install_analyses_api(app, service, max_body_bytes=max_body_bytes)
    return TestClient(app, base_url="https://museecho.test"), repository, store, queue


def _valid_probe(path: Path) -> AudioProbe:
    assert path.is_file()
    return AudioProbe("wav", 1.0, 22_050, 1, "pcm_s16le")


def _find_tool(name: str) -> str:
    discovered = shutil.which(name) or shutil.which(f"{name}.exe")
    if discovered:
        return discovered
    pytest.fail(f"{name} is required for real upload integration tests", pytrace=False)


def _encode_audio(source: Path, destination: Path, *arguments: str) -> Path:
    completed = subprocess.run(
        [
            _find_tool("ffmpeg"),
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(source),
            *arguments,
            "-y",
            str(destination),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    return destination


def _run_ffmpeg(*arguments: str) -> None:
    completed = subprocess.run(
        [_find_tool("ffmpeg"), "-v", "error", "-nostdin", *arguments],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")


def _wave_from_format_data(format_data: bytes) -> bytes:
    body = b"fmt " + struct.pack("<I", len(format_data)) + format_data + b"data\0\0\0\0"
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WAVE" + body


def _minimal_wave(*, format_tag: int = 1, bits_per_sample: int = 16) -> bytes:
    channels = 1
    sample_rate = 8_000
    bytes_per_sample = (bits_per_sample + 7) // 8
    block_align = channels * bytes_per_sample
    byte_rate = sample_rate * block_align
    format_chunk = struct.pack(
        "<HHIIHH",
        format_tag,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
    )
    return _wave_from_format_data(format_chunk)


def _extensible_wave(
    *,
    extension_size: int | None = None,
    valid_bits: int = 16,
    bits_per_sample: int = 16,
    subformat_tag: int = 1,
    extension_padding: bytes = b"",
) -> bytes:
    bytes_per_sample = bits_per_sample // 8
    if extension_size is None:
        extension_size = 22 + len(extension_padding)
    format_data = (
        struct.pack(
            "<HHIIHHHHI16s",
            0xFFFE,
            1,
            8_000,
            8_000 * bytes_per_sample,
            bytes_per_sample,
            bits_per_sample,
            extension_size,
            valid_bits,
            0,
            struct.pack("<I", subformat_tag) + b"\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71",
        )
        + extension_padding
    )
    return _wave_from_format_data(format_data)


def _free_format_layer_three(*, frame_sizes: tuple[int, ...] = (100, 100, 100)) -> bytes:
    header = b"\xff\xfb\x00\x64"
    return b"".join(header + bytes(size - len(header)) for size in frame_sizes)


def _mpeg1_layer_three_frames(*, count: int = 2, frame_size: int = 417) -> bytes:
    header = b"\xff\xfb\x90\x64"
    return b"".join(header + bytes(frame_size - len(header)) for _ in range(count))


def test_rejects_mp3_name_with_non_audio_bytes(tmp_path: Path):
    client, repository, store, queue = _client(tmp_path, FFmpegAudioValidator())
    response = client.post(
        "/api/analyses", files={"file": ("fake.mp3", b"not audio", "audio/mpeg")}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_audio"
    assert repository.jobs == {}
    assert store.writes == []
    assert queue.submitted == []
    assert list(tmp_path.iterdir()) == []


def test_rejects_oversized_upload_before_validation(tmp_path: Path):
    validated = False

    def validator(path: Path) -> AudioProbe:
        nonlocal validated
        validated = True
        return _valid_probe(path)

    client, repository, store, queue = _client(tmp_path, validator, max_bytes=8)
    response = client.post(
        "/api/analyses", files={"file": ("large.wav", b"123456789", "audio/wav")}
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "upload_too_large"
    assert not validated
    assert repository.jobs == {}
    assert store.writes == []
    assert queue.submitted == []
    assert list(tmp_path.iterdir()) == []


def test_rejects_unsupported_extension_without_storing(tmp_path: Path):
    client, repository, store, queue = _client(tmp_path, _valid_probe)
    response = client.post(
        "/api/analyses",
        files={"file": ("track.wma", b"audio", "audio/x-ms-wma")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_audio"
    assert repository.jobs == {}
    assert store.writes == []
    assert queue.submitted == []


@pytest.mark.parametrize(
    ("filename", "format_name", "codec_name", "canonical_media_type"),
    (
        ("track.wav", "wav", "pcm_s16le", "audio/wav"),
        ("track.mp3", "mp3", "mp3", "audio/mpeg"),
        ("track.flac", "flac", "flac", "audio/flac"),
        ("track.m4a", "mov,mp4,m4a,3gp,3g2,mj2", "aac", "audio/mp4"),
        ("track.m4a", "mov,mp4,m4a,3gp,3g2,mj2", "alac", "audio/mp4"),
        ("track.aac", "aac", "aac", "audio/aac"),
        ("track.ogg", "ogg", "vorbis", "audio/ogg"),
        ("track.opus", "ogg", "opus", "audio/opus"),
    ),
)
def test_supported_suffix_requires_exact_probe_pairing_and_stores_canonical_media_type(
    tmp_path: Path,
    filename: str,
    format_name: str,
    codec_name: str,
    canonical_media_type: str,
):
    probe = AudioProbe(format_name, 1.0, 22_050, 1, codec_name)
    client, repository, store, queue = _client(tmp_path, lambda _: probe)

    response = client.post(
        "/api/analyses",
        files={"file": (filename, b"validated audio", "application/octet-stream")},
    )

    assert response.status_code == 202
    analysis_id = uuid.UUID(response.json()["analysis_id"])
    assert analysis_id in repository.jobs
    assert store.writes == [(analysis_id, b"validated audio", canonical_media_type)]
    assert queue.submitted == [analysis_id]


def test_supported_suffix_rejects_wrong_codec_pairing_before_persistence(tmp_path: Path):
    probe = AudioProbe("mov,mp4,m4a,3gp,3g2,mj2", 1.0, 22_050, 2, "ac3")
    client, repository, store, queue = _client(tmp_path, lambda _: probe)

    response = client.post(
        "/api/analyses",
        files={"file": ("track.m4a", b"unapproved audio", "audio/mp4")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_audio"
    assert repository.jobs == {}
    assert store.writes == []
    assert queue.submitted == []


def test_real_mislabeled_audio_is_rejected_before_persistence(tmp_path: Path):
    source = write_sine_wav(tmp_path / "source.wav", duration_seconds=0.1)
    flac = _encode_audio(source, tmp_path / "source.flac", "-c:a", "flac")
    client, repository, store, queue = _client(
        tmp_path / "uploads",
        FFmpegAudioValidator(
            ffprobe_executable=_find_tool("ffprobe"),
            ffmpeg_executable=_find_tool("ffmpeg"),
        ),
    )

    response = client.post(
        "/api/analyses",
        files={"file": ("renamed.mp3", flac.read_bytes(), "audio/mpeg")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_audio"
    assert repository.jobs == {}
    assert store.writes == []
    assert queue.submitted == []


@pytest.mark.parametrize("unapproved_stream", ("video", "ac3"))
def test_real_m4a_unapproved_stream_is_rejected_before_persistence(
    tmp_path: Path, unapproved_stream: str
):
    source = write_sine_wav(tmp_path / "source.wav", duration_seconds=0.1)
    encoded = tmp_path / f"with-{unapproved_stream}.m4a"
    if unapproved_stream == "video":
        _run_ffmpeg(
            "-i",
            str(source),
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=32x32:d=0.1",
            "-map",
            "0:a:0",
            "-map",
            "1:v:0",
            "-c:a",
            "aac",
            "-c:v",
            "mpeg4",
            "-shortest",
            "-f",
            "mp4",
            "-y",
            str(encoded),
        )
    else:
        _run_ffmpeg(
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-map",
            "0:a:0",
            "-c:a:0",
            "aac",
            "-c:a:1",
            "ac3",
            "-f",
            "mp4",
            "-y",
            str(encoded),
        )
    client, repository, store, queue = _client(
        tmp_path / "uploads",
        FFmpegAudioValidator(
            ffprobe_executable=_find_tool("ffprobe"),
            ffmpeg_executable=_find_tool("ffmpeg"),
        ),
    )

    response = client.post(
        "/api/analyses",
        files={"file": ("track.m4a", encoded.read_bytes(), "audio/mp4")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_audio"
    assert repository.jobs == {}
    assert store.writes == []
    assert queue.submitted == []


def test_rejects_extension_that_does_not_match_detected_format(tmp_path: Path):
    client, repository, store, queue = _client(
        tmp_path, lambda _: AudioProbe("wav", 1.0, 22_050, 1)
    )
    response = client.post(
        "/api/analyses", files={"file": ("renamed.mp3", b"RIFFdata", "audio/mpeg")}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_audio"
    assert repository.jobs == {}
    assert store.writes == []
    assert queue.submitted == []


def test_rejects_audio_over_duration_limit(tmp_path: Path):
    def reject(_: Path) -> AudioProbe:
        raise AudioDurationLimitError("audio duration exceeds the supported limit")

    client, _, store, queue = _client(tmp_path, reject)
    response = client.post("/api/analyses", files={"file": ("long.wav", b"RIFFdata", "audio/wav")})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "audio_too_long"
    assert store.writes == []
    assert queue.submitted == []


def test_valid_upload_returns_202_random_id_and_capability_cookies(tmp_path: Path):
    client, repository, store, queue = _client(tmp_path, _valid_probe)
    response = client.post("/api/analyses", files={"file": ("track.wav", b"RIFFdata", "audio/wav")})

    assert response.status_code == 202
    analysis_id = uuid.UUID(response.json()["analysis_id"])
    assert response.json()["stage"] == "queued"
    assert response.json()["progress"] == 0.0
    assert analysis_id in repository.jobs
    assert store.writes == [(analysis_id, b"RIFFdata", "audio/wav")]
    assert queue.submitted == [analysis_id]
    cookie_headers = response.headers.get_list("set-cookie")
    assert any("museecho_access=" in value for value in cookie_headers)
    assert any("museecho_csrf=" in value for value in cookie_headers)
    assert list(tmp_path.iterdir()) == []


def test_repeated_uploads_are_isolated_jobs(tmp_path: Path):
    observed_paths: list[Path] = []

    def validator(path: Path) -> AudioProbe:
        observed_paths.append(path)
        return _valid_probe(path)

    client, repository, store, queue = _client(tmp_path, validator)
    first = client.post("/api/analyses", files={"file": ("same.wav", b"first", "audio/wav")})
    second = client.post("/api/analyses", files={"file": ("same.wav", b"second", "audio/wav")})

    first_id = uuid.UUID(first.json()["analysis_id"])
    second_id = uuid.UUID(second.json()["analysis_id"])
    assert first.status_code == second.status_code == 202
    assert first_id != second_id
    assert len(set(observed_paths)) == 2
    assert set(repository.jobs) == {first_id, second_id}
    assert [payload for _, payload, _ in store.writes] == [b"first", b"second"]
    assert queue.submitted == [first_id, second_id]


@pytest.mark.parametrize(
    "filename",
    ["", ".wav", "track.WAV.exe", "folder/track.wav", r"folder\track.wav"],
)
def test_rejects_ambiguous_filenames(tmp_path: Path, filename: str):
    client, _, store, queue = _client(tmp_path, _valid_probe)
    response = client.post(
        "/api/analyses", files={"file": (filename, b"audio", "application/octet-stream")}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_audio"
    assert store.writes == []
    assert queue.submitted == []


def test_queue_failure_rolls_back_job_and_encrypted_audio(tmp_path: Path):
    repository = MemoryRepository()
    store = RecordingStore()

    class FailingQueue:
        def submit(self, analysis_id: uuid.UUID) -> None:
            raise RuntimeError(f"queue unavailable for {analysis_id}")

    service = UploadSubmissionService(
        repository=repository,
        audio_store=store,
        access_service=RecordingAccessService(),
        queue=FailingQueue(),
        temp_root=tmp_path,
        validator=_valid_probe,
    )

    with pytest.raises(RuntimeError, match="queue unavailable"):
        service.submit(io.BytesIO(b"RIFFdata"), filename="track.wav", media_type="text/plain")

    assert repository.jobs == {}
    assert len(store.writes) == 1
    assert store.deleted == [store.writes[0][0]]
    assert list(tmp_path.iterdir()) == []


def test_ffmpeg_validator_requires_probe_and_successful_decode(tmp_path: Path, monkeypatch):
    from museecho.application import uploads
    from museecho.application.uploads import FFmpegAudioValidator
    from museecho.domain.models import DecodedAudio

    source = tmp_path / "source.wav"
    source.write_bytes(_minimal_wave())
    calls: list[str] = []
    probe = AudioProbe("wav", 1.0, 22_050, 1)

    def fake_probe(path: Path, **kwargs: Any) -> AudioProbe:
        assert path == source
        assert kwargs["max_duration_seconds"] == 600.0
        calls.append("probe")
        return probe

    def fake_decode(path: Path, **kwargs: Any) -> DecodedAudio:
        assert path == source
        assert kwargs["max_duration_seconds"] == 600.0
        calls.append("decode")
        return DecodedAudio(b"\x00\x00\x00\x00", 22_050, 1)

    monkeypatch.setattr(uploads, "probe_audio", fake_probe)
    monkeypatch.setattr(uploads, "decode_audio", fake_decode)

    result = FFmpegAudioValidator()(source)

    assert result == probe
    assert calls == ["probe", "decode"]


@pytest.mark.parametrize("subformat_tag", (0x0001, 0x0003))
def test_ffmpeg_validator_accepts_extensible_valid_precision_and_extension_padding(
    tmp_path: Path, monkeypatch, subformat_tag: int
):
    from museecho.application import uploads
    from museecho.domain.models import DecodedAudio

    source = tmp_path / "source.wav"
    source.write_bytes(
        _extensible_wave(
            valid_bits=24,
            bits_per_sample=32,
            subformat_tag=subformat_tag,
            extension_padding=b"\x00\x00",
        )
    )
    calls: list[str] = []
    probe = AudioProbe("wav", 1.0, 8_000, 1)
    monkeypatch.setattr(
        uploads,
        "probe_audio",
        lambda *_args, **_kwargs: calls.append("probe") or probe,
    )
    monkeypatch.setattr(
        uploads,
        "decode_audio",
        lambda *_args, **_kwargs: (
            calls.append("decode") or DecodedAudio(b"\x00\x00\x00\x00", 8_000, 1)
        ),
    )

    assert FFmpegAudioValidator()(source) == probe
    assert calls == ["probe", "decode"]


def test_ffmpeg_validator_rejects_free_format_layer_three_before_audio_tools(
    tmp_path: Path, monkeypatch
):
    from museecho.application import uploads

    source = tmp_path / "free-format.mp3"
    source.write_bytes(_free_format_layer_three())
    calls: list[str] = []
    monkeypatch.setattr(
        uploads,
        "probe_audio",
        lambda *_args, **_kwargs: calls.append("probe"),
    )
    monkeypatch.setattr(
        uploads,
        "decode_audio",
        lambda *_args, **_kwargs: calls.append("decode"),
    )

    with pytest.raises(InvalidAudioError, match="signature"):
        FFmpegAudioValidator()(source)

    assert calls == []


@pytest.mark.parametrize(
    "payload",
    (
        b"RIFF",
        b"RIFF\x24\x00\x00\x00NOPE",
        b"ID3\x04\x00\x00\x00\x00\x00\x00",
        b"ID3\x04\x00\x00\x80\x00\x00\x00payload",
        b"\xff\xeb\x90\x64not-an-mp3-frame",
        b"\xff\xfd\x90\x64mpeg-layer-two",
        b"\xff\xff\x90\x64mpeg-layer-one",
        b"\xff\xfb\x90\x64single-layer-three-header",
        b"ID3\x04\x00\x10\x00\x00\x00\x00notfooter!" + _mpeg1_layer_three_frames(),
    ),
)
def test_ffmpeg_validator_rejects_ambiguous_signatures_before_audio_tools(
    tmp_path: Path, monkeypatch, payload: bytes
):
    from museecho.application import uploads
    from museecho.application.uploads import FFmpegAudioValidator
    from museecho.domain.models import DecodedAudio

    source = tmp_path / "source.bin"
    source.write_bytes(payload)
    calls: list[str] = []
    probe = AudioProbe("wav", 1.0, 22_050, 1)

    def fake_probe(*_args: Any, **_kwargs: Any) -> AudioProbe:
        calls.append("probe")
        return probe

    def fake_decode(*_args: Any, **_kwargs: Any) -> DecodedAudio:
        calls.append("decode")
        return DecodedAudio(b"\x00\x00\x00\x00", 22_050, 1)

    monkeypatch.setattr(uploads, "probe_audio", fake_probe)
    monkeypatch.setattr(uploads, "decode_audio", fake_decode)

    with pytest.raises(InvalidAudioError, match="signature"):
        FFmpegAudioValidator()(source)

    assert calls == []


@pytest.mark.parametrize("valid_bits", (0, 33))
def test_ffmpeg_validator_rejects_extensible_precision_outside_container_before_tools(
    tmp_path: Path, monkeypatch, valid_bits: int
):
    from museecho.application import uploads

    source = tmp_path / "source.wav"
    source.write_bytes(_extensible_wave(valid_bits=valid_bits, bits_per_sample=32))
    calls: list[str] = []
    monkeypatch.setattr(
        uploads,
        "probe_audio",
        lambda *_args, **_kwargs: calls.append("probe"),
    )
    monkeypatch.setattr(
        uploads,
        "decode_audio",
        lambda *_args, **_kwargs: calls.append("decode"),
    )

    with pytest.raises(InvalidAudioError, match="signature"):
        FFmpegAudioValidator()(source)

    assert calls == []


def test_ffmpeg_validator_rejects_short_extensible_format_before_audio_tools(
    tmp_path: Path, monkeypatch
):
    from museecho.application import uploads

    source = tmp_path / "short-extensible.wav"
    source.write_bytes(_minimal_wave(format_tag=0xFFFE))
    calls: list[str] = []
    monkeypatch.setattr(
        uploads,
        "probe_audio",
        lambda *_args, **_kwargs: calls.append("probe"),
    )
    monkeypatch.setattr(
        uploads,
        "decode_audio",
        lambda *_args, **_kwargs: calls.append("decode"),
    )

    with pytest.raises(InvalidAudioError, match="signature"):
        FFmpegAudioValidator()(source)

    assert calls == []


@pytest.mark.parametrize(
    "payload",
    (
        _extensible_wave(extension_size=65_535),
        _wave_from_format_data(struct.pack("<HHIIHHH2s", 1, 1, 8_000, 16_000, 2, 16, 0, b"xx")),
    ),
)
def test_ffmpeg_validator_rejects_inconsistent_wave_format_lengths_before_audio_tools(
    tmp_path: Path, monkeypatch, payload: bytes
):
    from museecho.application import uploads

    source = tmp_path / "source.wav"
    source.write_bytes(payload)
    calls: list[str] = []
    monkeypatch.setattr(
        uploads,
        "probe_audio",
        lambda *_args, **_kwargs: calls.append("probe"),
    )
    monkeypatch.setattr(
        uploads,
        "decode_audio",
        lambda *_args, **_kwargs: calls.append("decode"),
    )

    with pytest.raises(InvalidAudioError, match="signature"):
        FFmpegAudioValidator()(source)

    assert calls == []


@pytest.mark.parametrize(
    ("format_tag", "bits_per_sample"),
    ((0x0011, 4), (0x0055, 0), (0x0001, 20), (0x0003, 16)),
)
def test_ffmpeg_validator_rejects_compressed_or_ambiguous_wave_before_audio_tools(
    tmp_path: Path,
    monkeypatch,
    format_tag: int,
    bits_per_sample: int,
):
    from museecho.application import uploads

    source = tmp_path / "source.wav"
    source.write_bytes(_minimal_wave(format_tag=format_tag, bits_per_sample=bits_per_sample))
    calls: list[str] = []
    monkeypatch.setattr(
        uploads,
        "probe_audio",
        lambda *_args, **_kwargs: calls.append("probe"),
    )
    monkeypatch.setattr(
        uploads,
        "decode_audio",
        lambda *_args, **_kwargs: calls.append("decode"),
    )

    with pytest.raises(InvalidAudioError, match="signature"):
        FFmpegAudioValidator()(source)

    assert calls == []


def test_request_body_limit_runs_before_multipart_parsing(tmp_path: Path):
    validated = False

    def validator(path: Path) -> AudioProbe:
        nonlocal validated
        validated = True
        return _valid_probe(path)

    client, repository, store, queue = _client(
        tmp_path,
        validator,
        max_bytes=1024 * 1024,
        max_body_bytes=512,
    )
    response = client.post(
        "/api/analyses",
        files={"file": ("large.wav", b"x" * 4096, "audio/wav")},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "upload_too_large"
    assert not validated
    assert repository.jobs == {}
    assert store.writes == []
    assert queue.submitted == []
    assert list(tmp_path.iterdir()) == []


def test_chunked_request_without_content_length_is_still_capped(tmp_path: Path):
    validated = False

    def validator(path: Path) -> AudioProbe:
        nonlocal validated
        validated = True
        return _valid_probe(path)

    client, repository, store, queue = _client(
        tmp_path,
        validator,
        max_bytes=1024 * 1024,
        max_body_bytes=256,
    )
    boundary = "museecho-boundary"
    body = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="large.wav"\r\n'
            "Content-Type: audio/wav\r\n\r\n"
        ).encode()
        + b"x" * 4096
        + f"\r\n--{boundary}--\r\n".encode()
    )

    def chunks():
        for offset in range(0, len(body), 64):
            yield body[offset : offset + 64]

    response = client.post(
        "/api/analyses",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        content=chunks(),
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "upload_too_large"
    assert not validated
    assert repository.jobs == {}
    assert store.writes == []
    assert queue.submitted == []
    assert list(tmp_path.iterdir()) == []


def test_body_limit_never_double_sends_after_downstream_responds_early():
    import asyncio

    from starlette.types import Message

    from museecho.api.analyses import UploadBodyLimitMiddleware

    sent: list[Message] = []
    request_messages = iter([{"type": "http.request", "body": b"x" * 9, "more_body": False}])

    async def downstream(_scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await receive()
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive() -> Message:
        return next(request_messages)

    async def send(message: Message) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/analyses",
        "headers": [],
    }
    asyncio.run(UploadBodyLimitMiddleware(downstream, max_body_bytes=8)(scope, receive, send))

    response_starts = [
        message["status"] for message in sent if message["type"] == "http.response.start"
    ]
    assert response_starts == [413]


def test_validation_is_serialized_across_service_instances(tmp_path: Path, monkeypatch):
    import threading

    from museecho.application import uploads
    from museecho.domain.models import DecodedAudio

    first_path = tmp_path / "first.wav"
    second_path = tmp_path / "second.wav"
    first_path.write_bytes(_minimal_wave())
    second_path.write_bytes(_minimal_wave())
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    failures: list[BaseException] = []
    probe = AudioProbe("wav", 1.0, 22_050, 1)

    def fake_probe(path: Path, **_: Any) -> AudioProbe:
        if path == first_path:
            first_started.set()
            assert release_first.wait(timeout=2)
        else:
            second_started.set()
        return probe

    monkeypatch.setattr(uploads, "probe_audio", fake_probe)
    monkeypatch.setattr(
        uploads,
        "decode_audio",
        lambda *_args, **_kwargs: DecodedAudio(b"\x00\x00\x00\x00", 22_050, 1),
    )

    def validate(validator: FFmpegAudioValidator, path: Path) -> None:
        try:
            validator(path)
        except BaseException as exc:
            failures.append(exc)

    first = threading.Thread(target=validate, args=(FFmpegAudioValidator(), first_path))
    second = threading.Thread(target=validate, args=(FFmpegAudioValidator(), second_path))
    first.start()
    assert first_started.wait(timeout=2)
    second.start()
    assert not second_started.wait(timeout=0.1)
    release_first.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert second_started.is_set()
    assert failures == []


def test_startup_removes_abandoned_plaintext_but_preserves_unrelated_files(tmp_path: Path):
    temp_root = tmp_path / "uploads"
    stale = temp_root / ("museecho-upload-" + "a" * 32 + "-deadbeef")
    stale.mkdir(parents=True)
    (stale / ".owner").write_bytes(b"MuseEcho temporary plaintext v1\n")
    (stale / "plaintext.wav").write_bytes(b"private audio")
    unrelated = temp_root / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")
    confusing_file = temp_root / "upload-personal-not-owned.txt"
    confusing_file.write_text("keep", encoding="utf-8")
    unmarked_directory = temp_root / ("museecho-upload-" + "b" * 32 + "-personal")
    unmarked_directory.mkdir()
    (unmarked_directory / "notes.txt").write_text("keep", encoding="utf-8")

    UploadSubmissionService(
        repository=MemoryRepository(),
        audio_store=RecordingStore(),
        access_service=RecordingAccessService(),
        queue=RecordingQueue(),
        temp_root=temp_root,
        validator=_valid_probe,
    )

    assert not stale.exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert confusing_file.read_text(encoding="utf-8") == "keep"
    assert (unmarked_directory / "notes.txt").read_text(encoding="utf-8") == "keep"


def test_resource_limits_can_be_lowered_but_not_raised(tmp_path: Path):
    from museecho.application.uploads import (
        DEFAULT_MAX_DURATION_SECONDS,
        DEFAULT_MAX_UPLOAD_BYTES,
    )

    with pytest.raises(ValueError, match="supported limit"):
        FFmpegAudioValidator(max_duration_seconds=DEFAULT_MAX_DURATION_SECONDS + 0.1)

    with pytest.raises(ValueError, match="supported limit"):
        UploadSubmissionService(
            repository=MemoryRepository(),
            audio_store=RecordingStore(),
            access_service=RecordingAccessService(),
            queue=RecordingQueue(),
            temp_root=tmp_path,
            validator=_valid_probe,
            max_bytes=DEFAULT_MAX_UPLOAD_BYTES + 1,
        )

    from museecho.api.analyses import (
        DEFAULT_MAX_UPLOAD_REQUEST_BYTES,
        UploadBodyLimitMiddleware,
    )

    async def passthrough(_scope, _receive, _send):
        return None

    with pytest.raises(ValueError, match="supported limit"):
        UploadBodyLimitMiddleware(
            passthrough,
            max_body_bytes=DEFAULT_MAX_UPLOAD_REQUEST_BYTES + 1,
        )
