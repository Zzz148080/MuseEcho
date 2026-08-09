from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from museecho.api.results import create_results_router
from museecho.app import create_app
from museecho.application.access import AccessService
from museecho.application.explanations import ExplanationService
from museecho.domain.models import AnalysisResult, Evidence, TrackAnalysis
from museecho.domain.status import AnalysisJob, AnalysisStage, SourceKind
from museecho.infrastructure.audio_store import ChunkedEncryptedAudioStore
from museecho.infrastructure.db import create_session_factory
from museecho.infrastructure.repositories import SqliteAnalysisRepository, init_db


class MemorySecretStore:
    source = "test-memory"

    def __init__(self, key: bytes) -> None:
        self.value = base64.urlsafe_b64encode(key).decode("ascii")

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value

    def clear(self) -> bool:
        self.value = ""
        return True


def _completed_client(tmp_path: Path):
    database_url = f"sqlite:///{(tmp_path / 'museecho.db').as_posix()}"
    init_db(database_url)
    repository = SqliteAnalysisRepository(create_session_factory(database_url))
    now = datetime.now(timezone.utc)
    job = AnalysisJob(
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(hours=24),
        pipeline_version="museecho-analysis-v1",
        source_kind=SourceKind.REAL,
    )
    repository.add(job)
    for stage in (
        AnalysisStage.VALIDATING,
        AnalysisStage.DECODING,
        AnalysisStage.RHYTHM,
        AnalysisStage.TONALITY,
        AnalysisStage.STRUCTURE,
        AnalysisStage.CHORDS,
        AnalysisStage.EVIDENCE,
    ):
        job.advance_to(stage)
    repository.update(job)
    evidence = Evidence(
        uuid.uuid4(),
        job.id,
        "rhythm",
        0.0,
        2.0,
        {"public_value": {"bpm": 120.0}},
        0.9,
        "test-rhythm",
        True,
    )
    repository.save_result(
        AnalysisResult(
            track=TrackAnalysis(
                job.id,
                2.0,
                22_050,
                1,
                120.0,
                0.9,
                None,
                None,
                None,
                None,
                None,
                {"source_kind": "real"},
            ),
            evidence=(evidence,),
        )
    )
    store = ChunkedEncryptedAudioStore(
        tmp_path / "ciphertext",
        key_store=MemorySecretStore(b"m" * 32),
        repository=repository,
        chunk_size=8,
    )
    with (tmp_path / "source.wav").open("wb+") as source:
        source.write(b"0123456789abcdef")
        source.seek(0)
        store.write(job.id, source, "audio/wav")
    access_service = AccessService(repository, clock=lambda: now)
    issued = access_service.issue(job.id, job.expires_at)  # type: ignore[arg-type]
    app = create_app(
        repository=repository,
        access_service=access_service,
        audio_store=store,
        explanation_service=ExplanationService(None),
        trusted_origins={"https://museecho.test"},
    )
    client = TestClient(app, base_url="https://museecho.test")
    client.cookies.set(
        "museecho_access",
        issued.raw_token,
        domain="museecho.test",
        path=f"/api/analyses/{job.id}",
    )
    client.cookies.set(
        "museecho_csrf",
        "csrf-test-token",
        domain="museecho.test",
        path=f"/api/analyses/{job.id}",
    )
    return client, repository, job


def test_authorized_status_and_result_return_persisted_real_analysis(tmp_path: Path):
    client, _repository, job = _completed_client(tmp_path)

    status = client.get(f"/api/analyses/{job.id}/status")
    result = client.get(f"/api/analyses/{job.id}")

    assert status.status_code == 200
    assert status.json() == {
        "analysis_id": str(job.id),
        "status": "complete",
        "stage": "complete",
        "progress": 1.0,
        "error_code": None,
        "expires_at": job.expires_at.isoformat(),  # type: ignore[union-attr]
        "pipeline_version": "museecho-analysis-v1",
        "source_kind": "real",
    }
    assert result.status_code == 200
    assert result.json()["analysis_id"] == str(job.id)
    assert result.json()["source_kind"] == "real"
    assert result.json()["pipeline_version"] == "museecho-analysis-v1"
    assert result.json()["track"]["bpm"] == 120.0
    assert result.json()["evidence"][0]["kind"] == "rhythm"


