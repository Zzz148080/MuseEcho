from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable, Collection
from typing import Annotated

from fastapi import Cookie, Header, HTTPException, status

from museecho.api.security import ACCESS_COOKIE_NAME, CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from museecho.domain.ports import AccessService


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


def require_analysis_access(service: AccessService) -> Callable[..., uuid.UUID]:
    def authorize(
        analysis_id: uuid.UUID,
        capability: Annotated[str | None, Cookie(alias=ACCESS_COOKIE_NAME)] = None,
    ) -> uuid.UUID:
        if capability is None or not service.authorize(analysis_id, capability):
            raise _not_found()
        return analysis_id

    return authorize


def require_analysis_mutation(
    service: AccessService,
    trusted_origins: Collection[str],
) -> Callable[..., uuid.UUID]:
    allowed_origins = frozenset(trusted_origins)

    def authorize(
        analysis_id: uuid.UUID,
        capability: Annotated[str | None, Cookie(alias=ACCESS_COOKIE_NAME)] = None,
        csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE_NAME)] = None,
        csrf_header: Annotated[str | None, Header(alias=CSRF_HEADER_NAME)] = None,
        origin: Annotated[str | None, Header(alias="Origin")] = None,
    ) -> uuid.UUID:
        csrf_matches = (
            csrf_cookie is not None
            and csrf_header is not None
            and secrets.compare_digest(csrf_cookie, csrf_header)
        )
        if (
            origin not in allowed_origins
            or not csrf_matches
            or capability is None
            or not service.authorize(analysis_id, capability)
        ):
            raise _not_found()
        return analysis_id

    return authorize
