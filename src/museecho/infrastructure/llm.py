from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx2

from museecho.application.evidence import select_for_segment
from museecho.domain.models import Evidence, ExplanationDraft
from museecho.infrastructure.secrets import MAX_SECRET_LENGTH, SecretStore


class ProviderError(RuntimeError):
    pass


class ProviderUnavailableError(ProviderError):
    pass


class ProviderTransportError(ProviderError):
    pass


class ProviderResponseError(ProviderError):
    pass


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    content: bytes


class HttpTransport(Protocol):
    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        content: bytes,
        connect_timeout_seconds: float,
        total_timeout_seconds: float,
        response_limit_bytes: int,
    ) -> HttpResponse: ...


class HttpxTransport:
    def __init__(self, transport: httpx2.BaseTransport | None = None) -> None:
        self._client_transport = transport

    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        content: bytes,
        connect_timeout_seconds: float,
        total_timeout_seconds: float,
        response_limit_bytes: int,
    ) -> HttpResponse:
        timeout = httpx2.Timeout(
            total_timeout_seconds,
            connect=min(connect_timeout_seconds, total_timeout_seconds),
        )
        try:
            with httpx2.Client(
                timeout=timeout,
                follow_redirects=False,
                transport=self._client_transport,
            ) as client:
                with client.stream("POST", url, headers=headers, content=content) as response:
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        if len(body) + len(chunk) > response_limit_bytes:
                            raise ProviderResponseError(
                                "Provider response exceeded its size limit."
                            )
                        body.extend(chunk)
                    return HttpResponse(response.status_code, bytes(body))
        except ProviderResponseError:
            raise
        except httpx2.HTTPError:
            raise ProviderTransportError("Provider request failed.") from None


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str
    model: str
    connect_timeout_seconds: float = 3.0
    total_timeout_seconds: float = 15.0
    request_limit_bytes: int = 32_768
    response_limit_bytes: int = 65_536

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("base_url must be an HTTPS origin or path without credentials")
        if not self.model.strip() or len(self.model) > 200:
            raise ValueError("model must contain between 1 and 200 characters")
        if any(character.isspace() for character in self.model):
            raise ValueError("model cannot contain whitespace")
        if (
            not math.isfinite(self.connect_timeout_seconds)
            or not math.isfinite(self.total_timeout_seconds)
            or self.connect_timeout_seconds <= 0.0
            or self.total_timeout_seconds <= 0.0
            or self.connect_timeout_seconds > self.total_timeout_seconds
        ):
            raise ValueError("provider timeouts must be positive, finite, and ordered")
        if type(self.request_limit_bytes) is not int or self.request_limit_bytes <= 0:
            raise ValueError("request_limit_bytes must be a positive integer")
        if type(self.response_limit_bytes) is not int or self.response_limit_bytes <= 0:
            raise ValueError("response_limit_bytes must be a positive integer")


