from __future__ import annotations

import uuid
from collections.abc import Collection

from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from museecho.api.dependencies import require_analysis_mutation
from museecho.application.lifecycle import (
    AnalysisLifecycleService,
    ExplanationRateLimitedError,
    ResultNotReadyError,
)
from museecho.domain.ports import AccessService


class ExplanationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    start_seconds: float
    end_seconds: float


def create_explanations_router(
    service: AnalysisLifecycleService,
    access_service: AccessService,
    trusted_origins: Collection[str],
) -> APIRouter:
    router = APIRouter(prefix="/api/analyses", tags=["analysis-explanations"])
    authorize = require_analysis_mutation(access_service, trusted_origins)

    @router.post("/{analysis_id}/explanations", response_model=None)
    def create_explanation(
        analysis_id: uuid.UUID,
        _authorized: uuid.UUID = Depends(authorize),
        payload: object | None = Body(default=None),
    ) -> dict[str, object] | JSONResponse:
        try:
            request = ExplanationRequest.model_validate(payload)
            explanation = service.explain(
                analysis_id,
                question=request.question,
                start_seconds=request.start_seconds,
                end_seconds=request.end_seconds,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Not Found") from None
        except ResultNotReadyError as exc:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"error": {"code": exc.code, "message": str(exc)}},
            )
        except ExplanationRateLimitedError:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": {
                        "code": "explanation_rate_limited",
                        "message": "explanation request rate exceeded",
                    }
                },
                headers={"Retry-After": "60"},
            )
        except (ValidationError, ValueError):
            return _invalid_request()
        return {
            "mode": explanation.mode,
            "text": explanation.text,
            "evidence_ids": explanation.evidence_ids_json,
        }

    return router


def _invalid_request() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "error": {
                "code": "invalid_explanation_request",
                "message": "question or segment is invalid",
            }
        },
    )


__all__ = ["ExplanationRequest", "create_explanations_router"]
