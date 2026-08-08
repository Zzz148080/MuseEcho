from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, File, Response, UploadFile, status
from fastapi.responses import JSONResponse

from museecho.analysis.decode import (
    AudioDecodeError,
    AudioDecodeTimeoutError,
    AudioDurationLimitError,
    AudioToolUnavailableError,
    InvalidAudioError,
)
from museecho.api.security import set_capability_cookies
from museecho.application.uploads import (
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


__all__ = ["create_analyses_router"]
