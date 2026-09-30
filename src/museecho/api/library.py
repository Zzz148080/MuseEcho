from __future__ import annotations

import uuid
from collections.abc import Collection
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from museecho.api.accounts import require_user, require_user_mutation
from museecho.api.security import ACCESS_COOKIE_NAME
from museecho.application.library import LibraryError, LibraryService
from museecho.domain.ports import AccessService


class SaveInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class UpdateInput(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    preference: str | None = None


class ProfileInput(BaseModel):
    enabled: bool


def _error(exc: LibraryError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.code}},
    )


def create_library_router(
    library: LibraryService,
    accounts: Any,
    access: AccessService,
    trusted_origins: Collection[str],
) -> APIRouter:
    router = APIRouter(prefix="/api/library", tags=["library"])

    @router.get("", response_model=None)
    def list_saved(
        request: Request,
        offset: int = 0,
        limit: int = 20,
        q: str = "",
        sort: str = "newest",
    ) -> dict[str, Any] | JSONResponse:
        user_id, _ = require_user(request, accounts)
        try:
            return library.list(user_id, offset=offset, limit=limit, query=q, sort=sort)
        except LibraryError as exc:
            return _error(exc)

    @router.get("/profile")
    def profile(request: Request) -> dict[str, Any]:
        user_id, _ = require_user(request, accounts)
        return library.profile(user_id)

    @router.patch("/profile")
    def set_profile(payload: ProfileInput, request: Request) -> dict[str, Any]:
        user_id = require_user_mutation(request, accounts, trusted_origins)
        return library.set_profile_enabled(user_id, payload.enabled)

    @router.get("/export")
    def export(request: Request) -> dict[str, Any]:
        user_id, email = require_user(request, accounts)
        page = library.list(user_id, offset=0, limit=100)
        return {
            "version": 1,
            "account": {"email": email},
            "profile": library.profile(user_id),
            "items": [library.get(user_id, uuid.UUID(item["id"])) for item in page["items"]],
        }

    @router.get("/{saved_id}", response_model=None)
    def get_saved(saved_id: uuid.UUID, request: Request) -> dict[str, Any] | JSONResponse:
        user_id, _ = require_user(request, accounts)
        try:
            return library.get(user_id, saved_id)
        except LibraryError as exc:
            return _error(exc)

    @router.patch("/{saved_id}", response_model=None)
    def update_saved(
        saved_id: uuid.UUID, payload: UpdateInput, request: Request
    ) -> dict[str, Any] | JSONResponse:
        user_id = require_user_mutation(request, accounts, trusted_origins)
        try:
            return library.update(
                user_id, saved_id, title=payload.title, preference=payload.preference
            )
        except LibraryError as exc:
            return _error(exc)

    @router.delete("/{saved_id}", status_code=204, response_model=None)
    def delete_saved(saved_id: uuid.UUID, request: Request) -> None | JSONResponse:
        user_id = require_user_mutation(request, accounts, trusted_origins)
        try:
            library.delete(user_id, saved_id)
        except LibraryError as exc:
            return _error(exc)
        return None

    return router


def create_library_save_router(
    library: LibraryService,
    accounts: Any,
    access: AccessService,
    trusted_origins: Collection[str],
) -> APIRouter:
    router = APIRouter(prefix="/api/analyses", tags=["library"])

    @router.post("/{analysis_id}/save", status_code=201, response_model=None)
    def save(
        analysis_id: uuid.UUID, payload: SaveInput, request: Request
    ) -> dict[str, Any] | JSONResponse:
        user_id = require_user_mutation(request, accounts, trusted_origins)
        capability = request.cookies.get(ACCESS_COOKIE_NAME)
        if capability is None or not access.authorize(analysis_id, capability):
            raise HTTPException(status_code=404, detail="Not Found")
        try:
            return library.save(user_id, analysis_id, payload.title)
        except LibraryError as exc:
            return _error(exc)

    return router
