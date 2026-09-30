from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

import httpx2

from museecho.infrastructure.secrets import SecretStore

_ALGORITHM = "TC3-HMAC-SHA256"
_HOST = "ses.tencentcloudapi.com"
_ENDPOINT = f"https://{_HOST}"
_SERVICE = "ses"
_VERSION = "2020-10-02"
_ACTION = "SendEmail"
_REGION = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
_MAX_RESPONSE_BYTES = 65_536


class TencentSESError(RuntimeError):
    pass


@dataclass(frozen=True)
class SESResponse:
    status_code: int
    content: bytes


class SESTransport(Protocol):
    def post(self, *, url: str, headers: dict[str, str], content: bytes) -> SESResponse: ...


class HttpxSESTransport:
    def __init__(self, transport: httpx2.BaseTransport | None = None) -> None:
        self._transport = transport

    def post(self, *, url: str, headers: dict[str, str], content: bytes) -> SESResponse:
        timeout = httpx2.Timeout(15.0, connect=5.0)
        try:
            with httpx2.Client(
                timeout=timeout,
                follow_redirects=False,
                transport=self._transport,
                trust_env=False,
            ) as client:
                with client.stream("POST", url, headers=headers, content=content) as response:
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                            raise TencentSESError("Tencent SES response exceeded its size limit.")
                        body.extend(chunk)
                    return SESResponse(response.status_code, bytes(body))
        except TencentSESError:
            raise
        except httpx2.HTTPError:
            raise TencentSESError("Tencent SES request failed.") from None


@dataclass(frozen=True)
class TencentSESConfig:
    region: str
    sender: str
    verify_template_id: int
    reset_template_id: int

    def __post_init__(self) -> None:
        if not _REGION.fullmatch(self.region):
            raise ValueError("Tencent SES region is invalid")
        if not self.sender.strip() or len(self.sender) > 320:
            raise ValueError("Tencent SES sender is invalid")
        if self.verify_template_id < 1 or self.reset_template_id < 1:
            raise ValueError("Tencent SES template IDs must be positive")


class TencentSESMailer:
    def __init__(
        self,
        config: TencentSESConfig,
        secret_id_store: SecretStore,
        secret_key_store: SecretStore,
        *,
        transport: SESTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._secret_id_store = secret_id_store
        self._secret_key_store = secret_key_store
        self._transport = transport or HttpxSESTransport()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def send(
        self,
        address: str,
        subject: str,
        body: str,
        *,
        template_key: str | None = None,
        template_data: dict[str, str] | None = None,
    ) -> None:
        secret_id = self._secret_id_store.get()
        secret_key = self._secret_key_store.get()
        if not secret_id or not secret_key:
            raise TencentSESError("Tencent SES credentials are unavailable.")
        template_ids = {
            "verify": self._config.verify_template_id,
            "reset": self._config.reset_template_id,
        }
        if template_key not in template_ids or template_data is None:
            raise TencentSESError("Tencent SES template data is unavailable.")
        payload = _payload(
            self._config.sender,
            address,
            subject,
            body,
            template_id=template_ids[template_key],
            template_data=template_data,
        )
        headers = _signed_headers(
            payload,
            secret_id,
            secret_key,
            self._config.region,
            self._clock(),
        )
        response = self._transport.post(url=_ENDPOINT, headers=headers, content=payload)
        _validate_response(response)

    def __repr__(self) -> str:
        return f"TencentSESMailer(region={self._config.region!r}, sender={self._config.sender!r})"


def _payload(
    sender: str,
    address: str,
    subject: str,
    body: str,
    *,
    template_id: int | None = None,
    template_data: dict[str, str] | None = None,
) -> bytes:
    if not address or len(address) > 254:
        raise ValueError("recipient address is invalid")
    if not subject or len(subject) > 998:
        raise ValueError("email subject is invalid")
    if not body or len(body.encode("utf-8")) > 1_000_000:
        raise ValueError("email body is invalid")
    value: dict[str, object] = {
        "FromEmailAddress": sender,
        "Destination": [address],
        "Subject": subject,
    }
    if template_id is None and template_data is None:
        value["Simple"] = {
            "Text": base64.b64encode(body.encode("utf-8")).decode("ascii")
        }
    elif template_id is not None and template_id > 0 and template_data is not None:
        value["Template"] = {
            "TemplateID": template_id,
            "TemplateData": json.dumps(
                template_data,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
    else:
        raise ValueError("template ID and data must be configured together")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _signed_headers(
    payload: bytes,
    secret_id: str,
    secret_key: str,
    region: str,
    now: datetime,
) -> dict[str, str]:
    timestamp = int(now.astimezone(timezone.utc).timestamp())
    date = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
    # Match Tencent Cloud's official SDK exactly. Some API gateways validate
    # the signed Content-Type as the media type rather than preserving charset
    # parameters during canonicalization.
    content_type = "application/json"
    canonical_headers = f"content-type:{content_type}\nhost:{_HOST}\n"
    signed_headers = "content-type;host"
    hashed_payload = hashlib.sha256(payload).hexdigest()
    canonical_request = (
        "POST\n/\n\n"
        f"{canonical_headers}\n"
        f"{signed_headers}\n"
        f"{hashed_payload}"
    )
    credential_scope = f"{date}/{_SERVICE}/tc3_request"
    string_to_sign = (
        f"{_ALGORITHM}\n{timestamp}\n{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    )
    secret_date = _hmac_sha256((f"TC3{secret_key}").encode("utf-8"), date)
    secret_service = _hmac_sha256(secret_date, _SERVICE)
    secret_signing = _hmac_sha256(secret_service, "tc3_request")
    signature = hmac.new(
        secret_signing,
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    authorization = (
        f"{_ALGORITHM} Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "Authorization": authorization,
        "Content-Type": content_type,
        "Host": _HOST,
        "X-TC-Action": _ACTION,
        "X-TC-Region": region,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": _VERSION,
    }


def _hmac_sha256(key: bytes, value: str) -> bytes:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()


def _validate_response(response: SESResponse) -> None:
    try:
        payload = json.loads(response.content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise TencentSESError("Tencent SES returned an invalid response.") from None
    response_body = payload.get("Response") if isinstance(payload, dict) else None
    if response.status_code != 200 or not isinstance(response_body, dict):
        raise TencentSESError("Tencent SES returned an unsuccessful response.")
    if "Error" in response_body:
        raise TencentSESError("Tencent SES rejected the email.")
    if not isinstance(response_body.get("MessageId"), str):
        raise TencentSESError("Tencent SES response did not include a message ID.")
