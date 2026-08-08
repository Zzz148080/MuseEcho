from __future__ import annotations

import secrets

from fastapi import Response

from museecho.domain.models import IssuedAccess

ACCESS_COOKIE_NAME = "museecho_access"
CSRF_COOKIE_NAME = "museecho_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
MAX_CAPABILITY_AGE_SECONDS = 24 * 60 * 60


def set_capability_cookies(response: Response, issued: IssuedAccess) -> str:
    grant = issued.grant
    max_age = min(
        int((grant.expires_at - grant.created_at).total_seconds()),
        MAX_CAPABILITY_AGE_SECONDS,
    )
    path = f"/api/analyses/{grant.analysis_id}"
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        ACCESS_COOKIE_NAME,
        issued.raw_token,
        max_age=max_age,
        expires=grant.expires_at,
        path=path,
        secure=True,
        httponly=True,
        samesite="strict",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        max_age=max_age,
        expires=grant.expires_at,
        path=path,
        secure=True,
        httponly=False,
        samesite="strict",
    )
    return csrf_token
