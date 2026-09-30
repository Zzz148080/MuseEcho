from __future__ import annotations

import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from ipaddress import ip_network
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from museecho.api.accounts import client_ip
from museecho.app import create_app
from museecho.application.access import AccessService
from museecho.application.accounts import AccountService
from museecho.application.library import LibraryError, LibraryService
from museecho.application.lifecycle import AnalysisLifecycleService
from museecho.domain.models import AnalysisResult, TrackAnalysis
from museecho.domain.status import AnalysisJob, AnalysisStage, SourceKind
from museecho.infrastructure.db import create_session_factory, session_scope
from museecho.infrastructure.repositories import (
    SavedAnalysisModel,
    SqliteAnalysisRepository,
    init_db,
)

ORIGIN = "https://museecho.test"


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = [] if forwarded is None else [(b"x-museecho-client-ip", forwarded.encode())]
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/account/login",
            "headers": headers,
            "client": (peer, 12345),
        }
    )


def test_client_ip_only_accepts_valid_header_from_trusted_proxy() -> None:
    trusted = (ip_network("172.16.0.0/12"),)

    assert client_ip(_request("172.18.0.2", "203.0.113.9"), trusted) == "203.0.113.9"
    assert client_ip(_request("198.51.100.7", "203.0.113.9"), trusted) == "198.51.100.7"
    assert client_ip(_request("172.18.0.2", "not-an-ip"), trusted) == "172.18.0.2"


class MemoryMailer:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.templates: list[tuple[str, dict[str, str]]] = []

    def send(
        self,
        address: str,
        subject: str,
        body: str,
        *,
        template_key: str | None = None,
        template_data: dict[str, str] | None = None,
    ) -> None:
        assert template_key in {"verify", "reset"}
        assert template_data is not None
        self.messages.append(body)
        self.templates.append((template_key, template_data))

    def token(self, purpose: str) -> str:
        match = re.search(rf"#{purpose}=([A-Za-z0-9_-]+)", self.messages[-1])
        assert match is not None
        return match.group(1)


def _system(tmp_path: Path):
    database_url = f"sqlite:///{(tmp_path / 'memory.db').as_posix()}"
    init_db(database_url)
    factory = create_session_factory(database_url)
    repository = SqliteAnalysisRepository(factory)
    access = AccessService(repository)
    mailer = MemoryMailer()
    accounts = AccountService(factory, mailer=mailer, public_origin=ORIGIN)
    library = LibraryService(factory, AnalysisLifecycleService(repository))
    app = create_app(
        repository=repository,
        access_service=access,
        account_service=accounts,
        library_service=library,
        trusted_origins={ORIGIN},
    )
    return TestClient(app, base_url=ORIGIN), repository, access, mailer


def _account(client: TestClient, mailer: MemoryMailer, email: str) -> str:
    password = "a-long-private-password"
    assert (
        client.post(
            "/api/account/register",
            json={"email": email, "password": password},
            headers={"Origin": ORIGIN},
        ).status_code
        == 202
    )
    assert mailer.templates[-1][0] == "verify"
    assert mailer.templates[-1][1]["expire_hours"] == "24"
    assert mailer.templates[-1][1]["verify_token"] in mailer.messages[-1]
    token = mailer.token("verify")
    assert (
        client.post(
            "/api/account/verify", json={"token": token}, headers={"Origin": ORIGIN}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/account/verify", json={"token": token}, headers={"Origin": ORIGIN}
        ).status_code
        == 400
    )
    response = client.post(
        "/api/account/login",
        json={"email": email, "password": password},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]
    return client.cookies.get("museecho_user_csrf") or ""


