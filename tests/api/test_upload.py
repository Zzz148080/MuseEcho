from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from museecho.analysis.decode import AudioDurationLimitError, AudioProbe
from museecho.api.analyses import install_analyses_api
from museecho.application.uploads import (
    FFmpegAudioValidator,
    UploadSubmissionService,
)
from museecho.domain.models import AccessGrant, EncryptedAudioMetadata, IssuedAccess
from museecho.domain.status import AnalysisJob


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
    return AudioProbe("wav", 1.0, 22_050, 1)


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
    response = client.post("/api/analyses", files={"file": ("track.flac", b"audio", "audio/flac")})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_audio"
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
    source.write_bytes(b"RIFFdata")
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


def test_validation_is_serialized_across_service_instances(tmp_path: Path, monkeypatch):
    import threading

    from museecho.application import uploads
    from museecho.domain.models import DecodedAudio

    first_path = tmp_path / "first.wav"
    second_path = tmp_path / "second.wav"
    first_path.write_bytes(b"first")
    second_path.write_bytes(b"second")
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
    stale = temp_root / "upload-abandoned"
    stale.mkdir(parents=True)
    (stale / "plaintext.wav").write_bytes(b"private audio")
    unrelated = temp_root / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")

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
