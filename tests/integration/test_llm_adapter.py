import json
import uuid

import httpx2
import pytest

from museecho.application.explanations import ExplanationService
from museecho.domain.models import Evidence
from museecho.infrastructure.llm import (
    HttpResponse,
    HttpxTransport,
    OpenAICompatibleProvider,
    ProviderConfig,
    ProviderResponseError,
    ProviderTransportError,
)


class Secret:
    source = "test"

    def __init__(self, value: str | None = "secret-key") -> None:
        self.value = value

    def get(self) -> str | None:
        return self.value


class Transport:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls = []

    def post(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _evidence() -> tuple[Evidence, ...]:
    analysis_id = uuid.uuid4()
    return (
        Evidence(
            uuid.uuid4(),
            analysis_id,
            "chord",
            1.0,
            3.0,
            {"symbol": "G"},
            0.9,
            "chroma-v1",
            True,
        ),
    )


def _response(text: str, evidence_id: uuid.UUID) -> HttpResponse:
    content = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"text": text, "evidence_ids": [str(evidence_id)]},
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }
    ).encode()
    return HttpResponse(200, content)


def test_openai_compatible_adapter_sends_structured_evidence_and_parses_schema():
    evidence = _evidence()
    transport = Transport([_response("这里的属和弦带来未解决感。", evidence[0].id)])
    provider = OpenAICompatibleProvider(
        ProviderConfig("https://provider.example/v1", "model-a"),
        Secret(),
        transport=transport,
    )

    draft = provider.explain("为什么有张力？", evidence)

    assert draft.mode == "llm"
    assert draft.evidence_ids == (evidence[0].id,)
    request = json.loads(transport.calls[0]["content"])
    assert request["model"] == "model-a"
    assert str(evidence[0].id) in request["messages"][1]["content"]
    assert "secret-key" not in transport.calls[0]["content"].decode()


def _service(transport, *, secret: str | None = "secret-key"):
    provider = OpenAICompatibleProvider(
        ProviderConfig("https://provider.example/v1", "model-a"),
        Secret(secret),
        transport=transport,
    )
    return ExplanationService(provider), provider


def test_missing_secret_skips_http_and_falls_back():
    evidence = _evidence()
    transport = Transport([])
    service, _ = _service(transport, secret=None)

    answer = service.explain("为什么？", evidence)

    assert answer.mode == "fallback"
    assert answer.evidence_ids == (evidence[0].id,)
    assert transport.calls == []


@pytest.mark.parametrize("status_code", [408, 429, 500, 503])
def test_transient_status_retries_once_then_uses_success(status_code):
    evidence = _evidence()
    transport = Transport(
        [HttpResponse(status_code, b"error"), _response("受证据约束的解释。", evidence[0].id)]
    )
    service, _ = _service(transport)

    answer = service.explain("为什么？", evidence)

    assert answer.mode == "llm"
    assert len(transport.calls) == 2


def test_non_retryable_status_calls_once_and_falls_back():
    evidence = _evidence()
    transport = Transport([HttpResponse(400, b"bad request")])
    service, _ = _service(transport)

    answer = service.explain("为什么？", evidence)

    assert answer.mode == "fallback"
    assert len(transport.calls) == 1


def test_two_transient_failures_stop_after_single_retry():
    evidence = _evidence()
    transport = Transport([HttpResponse(500, b"error"), HttpResponse(503, b"error")])
    service, _ = _service(transport)

    answer = service.explain("为什么？", evidence)

    assert answer.mode == "fallback"
    assert len(transport.calls) == 2


def test_expired_total_timeout_budget_skips_transport(monkeypatch):
    evidence = _evidence()
    transport = Transport([])
    service, _ = _service(transport)
    moments = iter([0.0, 16.0])
    monkeypatch.setattr("museecho.infrastructure.llm.time.monotonic", lambda: next(moments))

    answer = service.explain("为什么？", evidence)

    assert answer.mode == "fallback"
    assert transport.calls == []


def test_request_limit_and_invalid_secret_fail_before_network():
    evidence = _evidence()
    transport = Transport([])
    limited_provider = OpenAICompatibleProvider(
        ProviderConfig(
            "https://provider.example/v1",
            "model-a",
            request_limit_bytes=1,
        ),
        Secret(),
        transport=transport,
    )
    invalid_secret_provider = OpenAICompatibleProvider(
        ProviderConfig("https://provider.example/v1", "model-a"),
        Secret("secret\ninjected"),
        transport=transport,
    )

    assert ExplanationService(limited_provider).explain("为什么？", evidence).mode == "fallback"
    assert (
        ExplanationService(invalid_secret_provider).explain("为什么？", evidence).mode == "fallback"
    )
    assert transport.calls == []


@pytest.mark.parametrize(
    "outcomes",
    [
        [HttpResponse(200, b"not-json")],
        [
            HttpResponse(
                200,
                json.dumps(
                    {
                        "choices": [
                            {"message": {"content": '{"text":"x","evidence_ids":[],"extra":1}'}}
                        ]
                    }
                ).encode(),
            )
        ],
        [ProviderResponseError("response too large")],
        [ProviderTransportError("timeout"), ProviderTransportError("timeout")],
    ],
)
def test_invalid_response_and_transport_failures_fall_back(outcomes):
    evidence = _evidence()
    transport = Transport(outcomes)
    service, provider = _service(transport)

    answer = service.explain("为什么？", evidence)

    assert answer.mode == "fallback"
    assert "secret-key" not in repr(provider)


def test_unknown_response_evidence_id_falls_back():
    evidence = _evidence()
    transport = Transport([_response("引用了未知证据。", uuid.uuid4())])
    service, _ = _service(transport)

    answer = service.explain("为什么？", evidence)

    assert answer.mode == "fallback"
    assert answer.evidence_ids == (evidence[0].id,)


@pytest.mark.parametrize(
    "config_args",
    [
        ("http://provider.example/v1", "model"),
        ("https://user:pass@provider.example/v1", "model"),
        ("https://provider.example/v1?secret=x", "model"),
        ("https://provider.example/v1", ""),
    ],
)
def test_provider_config_rejects_unsafe_endpoint_and_model(config_args):
    with pytest.raises(ValueError):
        ProviderConfig(*config_args)


def test_real_http_transport_streams_with_limit_and_does_not_follow_redirects():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(
            307,
            headers={"Location": "https://attacker.example/collect"},
            content=b"bounded response",
        )

    transport = HttpxTransport(httpx2.MockTransport(handler))
    response = transport.post(
        url="https://provider.example/v1/chat/completions",
        headers={"Authorization": "Bearer test-secret"},
        content=b"{}",
        connect_timeout_seconds=1.0,
        total_timeout_seconds=2.0,
        response_limit_bytes=32,
    )

    assert response.status_code == 307
    assert len(requests) == 1

    with pytest.raises(ProviderResponseError, match="size limit"):
        transport.post(
            url="https://provider.example/v1/chat/completions",
            headers={"Authorization": "Bearer test-secret"},
            content=b"{}",
            connect_timeout_seconds=1.0,
            total_timeout_seconds=2.0,
            response_limit_bytes=4,
        )