class OpenAICompatibleProvider:
    def __init__(
        self,
        config: ProviderConfig,
        secret_store: SecretStore,
        *,
        transport: HttpTransport | None = None,
    ) -> None:
        self._config = config
        self._secret_store = secret_store
        self._transport = transport or HttpxTransport()

    def explain(self, question: str, evidence: tuple[Evidence, ...]) -> ExplanationDraft:
        if not isinstance(question, str) or not question.strip() or len(question) > 500:
            raise ValueError("question must contain between 1 and 500 characters")
        selected = _select_evidence(evidence)
        if not selected:
            raise ProviderUnavailableError("No eligible evidence is available.")
        secret = self._secret_store.get()
        if (
            secret is None
            or not secret.strip()
            or len(secret) > MAX_SECRET_LENGTH
            or "\n" in secret
            or "\r" in secret
        ):
            raise ProviderUnavailableError("Provider secret is not configured.")
        request_body = _request_body(self._config.model, question.strip(), selected)
        if len(request_body) > self._config.request_limit_bytes:
            raise ProviderResponseError("Provider request exceeded its size limit.")
        response = self._request_with_retry(request_body, secret)
        return _parse_response(response.content, {item.id for item in selected})

    def _request_with_retry(self, content: bytes, secret: str) -> HttpResponse:
        started = time.monotonic()
        url = f"{self._config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        last_error: ProviderError | None = None
        for attempt in range(2):
            remaining = self._config.total_timeout_seconds - (time.monotonic() - started)
            if remaining <= 0.0:
                raise ProviderTransportError("Provider request timed out.") from None
            try:
                response = self._transport.post(
                    url=url,
                    headers=headers,
                    content=content,
                    connect_timeout_seconds=self._config.connect_timeout_seconds,
                    total_timeout_seconds=remaining,
                    response_limit_bytes=self._config.response_limit_bytes,
                )
            except ProviderTransportError as exc:
                last_error = exc
                if attempt == 0:
                    continue
                raise ProviderTransportError("Provider request failed.") from None
            if response.status_code == 200:
                return response
            if attempt == 0 and (response.status_code in {408, 429} or response.status_code >= 500):
                continue
            raise ProviderTransportError("Provider returned an unsuccessful status.") from None
        raise ProviderTransportError("Provider request failed.") from last_error

    def __repr__(self) -> str:
        return (
            f"OpenAICompatibleProvider(base_url={self._config.base_url!r}, "
            f"model={self._config.model!r})"
        )


def _select_evidence(evidence: tuple[Evidence, ...]) -> tuple[Evidence, ...]:
    if not evidence:
        return ()
    return select_for_segment(
        evidence,
        min(item.start_seconds for item in evidence),
        max(item.end_seconds for item in evidence),
    )


def _request_body(model: str, question: str, evidence: tuple[Evidence, ...]) -> bytes:
    evidence_payload = [
        {
            "id": str(item.id),
            "kind": item.kind,
            "start_seconds": item.start_seconds,
            "end_seconds": item.end_seconds,
            "value": item.public_value,
            "confidence": item.confidence,
            "algorithm": item.algorithm,
        }
        for item in evidence
    ]
    user_payload = json.dumps(
        {"question": question, "evidence": evidence_payload},
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You explain only the supplied structured music evidence. "
                    "Never add or modify chords, keys, sections, timestamps, energy changes, "
                    "instruments, genres, emotions, or causal facts. Return strict JSON with "
                    "exactly text and evidence_ids; every cited ID must appear in the evidence."
                ),
            },
            {"role": "user", "content": user_payload},
        ],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _parse_response(content: bytes, allowed_ids: set[uuid.UUID]) -> ExplanationDraft:
    try:
        envelope = json.loads(content)
        choices = envelope["choices"]
        message_content = choices[0]["message"]["content"]
        payload = json.loads(message_content)
    except (KeyError, IndexError, TypeError, ValueError, UnicodeDecodeError):
        raise ProviderResponseError(
            "Provider response did not match the required schema."
        ) from None
    if not isinstance(payload, dict) or set(payload) != {"text", "evidence_ids"}:
        raise ProviderResponseError("Provider response did not match the required schema.")
    text = payload["text"]
    raw_ids = payload["evidence_ids"]
    if not isinstance(text, str) or not text.strip() or len(text) > 4_000:
        raise ProviderResponseError("Provider response text is invalid.")
    if not isinstance(raw_ids, list) or not raw_ids or len(raw_ids) > len(allowed_ids):
        raise ProviderResponseError("Provider response citations are invalid.")
    try:
        evidence_ids = tuple(uuid.UUID(item) for item in raw_ids if isinstance(item, str))
    except ValueError:
        raise ProviderResponseError("Provider response citations are invalid.") from None
    if (
        len(evidence_ids) != len(raw_ids)
        or len(set(evidence_ids)) != len(evidence_ids)
        or any(evidence_id not in allowed_ids for evidence_id in evidence_ids)
    ):
        raise ProviderResponseError("Provider response citations are invalid.")
    return ExplanationDraft("llm", text.strip(), evidence_ids)
