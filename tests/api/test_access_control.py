from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, Response
from fastapi.testclient import TestClient

from museecho.api.dependencies import require_analysis_access, require_analysis_mutation
from museecho.api.security import (
    ACCESS_COOKIE_NAME,
    CSRF_COOKIE_NAME,
    set_capability_cookies,
)
from museecho.application.access import AccessService
from museecho.domain.models import AccessGrant, IssuedAccess


class MemoryAccessRepository:
    def __init__(self) -> None:
        self.grants: dict[uuid.UUID, list[AccessGrant]] = {}

    def save_access_grant(self, grant: AccessGrant) -> None:
        self.grants.setdefault(grant.analysis_id, []).append(grant)

    def replace_access_grant(self, grant: AccessGrant) -> None:
        self.grants[grant.analysis_id] = [grant]

    def get_access_grants(self, analysis_id: uuid.UUID) -> list[AccessGrant]:
        return list(self.grants.get(analysis_id, ()))


def _read_app(service: AccessService) -> FastAPI:
    app = FastAPI()
    access_guard = require_analysis_access(service)

    @app.get("/api/analyses/{analysis_id}", dependencies=[Depends(access_guard)])
    def read_analysis(analysis_id: uuid.UUID) -> dict[str, str]:
        return {"analysis_id": str(analysis_id)}

    return app


def _mutation_app(service: AccessService) -> FastAPI:
    app = FastAPI()
    mutation_guard = require_analysis_mutation(service, {"https://museecho.test"})

    @app.delete("/api/analyses/{analysis_id}", dependencies=[Depends(mutation_guard)])
    def delete_analysis(analysis_id: uuid.UUID) -> dict[str, str]:
        return {"analysis_id": str(analysis_id)}

    return app


def test_capability_cookies_are_secure_strict_and_browser_usable():
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    analysis_id = uuid.uuid4()
    issued = IssuedAccess(
        raw_token="raw-capability",
        grant=AccessGrant(
            analysis_id=analysis_id,
            token_hash="$argon2id$stored-only",
            created_at=now,
            expires_at=now + timedelta(hours=1),
            revoked_at=None,
        ),
    )
    response = Response()

    csrf_token = set_capability_cookies(response, issued, now=now)

    cookies = response.headers.getlist("set-cookie")
    access_cookie = next(value for value in cookies if value.startswith(f"{ACCESS_COOKIE_NAME}="))
    csrf_cookie = next(value for value in cookies if value.startswith(f"{CSRF_COOKIE_NAME}="))
    expected_path = f"Path=/api/analyses/{analysis_id}"
    assert expected_path in access_cookie
    assert "HttpOnly" in access_cookie
    assert "Secure" in access_cookie
    assert "SameSite=strict" in access_cookie
    assert "Max-Age=3600" in access_cookie
    assert "Path=/;" in csrf_cookie
    assert expected_path not in csrf_cookie
    assert "HttpOnly" not in csrf_cookie
    assert "Secure" in csrf_cookie
    assert "SameSite=strict" in csrf_cookie
    assert csrf_token in csrf_cookie
    assert issued.raw_token not in csrf_cookie


def test_capability_cookie_max_age_uses_remaining_grant_lifetime():
    created_at = datetime(2026, 8, 8, tzinfo=timezone.utc)
    issued = IssuedAccess(
        raw_token="raw-capability",
        grant=AccessGrant(
            analysis_id=uuid.uuid4(),
            token_hash="$argon2id$stored-only",
            created_at=created_at,
            expires_at=created_at + timedelta(hours=1),
            revoked_at=None,
        ),
    )
    response = Response()

    set_capability_cookies(response, issued, now=created_at + timedelta(minutes=30))

    assert all("Max-Age=1800" in value for value in response.headers.getlist("set-cookie"))


def test_matching_capability_cookie_can_read_analysis():
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    analysis_id = uuid.uuid4()
    service = AccessService(MemoryAccessRepository(), clock=lambda: now)
    issued = service.issue(analysis_id, now + timedelta(hours=1))
    client = TestClient(_read_app(service), base_url="https://museecho.test")
    client.cookies.set(
        ACCESS_COOKIE_NAME,
        issued.raw_token,
        path=f"/api/analyses/{analysis_id}",
    )

    response = client.get(f"/api/analyses/{analysis_id}")

    assert response.status_code == 200
    assert response.json() == {"analysis_id": str(analysis_id)}


