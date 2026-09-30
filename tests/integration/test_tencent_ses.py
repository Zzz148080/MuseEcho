from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from museecho.infrastructure.tencent_ses import (
    SESResponse,
    TencentSESConfig,
    TencentSESError,
    TencentSESMailer,
)


class Secret:
    source = "test"

    def __init__(self, value: str | None) -> None:
        self.value = value

    def get(self) -> str | None:
        return self.value


class Transport:
    def __init__(self, response: SESResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def post(self, **kwargs) -> SESResponse:
        self.calls.append(kwargs)
        return self.response


def _mailer(transport: Transport, *, secret_id: str | None = "AKIDEXAMPLE") -> TencentSESMailer:
    return TencentSESMailer(
        TencentSESConfig(
            "ap-hongkong",
            "MuseEcho <no-reply@mail.toolgate.cloud>",
            1001,
            1002,
        ),
        Secret(secret_id),
        Secret("secret-key"),
        transport=transport,
        clock=lambda: datetime(2026, 9, 28, 15, 0, tzinfo=timezone.utc),
    )


def test_tencent_ses_mailer_signs_and_sends_template_email() -> None:
    transport = Transport(
        SESResponse(200, b'{"Response":{"MessageId":"message-1","RequestId":"request-1"}}')
    )

    _mailer(transport).send(
        "listener@example.com",
        "MuseEcho 邮箱验证",
        "验证正文",
        template_key="verify",
        template_data={"verify_token": "token-1", "expire_hours": "24"},
    )

    assert len(transport.calls) == 1
    call = transport.calls[0]
    payload = json.loads(call["content"])
    assert payload["FromEmailAddress"] == "MuseEcho <no-reply@mail.toolgate.cloud>"
    assert payload["Destination"] == ["listener@example.com"]
    assert payload["Template"]["TemplateID"] == 1001
    assert json.loads(payload["Template"]["TemplateData"]) == {
        "verify_token": "token-1",
        "expire_hours": "24",
    }
    assert "Simple" not in payload
    headers = call["headers"]
    assert headers["Content-Type"] == "application/json"
    assert headers["X-TC-Action"] == "SendEmail"
    assert headers["X-TC-Region"] == "ap-hongkong"
    assert headers["X-TC-Timestamp"] == "1790607600"
    assert headers["Authorization"].startswith(
        "TC3-HMAC-SHA256 Credential=AKIDEXAMPLE/2026-09-28/ses/tc3_request"
    )
    assert "SignedHeaders=content-type;host" in headers["Authorization"]
    assert headers["Authorization"].endswith(
        "Signature=4b007b28bdbf92eafd6dead0b54d38142e13deddd43db44490b6015453741046"
    )
    assert "secret-key" not in json.dumps(headers)
    assert b"secret-key" not in call["content"]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (SESResponse(500, b"{}"), "unsuccessful"),
        (
            SESResponse(200, b'{"Response":{"Error":{"Code":"Failed"}}}'),
            "rejected",
        ),
        (SESResponse(200, b"not-json"), "invalid"),
    ],
)
def test_tencent_ses_mailer_rejects_provider_failures(
    response: SESResponse,
    message: str,
) -> None:
    with pytest.raises(TencentSESError, match=message):
        _mailer(Transport(response)).send(
            "listener@example.com",
            "subject",
            "body",
            template_key="reset",
            template_data={"reset_token": "token-2", "expire_minutes": "60"},
        )


def test_tencent_ses_mailer_requires_credentials_without_calling_transport() -> None:
    transport = Transport(SESResponse(200, b"{}"))

    with pytest.raises(TencentSESError, match="credentials"):
        _mailer(transport, secret_id=None).send("listener@example.com", "subject", "body")

    assert transport.calls == []