def test_unknown_or_unauthorized_analysis_is_indistinguishable(tmp_path: Path):
    client, _repository, job = _completed_client(tmp_path)
    client.cookies.clear()

    denied = client.get(f"/api/analyses/{job.id}/status")
    missing = client.get(f"/api/analyses/{uuid.uuid4()}/status")

    assert denied.status_code == missing.status_code == 404
    assert denied.json() == missing.json() == {"detail": "Not Found"}


def test_audio_supports_full_and_bounded_range_reads(tmp_path: Path):
    client, _repository, job = _completed_client(tmp_path)

    full = client.get(f"/api/analyses/{job.id}/audio")
    partial = client.get(
        f"/api/analyses/{job.id}/audio",
        headers={"Range": "bytes=2-5"},
    )

    assert full.status_code == 200
    assert full.content == b"0123456789abcdef"
    assert full.headers["accept-ranges"] == "bytes"
    assert full.headers["content-length"] == "16"
    assert partial.status_code == 206
    assert partial.content == b"2345"
    assert partial.headers["content-range"] == "bytes 2-5/16"
    assert partial.headers["content-length"] == "4"
    assert partial.headers["content-type"].startswith("audio/wav")


def test_audio_rejects_malformed_or_unsatisfiable_ranges(tmp_path: Path):
    client, _repository, job = _completed_client(tmp_path)

    for value in (
        "items=0-1",
        "bytes=4-2",
        "bytes=99-",
        "bytes=0-1,4-5",
        f"bytes={'9' * 5000}-",
    ):
        response = client.get(
            f"/api/analyses/{job.id}/audio",
            headers={"Range": value},
        )
        assert response.status_code == 416
        assert response.headers["content-range"] == "bytes */16"