def _analysis(repository: SqliteAnalysisRepository, access: AccessService, bpm: float = 120):
    now = datetime.now(timezone.utc)
    job = AnalysisJob(
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(hours=24),
        pipeline_version="test-v1",
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
    repository.save_result(
        AnalysisResult(
            track=TrackAnalysis(
                job.id,
                30.0,
                22_050,
                1,
                bpm,
                0.95,
                "C",
                "major",
                0.9,
                "4/4",
                0.9,
                None,
            )
        )
    )
    grant = access.issue(job.id, job.expires_at)
    return job.id, grant.raw_token


def test_register_save_private_reopen_after_source_deleted_and_profile(tmp_path: Path):
    client, repository, access, mailer = _system(tmp_path)
    csrf = _account(client, mailer, "a@example.test")
    user_id = client.get("/api/account/me").json()["id"]
    headers = {"Origin": ORIGIN, "X-User-CSRF-Token": csrf}
    saved_ids: list[str] = []
    for number in range(5):
        analysis_id, capability = _analysis(repository, access, 100 + number)
        client.cookies.set(
            "museecho_access",
            capability,
            domain="museecho.test",
            path=f"/api/analyses/{analysis_id}",
        )
        save = client.post(
            f"/api/analyses/{analysis_id}/save",
            json={"title": f"Song {number}"},
            headers=headers,
        )
        assert save.status_code == 201, save.text
        saved_id = save.json()["id"]
        saved_ids.append(saved_id)
        assert (
            client.patch(
                f"/api/library/{saved_id}", json={"preference": "liked"}, headers=headers
            ).status_code
            == 200
        )
        if number == 0:
            repository.delete_cascade(analysis_id)
            detail = client.get(f"/api/library/{saved_id}")
            assert detail.status_code == 200
            assert detail.json()["audio_available"] is False
            assert detail.json()["analysis"]["track"]["bpm"] == 100
    profile = client.get("/api/library/profile").json()
    assert profile["sample_count"] == 5
    assert profile["tags"][0]["name"] == "中速律动"
    assert client.get("/api/library").json()["total"] == 5
    assert len(client.get("/api/library/export").json()["items"]) == 5

    other = TestClient(client.app, base_url=ORIGIN)
    other_csrf = _account(other, mailer, "b@example.test")
    assert other.get(f"/api/library/{saved_ids[0]}").status_code == 404
    assert (
        other.patch(
            f"/api/library/{saved_ids[0]}",
            json={"title": "stolen"},
            headers={"Origin": ORIGIN, "X-User-CSRF-Token": other_csrf},
        ).status_code
        == 404
    )
    assert other.get("/api/library").json()["total"] == 0
    assert client.get("/api/account/me").json()["id"] == user_id

    assert (
        client.patch("/api/library/profile", json={"enabled": False}, headers=headers).json()[
            "tags"
        ]
        == []
    )
    assert client.delete(f"/api/library/{saved_ids[0]}", headers=headers).status_code == 204
    assert client.get("/api/library/profile").json()["sample_count"] == 4
    assert (
        client.request(
            "DELETE", "/api/account/me", headers=headers, json={"password": "wrong"}
        ).status_code
        == 401
    )
    assert (
        client.request(
            "DELETE",
            "/api/account/me",
            headers=headers,
            json={"password": "a-long-private-password"},
        ).status_code
        == 204
    )
    assert client.get("/api/account/me").status_code == 401


def test_save_requires_both_session_csrf_and_analysis_capability(tmp_path: Path):
    client, repository, access, mailer = _system(tmp_path)
    csrf = _account(client, mailer, "a@example.test")
    analysis_id, capability = _analysis(repository, access)
    path = f"/api/analyses/{analysis_id}/save"
    client.cookies.set(
        "museecho_access", capability, domain="museecho.test", path=f"/api/analyses/{analysis_id}"
    )
    assert client.post(path, json={"title": "Song"}, headers={"Origin": ORIGIN}).status_code == 401
    assert (
        client.post(
            path,
            json={"title": "Song"},
            headers={"Origin": "https://evil.test", "X-User-CSRF-Token": csrf},
        ).status_code
        == 403
    )
    client.cookies.delete(
        "museecho_access", domain="museecho.test", path=f"/api/analyses/{analysis_id}"
    )
    assert (
        client.post(
            path, json={"title": "Song"}, headers={"Origin": ORIGIN, "X-User-CSRF-Token": csrf}
        ).status_code
        == 404
    )


def test_password_reset_revokes_sessions_and_library_limit_is_enforced(tmp_path: Path):
    client, repository, access, mailer = _system(tmp_path)
    csrf = _account(client, mailer, "a@example.test")
    user_id = client.get("/api/account/me").json()["id"]
    factory = create_session_factory(f"sqlite:///{(tmp_path / 'memory.db').as_posix()}")
    now = datetime.now(timezone.utc)
    with session_scope(factory) as session:
        session.add_all(
            [
                SavedAnalysisModel(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    original_analysis_id=str(uuid.uuid4()),
                    title=f"Saved {number}",
                    snapshot_json="{}",
                    snapshot_version=1,
                    preference="unmarked",
                    saved_at=now,
                )
                for number in range(100)
            ]
        )
    analysis_id, capability = _analysis(repository, access)
    client.cookies.set(
        "museecho_access", capability, domain="museecho.test", path=f"/api/analyses/{analysis_id}"
    )
    response = client.post(
        f"/api/analyses/{analysis_id}/save",
        json={"title": "One more"},
        headers={"Origin": ORIGIN, "X-User-CSRF-Token": csrf},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "library_full"
    assert (
        client.post(
            "/api/account/request-reset",
            json={"email": "a@example.test"},
            headers={"Origin": ORIGIN},
        ).status_code
        == 202
    )
    assert mailer.templates[-1][0] == "reset"
    assert mailer.templates[-1][1]["expire_minutes"] == "60"
    assert mailer.templates[-1][1]["reset_token"] in mailer.messages[-1]
    reset = mailer.token("reset")
    assert (
        client.post(
            "/api/account/reset-password",
            json={"token": reset, "password": "replacement-password-123"},
            headers={"Origin": ORIGIN},
        ).status_code
        == 200
    )
    assert client.get("/api/account/me").status_code == 401
    assert (
        client.post(
            "/api/account/login",
            json={"email": "a@example.test", "password": "a-long-private-password"},
            headers={"Origin": ORIGIN},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/account/login",
            json={"email": "a@example.test", "password": "replacement-password-123"},
            headers={"Origin": ORIGIN},
        ).status_code
        == 200
    )


def test_unverified_account_can_recover_and_verify_with_reset_link(tmp_path: Path):
    client, _, _, mailer = _system(tmp_path)
    email = "unverified@example.test"
    assert (
        client.post(
            "/api/account/register",
            json={"email": email, "password": "forgotten-password-123"},
            headers={"Origin": ORIGIN},
        ).status_code
        == 202
    )
    assert (
        client.post(
            "/api/account/request-reset", json={"email": email}, headers={"Origin": ORIGIN}
        ).status_code
        == 202
    )
    token = mailer.token("reset")
    assert (
        client.post(
            "/api/account/reset-password",
            json={"token": token, "password": "replacement-password-123"},
            headers={"Origin": ORIGIN},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/account/reset-password",
            json={"token": token, "password": "another-password-123"},
            headers={"Origin": ORIGIN},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/account/login",
            json={"email": email, "password": "replacement-password-123"},
            headers={"Origin": ORIGIN},
        ).status_code
        == 200
    )


def test_simultaneous_saves_cannot_exceed_account_limit(tmp_path: Path):
    client, repository, access, mailer = _system(tmp_path)
    _account(client, mailer, "quota@example.test")
    user_id = client.get("/api/account/me").json()["id"]
    factory = create_session_factory(f"sqlite:///{(tmp_path / 'memory.db').as_posix()}")
    now = datetime.now(timezone.utc)
    with session_scope(factory) as session:
        session.add_all(
            [
                SavedAnalysisModel(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    original_analysis_id=str(uuid.uuid4()),
                    title=f"Saved {number}",
                    snapshot_json="{}",
                    snapshot_version=1,
                    preference="unmarked",
                    saved_at=now,
                )
                for number in range(99)
            ]
        )
    first_id, _ = _analysis(repository, access)
    second_id, _ = _analysis(repository, access)
    library = LibraryService(factory, AnalysisLifecycleService(repository))

    def save(analysis_id: uuid.UUID) -> str:
        try:
            library.save(user_id, analysis_id, "Concurrent song")
            return "saved"
        except LibraryError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(save, (first_id, second_id)))
    assert sorted(outcomes) == ["library_full", "saved"]
    assert library.list(user_id)["saved_count"] == 100


def test_combined_delete_keeps_snapshot_if_temporary_deletion_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    client, repository, access, mailer = _system(tmp_path)
    user_csrf = _account(client, mailer, "delete@example.test")
    analysis_id, capability = _analysis(repository, access)
    client.cookies.set(
        "museecho_access", capability, domain="museecho.test", path=f"/api/analyses/{analysis_id}"
    )
    client.cookies.set("museecho_csrf", "analysis-csrf", domain="museecho.test", path="/")
    save = client.post(
        f"/api/analyses/{analysis_id}/save",
        json={"title": "Keep until source deletion succeeds"},
        headers={"Origin": ORIGIN, "X-User-CSRF-Token": user_csrf},
    )
    assert save.status_code == 201
    saved_id = save.json()["id"]
    headers = {
        "Origin": ORIGIN,
        "X-User-CSRF-Token": user_csrf,
        "X-CSRF-Token": "analysis-csrf",
    }

    def fail_delete(_self: AnalysisLifecycleService, _analysis_id: uuid.UUID) -> bool:
        raise RuntimeError("simulated source deletion failure")

    monkeypatch.setattr(AnalysisLifecycleService, "delete", fail_delete)
    response = client.delete(f"/api/analyses/{analysis_id}?delete_saved=true", headers=headers)
    assert response.status_code == 500, response.text
    assert client.get(f"/api/library/{saved_id}").status_code == 200

    def complete_delete(_self: AnalysisLifecycleService, source_id: uuid.UUID) -> bool:
        repository.delete_cascade(source_id)
        return True

    monkeypatch.setattr(AnalysisLifecycleService, "delete", complete_delete)
    response = client.delete(f"/api/analyses/{analysis_id}?delete_saved=true", headers=headers)
    assert response.status_code == 204
    assert client.get(f"/api/library/{saved_id}").status_code == 404
