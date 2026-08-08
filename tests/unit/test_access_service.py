from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

import museecho.application.access as access_module
from museecho.application.access import AccessService
from museecho.domain.models import AccessGrant


class MemoryAccessRepository:
    def __init__(self) -> None:
        self.grants: dict[uuid.UUID, list[AccessGrant]] = {}

    def save_access_grant(self, grant: AccessGrant) -> None:
        self.grants.setdefault(grant.analysis_id, []).append(grant)

    def get_access_grants(self, analysis_id: uuid.UUID) -> list[AccessGrant]:
        return list(self.grants.get(analysis_id, ()))


def test_issue_persists_argon2id_hash_not_raw_token_and_authorizes():
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    analysis_id = uuid.uuid4()
    repository = MemoryAccessRepository()
    service = AccessService(repository, clock=lambda: now)

    issued = service.issue(analysis_id, now + timedelta(hours=1))

    stored = repository.get_access_grants(analysis_id)[0]
    assert stored.token_hash.startswith("$argon2id$")
    assert stored.token_hash != issued.raw_token
    assert issued.grant == stored
    assert service.authorize(analysis_id, issued.raw_token)


def test_authorize_returns_false_for_wrong_token():
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    analysis_id = uuid.uuid4()
    repository = MemoryAccessRepository()
    service = AccessService(repository, clock=lambda: now)
    service.issue(analysis_id, now + timedelta(hours=1))

    assert not service.authorize(analysis_id, "wrong-token")


def test_authorize_verifies_dummy_hash_when_analysis_has_no_active_grant(monkeypatch):
    class RecordingHasher:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def hash(self, raw_token: str) -> str:
            return f"hash:{raw_token}"

        def verify(self, token_hash: str, raw_token: str) -> bool:
            self.calls.append((token_hash, raw_token))
            return False

    hasher = RecordingHasher()
    monkeypatch.setattr(access_module, "PasswordHasher", lambda **_: hasher)
    service = AccessService(MemoryAccessRepository())

    assert not service.authorize(uuid.uuid4(), "candidate")
    assert hasher.calls == [(service._dummy_hash, "candidate")]


def test_authorize_returns_false_after_grant_expires():
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    current_time = [now]
    analysis_id = uuid.uuid4()
    repository = MemoryAccessRepository()
    service = AccessService(repository, clock=lambda: current_time[0])
    issued = service.issue(analysis_id, now + timedelta(hours=1))
    current_time[0] = now + timedelta(hours=1)

    assert not service.authorize(analysis_id, issued.raw_token)


def test_authorize_returns_false_after_grant_is_revoked():
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    analysis_id = uuid.uuid4()
    repository = MemoryAccessRepository()
    service = AccessService(repository, clock=lambda: now)
    issued = service.issue(analysis_id, now + timedelta(hours=1))
    repository.grants[analysis_id][0].revoked_at = now

    assert not service.authorize(analysis_id, issued.raw_token)


def test_issue_rejects_lifetime_longer_than_twenty_four_hours():
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    service = AccessService(MemoryAccessRepository(), clock=lambda: now)

    with pytest.raises(ValueError, match="24 hours"):
        service.issue(uuid.uuid4(), now + timedelta(hours=24, seconds=1))


def test_authorize_treats_malformed_stored_hash_as_denied():
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    analysis_id = uuid.uuid4()
    repository = MemoryAccessRepository()
    repository.save_access_grant(
        AccessGrant(
            analysis_id=analysis_id,
            token_hash="malformed",
            created_at=now,
            expires_at=now + timedelta(hours=1),
            revoked_at=None,
        )
    )
    service = AccessService(repository, clock=lambda: now)

    assert not service.authorize(analysis_id, "candidate")


def test_issue_rejects_non_utc_expiration():
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    service = AccessService(MemoryAccessRepository(), clock=lambda: now)

    with pytest.raises(ValueError, match="UTC"):
        service.issue(uuid.uuid4(), datetime(2026, 8, 8, 1, 0))
