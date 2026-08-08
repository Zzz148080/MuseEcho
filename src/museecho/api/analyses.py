from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, FastAPI, File, Response, UploadFile, status
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from museecho.analysis.decode import (
    AudioDecodeError,
    AudioDecodeTimeoutError,
    AudioDurationLimitError,
    AudioToolUnavailableError,
    InvalidAudioError,
)
from museecho.api.security import set_capability_cookies
from museecho.application.uploads import (
    DEFAULT_MAX_UPLOAD_BYTES,
    UnsupportedAudioError,
    UploadError,
    UploadSubmissionService,
    UploadTooLargeError,
)


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def create_analyses_router(service: UploadSubmissionService) -> APIRouter:
    router = APIRouter(prefix="/api/analyses", tags=["analyses"])

    @router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=None)
    def create_analysis(
        response: Response,
        file: Annotated[UploadFile | str, File(...)],
    ) -> Mapping[str, str | float] | JSONResponse:
        if isinstance(file, str):
            return _error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "unsupported_audio",
                "an audio file is required",
            )
        try:
            submitted = service.submit(
                file.file,
                filename=file.filename or "",
                media_type=file.content_type,
            )
        except UploadTooLargeError as exc:
            return _error(status.HTTP_413_CONTENT_TOO_LARGE, exc.code, str(exc))
        except UnsupportedAudioError as exc:
            return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.code, str(exc))
        except AudioDurationLimitError as exc:
            return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.code, str(exc))
        except InvalidAudioError as exc:
            return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.code, str(exc))
        except AudioDecodeTimeoutError as exc:
            return _error(status.HTTP_503_SERVICE_UNAVAILABLE, exc.code, str(exc))
        except AudioToolUnavailableError as exc:
            return _error(status.HTTP_503_SERVICE_UNAVAILABLE, exc.code, str(exc))
        except (UploadError, AudioDecodeError) as exc:
            return _error(status.HTTP_500_INTERNAL_SERVER_ERROR, exc.code, str(exc))

        set_capability_cookies(response, submitted.access)
        return {
            "analysis_id": str(submitted.job.id),
            "stage": submitted.job.stage.value,
            "progress": submitted.job.progress,
        }

    return router


DEFAULT_REQUEST_OVERHEAD_BYTES = 64 * 1024
DEFAULT_MAX_UPLOAD_REQUEST_BYTES = DEFAULT_MAX_UPLOAD_BYTES + DEFAULT_REQUEST_OVERHEAD_BYTES


class UploadBodyLimitMiddleware:
    """Reject oversized upload bodies before multipart parsing can spool them."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_bytes: int = DEFAULT_MAX_UPLOAD_REQUEST_BYTES,
    ) -> None:
        if max_body_bytes <= 0 or max_body_bytes > DEFAULT_MAX_UPLOAD_REQUEST_BYTES:
            raise ValueError("max_body_bytes must be within the supported limit")
        self._app = app
        self._max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not _is_analysis_upload(scope):
            await self._app(scope, receive, send)
            return
        content_length = _content_length(scope)
        if content_length is not None and content_length > self._max_body_bytes:
            await _send_upload_too_large(scope, receive, send)
            return

        received = 0
        too_large = False
        buffered_messages: list[Message] = []

        async def limited_receive() -> Message:
            nonlocal received, too_large
            if too_large:
                return {"type": "http.request", "body": b"", "more_body": False}
            message = await receive()
            if message["type"] == "http.request":
                next_total = received + len(message.get("body", b""))
                if next_total > self._max_body_bytes:
                    too_large = True
                    return {"type": "http.request", "body": b"", "more_body": False}
                received = next_total
            return message

        async def limited_send(message: Message) -> None:
            buffered_messages.append(message)

        try:
            await self._app(scope, limited_receive, limited_send)
        except Exception:
            if not too_large:
                raise
        if too_large:
            await _send_upload_too_large(scope, receive, send)
            return
        for message in buffered_messages:
            await send(message)


def install_analyses_api(
    app: FastAPI,
    service: UploadSubmissionService,
    *,
    max_body_bytes: int = DEFAULT_MAX_UPLOAD_REQUEST_BYTES,
) -> None:
    app.add_middleware(UploadBodyLimitMiddleware, max_body_bytes=max_body_bytes)
    app.include_router(create_analyses_router(service))


def _is_analysis_upload(scope: Scope) -> bool:
    return (
        scope["type"] == "http"
        and scope.get("method") == "POST"
        and str(scope.get("path", "")).rstrip("/") == "/api/analyses"
    )


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", ()):
        if name.lower() == b"content-length":
            try:
                parsed = int(value)
            except ValueError:
                return None
            return max(0, parsed)
    return None


async def _send_upload_too_large(scope: Scope, receive: Receive, send: Send) -> None:
    response = _error(
        status.HTTP_413_CONTENT_TOO_LARGE,
        "upload_too_large",
        "upload request exceeds the supported size",
    )
    await response(scope, receive, send)


__all__ = [
    "DEFAULT_MAX_UPLOAD_REQUEST_BYTES",
    "UploadBodyLimitMiddleware",
    "create_analyses_router",
    "install_analyses_api",
]
