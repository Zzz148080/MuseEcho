from __future__ import annotations

from collections.abc import Collection
from ipaddress import IPv4Network, IPv6Network, ip_address

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from museecho.application.accounts import SESSION_TTL, AccountError, AccountService

SESSION_COOKIE = "museecho_user_session"
CSRF_COOKIE = "museecho_user_csrf"
CSRF_HEADER = "X-User-CSRF-Token"
CLIENT_IP_HEADER = "X-MuseEcho-Client-IP"
IPNetwork = IPv4Network | IPv6Network


class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class EmailInput(BaseModel):
    email: str = Field(max_length=254)


class TokenInput(BaseModel):
    token: str = Field(max_length=200)


class ResetInput(TokenInput):
    password: str = Field(max_length=128)


class DeleteAccountInput(BaseModel):
    password: str = Field(max_length=128)


def require_origin(request: Request, trusted_origins: Collection[str]) -> None:
    if request.headers.get("origin") not in trusted_origins:
        raise HTTPException(status_code=403, detail="Forbidden")


def require_user(request: Request, service: AccountService) -> tuple[str, str]:
    user = service.current_user(request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


def require_user_mutation(
    request: Request, service: AccountService, trusted_origins: Collection[str]
) -> str:
    require_origin(request, trusted_origins)
    user_id = service.authorize_mutation(
        request.cookies.get(SESSION_COOKIE), request.headers.get(CSRF_HEADER)
    )
    if user_id is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user_id


def account_error(exc: AccountError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.code}},
    )


def client_ip(request: Request, trusted_proxy_networks: Collection[IPNetwork]) -> str:
    """Return a proxy supplied address only when the direct peer is trusted."""

    direct = request.client.host if request.client else ""
    try:
        peer = ip_address(direct)
    except ValueError:
        return direct
    if not any(peer in network for network in trusted_proxy_networks):
        return direct
    forwarded = request.headers.get(CLIENT_IP_HEADER, "").strip()
    try:
        return str(ip_address(forwarded))
    except ValueError:
        return direct


def create_accounts_router(
    service: AccountService,
    trusted_origins: Collection[str],
    trusted_proxy_networks: Collection[IPNetwork] = (),
) -> APIRouter:
    router = APIRouter(prefix="/api/account", tags=["account"])

    @router.get("/config")
    def config() -> dict[str, bool]:
        return {"registration_available": service.registration_available}

    @router.post("/register", status_code=202, response_model=None)
    def register(payload: Credentials, request: Request) -> dict[str, str] | JSONResponse:
        require_origin(request, trusted_origins)
        try:
            service.register(
                payload.email,
                payload.password,
                client_ip(request, trusted_proxy_networks),
            )
        except AccountError as exc:
            return account_error(exc)
        return {"status": "check_email"}

    @router.post("/resend-verification", status_code=202, response_model=None)
    def resend(payload: EmailInput, request: Request) -> dict[str, str] | JSONResponse:
        require_origin(request, trusted_origins)
        try:
            service.resend_verification(payload.email, client_ip(request, trusted_proxy_networks))
        except AccountError as exc:
            return account_error(exc)
        return {"status": "check_email"}

    @router.post("/verify", response_model=None)
    def verify(payload: TokenInput, request: Request) -> dict[str, str] | JSONResponse:
        require_origin(request, trusted_origins)
        try:
            service.verify(payload.token)
        except AccountError as exc:
            return account_error(exc)
        return {"status": "verified"}

    @router.post("/login", response_model=None)
    def login(
        payload: Credentials, request: Request, response: Response
    ) -> dict[str, str] | JSONResponse:
        require_origin(request, trusted_origins)
        try:
            grant = service.login(
                payload.email, payload.password, client_ip(request, trusted_proxy_networks)
            )
        except AccountError as exc:
            return account_error(exc)
        age = int(SESSION_TTL.total_seconds())
        response.set_cookie(
            SESSION_COOKIE,
            grant.raw_token,
            max_age=age,
            path="/api",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        response.set_cookie(
            CSRF_COOKIE,
            grant.csrf_token,
            max_age=age,
            path="/",
            secure=True,
            httponly=False,
            samesite="strict",
        )
        return {"id": grant.user_id, "email": grant.email}

    @router.get("/me")
    def me(request: Request) -> dict[str, str]:
        user_id, email = require_user(request, service)
        return {"id": user_id, "email": email}

    @router.post("/logout", status_code=204)
    def logout(request: Request, response: Response) -> None:
        require_user_mutation(request, service, trusted_origins)
        raw = request.cookies.get(SESSION_COOKIE)
        if raw:
            service.logout(raw)
        response.delete_cookie(
            SESSION_COOKIE, path="/api", secure=True, httponly=True, samesite="strict"
        )
        response.delete_cookie(
            CSRF_COOKIE, path="/", secure=True, httponly=False, samesite="strict"
        )

    @router.post("/request-reset", status_code=202, response_model=None)
    def request_reset(payload: EmailInput, request: Request) -> dict[str, str] | JSONResponse:
        require_origin(request, trusted_origins)
        try:
            service.request_reset(payload.email, client_ip(request, trusted_proxy_networks))
        except AccountError as exc:
            return account_error(exc)
        return {"status": "check_email"}

    @router.post("/reset-password", response_model=None)
    def reset_password(payload: ResetInput, request: Request) -> dict[str, str] | JSONResponse:
        require_origin(request, trusted_origins)
        try:
            service.reset_password(payload.token, payload.password)
        except AccountError as exc:
            return account_error(exc)
        return {"status": "password_reset"}

    @router.delete("/me", status_code=204, response_model=None)
    def delete_me(
        payload: DeleteAccountInput, request: Request, response: Response
    ) -> None | JSONResponse:
        user_id = require_user_mutation(request, service, trusted_origins)
        try:
            service.delete_account(user_id, payload.password)
        except AccountError as exc:
            return account_error(exc)
        response.delete_cookie(
            SESSION_COOKIE, path="/api", secure=True, httponly=True, samesite="strict"
        )
        response.delete_cookie(
            CSRF_COOKIE, path="/", secure=True, httponly=False, samesite="strict"
        )
        return None

    return router
