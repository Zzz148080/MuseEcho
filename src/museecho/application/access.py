from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Protocol

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

from museecho.domain.models import AccessGrant, IssuedAccess


class AccessGrantRepository(Protocol):
    def save_access_grant(self, grant: AccessGrant) -> None: ...

    def get_access_grants(self, analysis_id: uuid.UUID) -> list[AccessGrant]: ...


class AccessService:
    def __init__(
        self,
        repository: AccessGrantRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._hasher = PasswordHasher(type=Type.ID)
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(32))

    def issue(self, analysis_id: uuid.UUID, expires_at: datetime) -> IssuedAccess:
        created_at = self._clock()
        if expires_at.tzinfo is None or expires_at.utcoffset() != timedelta(0):
            raise ValueError("expires_at must be an aware UTC datetime")
        if expires_at - created_at > timedelta(hours=24):
            raise ValueError("capability lifetime cannot exceed 24 hours")
        raw_token = secrets.token_urlsafe(32)
        grant = AccessGrant(
            analysis_id=analysis_id,
            token_hash=self._hasher.hash(raw_token),
            created_at=created_at,
            expires_at=expires_at,
            revoked_at=None,
        )
        self._repository.save_access_grant(grant)
        return IssuedAccess(raw_token=raw_token, grant=grant)

    def authorize(self, analysis_id: uuid.UUID, raw_token: str) -> bool:
        grants = self._repository.get_access_grants(analysis_id)
        now = self._clock()
        matched = False
        verified_well_formed_hash = False
        for grant in grants:
            if grant.revoked_at is not None or grant.expires_at <= now:
                continue
            try:
                matched = self._hasher.verify(grant.token_hash, raw_token) or matched
                verified_well_formed_hash = True
            except InvalidHashError:
                continue
            except VerificationError:
                verified_well_formed_hash = True
        if not verified_well_formed_hash:
            try:
                self._hasher.verify(self._dummy_hash, raw_token)
            except VerificationError:
                pass
        return matched
