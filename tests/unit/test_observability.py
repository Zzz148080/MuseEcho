from __future__ import annotations

import json
import logging
import uuid

from fastapi.testclient import TestClient

from museecho.app import create_app
from museecho.domain.status import AnalysisStage
from museecho.observability import RuntimeMetrics


def test_runtime_metrics_record_required_aggregate_signals() -> None:
    metrics = RuntimeMetrics()

    metrics.observe_stage(uuid.UUID(int=1), AnalysisStage.DECODING, 0.25)
    metrics.observe_analysis_failure(uuid.UUID(int=1), AnalysisStage.DECODING, "decode_failed")
    metrics.observe_cleanup(deleted=2)
    metrics.observe_cleanup_failure()
    metrics.observe_explanation(mode="fallback")

    assert metrics.snapshot(queue_length=3, active_analyses=1) == {
        "queue_length": 3,
        "active_analyses": 1,
        "analysis_failure_count": 1,
        "cleanup_deleted_count": 2,
        "cleanup_failure_count": 1,
        "fallback_count": 1,
        "stage_duration_seconds": {"decoding": 0.25},
    }


def test_health_distinguishes_liveness_readiness_and_reports_safe_metrics(
    caplog,
) -> None:
    metrics = RuntimeMetrics()
    app = create_app(
        readiness_check=lambda: False,
        metrics_snapshot=lambda: metrics.snapshot(queue_length=2, active_analyses=1),
    )
    logger = logging.getLogger("museecho.requests")
    previous_disabled = logger.disabled
    logger.disabled = False
    try:
        with caplog.at_level(logging.INFO, logger="museecho.requests"):
            response = TestClient(app).get(
                "/api/health",
                headers={
                    "Authorization": "Bearer credential-shaped-secret",
                    "Cookie": "museecho_access=capability-shaped-secret",
                    "X-Original-Filename": "private-song.wav",
                    "X-Request-ID": "attacker-controlled-request-id",
                },
            )
    finally:
        logger.disabled = previous_disabled

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "liveness": "alive",
        "readiness": "degraded",
        "metrics": {
            "queue_length": 2,
            "active_analyses": 1,
            "analysis_failure_count": 0,
            "cleanup_deleted_count": 0,
            "cleanup_failure_count": 0,
            "fallback_count": 0,
            "stage_duration_seconds": {},
        },
    }
    request_id = response.headers["X-Request-ID"]
    assert len(request_id) == 32
    int(request_id, 16)
    assert request_id != "attacker-controlled-request-id"
    record = json.loads(caplog.records[-1].message)
    assert record == {
        "duration_ms": record["duration_ms"],
        "error_code": "http_503",
        "event": "http_request",
        "request_id": request_id,
        "resource_summary": {"request_bytes": 0, "status_code": 503},
        "stage": "http",
        "task_id": None,
    }
    assert record["duration_ms"] >= 0
    assert "credential-shaped-secret" not in caplog.text
    assert "capability-shaped-secret" not in caplog.text
    assert "private-song.wav" not in caplog.text
    assert "attacker-controlled-request-id" not in caplog.text


def test_unhandled_exception_returns_safe_stable_500_with_request_id(caplog) -> None:
    app = create_app()

    @app.get("/explode")
    def explode() -> None:
        raise RuntimeError("private-song.wav bearer-token complete-question")

    logger = logging.getLogger("museecho.requests")
    previous_disabled = logger.disabled
    logger.disabled = False
    try:
        with caplog.at_level(logging.INFO, logger="museecho.requests"):
            response = TestClient(app, raise_server_exceptions=False).get(
                "/explode",
                headers={"X-Request-ID": "malicious-upstream-id", "Authorization": "token"},
            )
    finally:
        logger.disabled = previous_disabled

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Internal server error"}
    }
    request_id = response.headers["X-Request-ID"]
    assert len(request_id) == 32
    int(request_id, 16)
    assert request_id != "malicious-upstream-id"
    record = json.loads(caplog.records[-1].message)
    assert record["request_id"] == request_id
    assert record["error_code"] == "internal_error"
    assert record["resource_summary"]["status_code"] == 500
    assert "private-song.wav" not in caplog.text
    assert "bearer-token" not in caplog.text
    assert "complete-question" not in caplog.text
    assert "malicious-upstream-id" not in caplog.text


def test_background_failure_log_has_safe_task_stage_and_error_code(caplog) -> None:
    metrics = RuntimeMetrics()
    analysis_id = uuid.UUID("10000000-0000-0000-0000-000000000001")
    logger = logging.getLogger("museecho.analysis")
    previous_disabled = logger.disabled
    logger.disabled = False
    try:
        with caplog.at_level(logging.INFO, logger="museecho.analysis"):
            metrics.observe_analysis_failure(analysis_id, AnalysisStage.DECODING, "decode_failed")
    finally:
        logger.disabled = previous_disabled

    record = json.loads(caplog.records[-1].message)
    assert record == {
        "duration_ms": 0.0,
        "error_code": "decode_failed",
        "event": "analysis_failure",
        "request_id": None,
        "resource_summary": {},
        "stage": "decoding",
        "task_id": str(analysis_id),
    }
    assert metrics.snapshot(queue_length=0, active_analyses=0)["analysis_failure_count"] == 1