def test_mutation_without_double_submit_csrf_is_rejected():
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    analysis_id = uuid.uuid4()
    service = AccessService(MemoryAccessRepository(), clock=lambda: now)
    issued = service.issue(analysis_id, now + timedelta(hours=1))
    client = TestClient(_mutation_app(service), base_url="https://museecho.test")
    client.cookies.set(
        ACCESS_COOKIE_NAME,
        issued.raw_token,
        path=f"/api/analyses/{analysis_id}",
    )

    response = client.delete(
        f"/api/analyses/{analysis_id}",
        headers={"Origin": "https://museecho.test"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_mutation_with_trusted_origin_and_double_submit_csrf_succeeds():
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    analysis_id = uuid.uuid4()
    service = AccessService(MemoryAccessRepository(), clock=lambda: now)
    issued = service.issue(analysis_id, now + timedelta(hours=1))
    client = TestClient(_mutation_app(service), base_url="https://museecho.test")
    path = f"/api/analyses/{analysis_id}"
    client.cookies.set(ACCESS_COOKIE_NAME, issued.raw_token, path=path)
    client.cookies.set(CSRF_COOKIE_NAME, "csrf-value", path=path)

    response = client.delete(
        path,
        headers={"Origin": "https://museecho.test", "X-CSRF-Token": "csrf-value"},
    )

    assert response.status_code == 200


def test_mutation_with_untrusted_origin_is_rejected():
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    analysis_id = uuid.uuid4()
    service = AccessService(MemoryAccessRepository(), clock=lambda: now)
    issued = service.issue(analysis_id, now + timedelta(hours=1))
    client = TestClient(_mutation_app(service), base_url="https://museecho.test")
    path = f"/api/analyses/{analysis_id}"
    client.cookies.set(ACCESS_COOKIE_NAME, issued.raw_token, path=path)
    client.cookies.set(CSRF_COOKIE_NAME, "csrf-value", path=path)

    response = client.delete(
        path,
        headers={"Origin": "https://evil.example", "X-CSRF-Token": "csrf-value"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_mutation_with_wrong_csrf_header_is_rejected():
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    analysis_id = uuid.uuid4()
    service = AccessService(MemoryAccessRepository(), clock=lambda: now)
    issued = service.issue(analysis_id, now + timedelta(hours=1))
    client = TestClient(_mutation_app(service), base_url="https://museecho.test")
    path = f"/api/analyses/{analysis_id}"
    client.cookies.set(ACCESS_COOKIE_NAME, issued.raw_token, path=path)
    client.cookies.set(CSRF_COOKIE_NAME, "csrf-value", path=path)

    response = client.delete(
        path,
        headers={"Origin": "https://museecho.test", "X-CSRF-Token": "wrong"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_missing_wrong_and_cross_analysis_capabilities_share_not_found_response():
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    analysis_id = uuid.uuid4()
    other_analysis_id = uuid.uuid4()
    service = AccessService(MemoryAccessRepository(), clock=lambda: now)
    issued = service.issue(analysis_id, now + timedelta(hours=1))

    missing_client = TestClient(_read_app(service), base_url="https://museecho.test")
    missing = missing_client.get(f"/api/analyses/{analysis_id}")

    wrong_client = TestClient(_read_app(service), base_url="https://museecho.test")
    wrong_client.cookies.set(ACCESS_COOKIE_NAME, "wrong", path=f"/api/analyses/{analysis_id}")
    wrong = wrong_client.get(f"/api/analyses/{analysis_id}")

    cross_client = TestClient(_read_app(service), base_url="https://museecho.test")
    cross_client.cookies.set(ACCESS_COOKIE_NAME, issued.raw_token, path="/api/analyses")
    cross = cross_client.get(f"/api/analyses/{other_analysis_id}")

    expired_time = [now]
    expired_service = AccessService(MemoryAccessRepository(), clock=lambda: expired_time[0])
    expired_issued = expired_service.issue(analysis_id, now + timedelta(hours=1))
    expired_time[0] = now + timedelta(hours=1)
    expired_client = TestClient(_read_app(expired_service), base_url="https://museecho.test")
    expired_client.cookies.set(
        ACCESS_COOKIE_NAME,
        expired_issued.raw_token,
        path=f"/api/analyses/{analysis_id}",
    )
    expired = expired_client.get(f"/api/analyses/{analysis_id}")

    expected = {"detail": "Not Found"}
    assert (missing.status_code, missing.json()) == (404, expected)
    assert (wrong.status_code, wrong.json()) == (404, expected)
    assert (cross.status_code, cross.json()) == (404, expected)
    assert (expired.status_code, expired.json()) == (404, expected)


def test_corrupt_stored_hash_returns_not_found_instead_of_server_error():
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    analysis_id = uuid.uuid4()
    repository = MemoryAccessRepository()
    repository.save_access_grant(
        AccessGrant(
            analysis_id=analysis_id,
            token_hash="é-corrupt",
            created_at=now,
            expires_at=now + timedelta(hours=1),
            revoked_at=None,
        )
    )
    service = AccessService(repository, clock=lambda: now)
    client = TestClient(_read_app(service), base_url="https://museecho.test")
    client.cookies.set(ACCESS_COOKIE_NAME, "candidate", path=f"/api/analyses/{analysis_id}")

    response = client.get(f"/api/analyses/{analysis_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
