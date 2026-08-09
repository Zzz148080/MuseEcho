from __future__ import annotations

import uuid
from collections.abc import Collection
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse

from museecho.api.dependencies import require_analysis_access, require_analysis_mutation
from museecho.api.security import clear_analysis_access_cookie
from museecho.application.lifecycle import AnalysisLifecycleService, ResultNotReadyError
from museecho.domain.models import AnalysisResult
from museecho.domain.ports import AccessService


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def create_results_router(
    service: AnalysisLifecycleService,
    access_service: AccessService,
    trusted_origins: Collection[str],
) -> APIRouter:
    router = APIRouter(prefix="/api/analyses", tags=["analysis-results"])
    authorize = require_analysis_access(access_service)
    authorize_mutation = require_analysis_mutation(access_service, trusted_origins)

    @router.get("/{analysis_id}/status")
    def get_status(
        analysis_id: uuid.UUID,
        _authorized: uuid.UUID = Depends(authorize),
    ) -> dict[str, object]:
        try:
            job = service.status(analysis_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Not Found") from None
        return {
            "analysis_id": str(job.id),
            "status": job.status.value,
            "stage": job.stage.value,
            "progress": job.progress,
            "error_code": job.error_code,
            "expires_at": None if job.expires_at is None else job.expires_at.isoformat(),
            "pipeline_version": job.pipeline_version,
            "source_kind": job.source_kind.value,
        }

    @router.get("/{analysis_id}", response_model=None)
    def get_result(
        analysis_id: uuid.UUID,
        _authorized: uuid.UUID = Depends(authorize),
    ) -> dict[str, Any] | JSONResponse:
        try:
            result = service.result(analysis_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Not Found") from None
        except ResultNotReadyError as exc:
            return _error(status.HTTP_409_CONFLICT, exc.code, str(exc))
        except ValueError:
            return _error(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "invalid_analysis_result",
                "stored analysis result is invalid",
            )
        try:
            job = service.status(analysis_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Not Found") from None
        return _serialize_result(result, job.source_kind.value, job.pipeline_version)

    @router.delete("/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_analysis(
        analysis_id: uuid.UUID,
        response: Response,
        _authorized: uuid.UUID = Depends(authorize_mutation),
    ) -> None:
        service.delete(analysis_id)
        clear_analysis_access_cookie(response, analysis_id)

    return router


def _serialize_result(
    result: AnalysisResult,
    source_kind: str,
    pipeline_version: str | None,
) -> dict[str, Any]:
    track = result.track
    return {
        "analysis_id": str(track.analysis_id),
        "source_kind": source_kind,
        "pipeline_version": pipeline_version,
        "track": {
            "duration_seconds": track.duration_seconds,
            "sample_rate": track.sample_rate,
            "channels": track.channels,
            "bpm": track.bpm,
            "bpm_confidence": track.bpm_confidence,
            "key_tonic": track.key_tonic,
            "mode": track.mode,
            "key_confidence": track.key_confidence,
            "time_signature": track.time_signature,
            "time_signature_confidence": track.time_signature_confidence,
            "summary": track.summary_json,
        },
        "sections": [
            {
                "id": str(item.id),
                "start_seconds": item.start_seconds,
                "end_seconds": item.end_seconds,
                "label": item.label,
                "confidence": item.confidence,
                "algorithm": item.algorithm,
            }
            for item in result.sections
        ],
        "chords": [
            {
                "id": str(item.id),
                "start_seconds": item.start_seconds,
                "end_seconds": item.end_seconds,
                "symbol": item.symbol,
                "confidence": item.confidence,
                "algorithm": item.algorithm,
                "theory": item.theory_json,
            }
            for item in result.chords
        ],
        "time_series": [
            {
                "kind": item.kind,
                "resolution_seconds": item.resolution_seconds,
                "points": item.points_json,
                "algorithm": item.algorithm,
            }
            for item in result.time_series
        ],
        "evidence": [
            {
                "id": str(item.id),
                "kind": item.kind,
                "start_seconds": item.start_seconds,
                "end_seconds": item.end_seconds,
                "value": item.public_value,
                "confidence": item.confidence,
                "algorithm": item.algorithm,
                "eligible_for_llm": item.eligible_for_llm,
            }
            for item in result.evidence
        ],
    }


__all__ = ["create_results_router"]