def test_explanation_uses_segment_evidence_and_persists_only_question_digest(tmp_path: Path):
    client, repository, job = _completed_client(tmp_path)

    response = client.post(
        f"/api/analyses/{job.id}/explanations",
        headers={
            "Origin": "https://museecho.test",
            "X-CSRF-Token": "csrf-test-token",
        },
        json={
            "question": "这段节奏有什么特点？",
            "start_seconds": 0.0,
            "end_seconds": 2.0,
        },
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "fallback"
    assert len(response.json()["evidence_ids"]) == 1
    assert "120" in response.json()["text"]
    saved = repository.get_explanations(job.id)
    assert len(saved) == 1
    assert saved[0].question_digest != "这段节奏有什么特点？"
    assert len(saved[0].question_digest) == 64


def test_explanation_rejects_invalid_interval_with_stable_error(tmp_path: Path):
    client, _repository, job = _completed_client(tmp_path)

    response = client.post(
        f"/api/analyses/{job.id}/explanations",
        headers={
            "Origin": "https://museecho.test",
            "X-CSRF-Token": "csrf-test-token",
        },
        json={
            "question": "越界了吗？",
            "start_seconds": 1.5,
            "end_seconds": 3.0,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_explanation_request"

    malformed = client.post(
        f"/api/analyses/{job.id}/explanations",
        headers={
            "Origin": "https://museecho.test",
            "X-CSRF-Token": "csrf-test-token",
        },
        json={
            "question": ["not", "text"],
            "start_seconds": "zero",
            "end_seconds": 1.0,
            "unexpected": True,
        },
    )
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "invalid_explanation_request"


def test_delete_revokes_access_and_removes_ciphertext_and_rows(tmp_path: Path):
    client, repository, job = _completed_client(tmp_path)
    metadata = repository.get_encrypted_audio(job.id)
    assert metadata is not None
    cipher_path = Path(metadata.cipher_path)

    deleted = client.delete(
        f"/api/analyses/{job.id}",
        headers={
            "Origin": "https://museecho.test",
            "X-CSRF-Token": "csrf-test-token",
        },
    )

    assert deleted.status_code == 204
    assert repository.get(job.id) is None
    assert repository.get_encrypted_audio(job.id) is None
    assert not cipher_path.exists()
    assert client.get(f"/api/analyses/{job.id}/status").status_code == 404


def test_delete_with_untrusted_origin_is_not_found_and_preserves_data(tmp_path: Path):
    client, repository, job = _completed_client(tmp_path)

    denied = client.delete(
        f"/api/analyses/{job.id}",
        headers={
            "Origin": "https://evil.test",
            "X-CSRF-Token": "csrf-test-token",
        },
    )

    assert denied.status_code == 404
    assert repository.get(job.id) is not None
    assert repository.get_encrypted_audio(job.id) is not None


def test_malformed_persisted_result_returns_stable_error_without_details():
    analysis_id = uuid.uuid4()

    class AllowAccess:
        def authorize(self, candidate: uuid.UUID, raw_token: str) -> bool:
            return candidate == analysis_id and raw_token == "allowed"

    class MalformedResultService:
        def result(self, candidate: uuid.UUID):
            assert candidate == analysis_id
            raise ValueError("sensitive database corruption detail")

    app = FastAPI()
    app.include_router(
        create_results_router(
            MalformedResultService(),  # type: ignore[arg-type]
            AllowAccess(),  # type: ignore[arg-type]
            {"https://museecho.test"},
        )
    )
    client = TestClient(app, base_url="https://museecho.test")
    client.cookies.set(
        "museecho_access",
        "allowed",
        domain="museecho.test",
        path=f"/api/analyses/{analysis_id}",
    )

    response = client.get(f"/api/analyses/{analysis_id}")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "invalid_analysis_result",
            "message": "stored analysis result is invalid",
        }
    }
    assert "sensitive" not in response.text


def test_resource_disappearing_after_authorization_returns_not_found():
    analysis_id = uuid.uuid4()

    class AllowAccess:
        def authorize(self, candidate: uuid.UUID, raw_token: str) -> bool:
            return candidate == analysis_id and raw_token == "allowed"

    class GoneService:
        def status(self, candidate: uuid.UUID):
            assert candidate == analysis_id
            raise KeyError(str(candidate))

        def result(self, candidate: uuid.UUID):
            assert candidate == analysis_id
            raise KeyError(str(candidate))

    app = FastAPI()
    app.include_router(
        create_results_router(
            GoneService(),  # type: ignore[arg-type]
            AllowAccess(),  # type: ignore[arg-type]
            {"https://museecho.test"},
        )
    )
    client = TestClient(app, base_url="https://museecho.test")
    client.cookies.set(
        "museecho_access",
        "allowed",
        domain="museecho.test",
        path=f"/api/analyses/{analysis_id}",
    )

    status_response = client.get(f"/api/analyses/{analysis_id}/status")
    result_response = client.get(f"/api/analyses/{analysis_id}")

    assert status_response.status_code == result_response.status_code == 404
    assert status_response.json() == result_response.json() == {"detail": "Not Found"}


def test_explanation_rate_limit_returns_retryable_stable_error(tmp_path: Path):
    client, _repository, job = _completed_client(tmp_path)
    request = {
        "headers": {
            "Origin": "https://museecho.test",
            "X-CSRF-Token": "csrf-test-token",
        },
        "json": {
            "question": "节奏？",
            "start_seconds": 0.0,
            "end_seconds": 2.0,
        },
    }

    accepted = [client.post(f"/api/analyses/{job.id}/explanations", **request) for _ in range(10)]
    limited = client.post(f"/api/analyses/{job.id}/explanations", **request)

    assert all(response.status_code == 200 for response in accepted)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "explanation_rate_limited"
