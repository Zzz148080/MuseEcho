from __future__ import annotations

import re
import uuid
from collections.abc import Iterator

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from fastapi.responses import StreamingResponse

from museecho.api.dependencies import require_analysis_access
from museecho.application.lifecycle import AnalysisLifecycleService
from museecho.domain.models import EncryptedAudioMetadata
from museecho.domain.ports import AccessService
from museecho.infrastructure.audio_store import DestroyedAudioKeyError

_SINGLE_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
AUDIO_STREAM_CHUNK_BYTES = 1024 * 1024


class InvalidByteRange(ValueError):
    pass


def create_audio_router(
    service: AnalysisLifecycleService,
    access_service: AccessService,
) -> APIRouter:
    router = APIRouter(prefix="/api/analyses", tags=["analysis-audio"])
    authorize = require_analysis_access(access_service)

    @router.get("/{analysis_id}/audio")
    def get_audio(
        analysis_id: uuid.UUID,
        _authorized: uuid.UUID = Depends(authorize),
        range_header: str | None = Header(default=None, alias="Range"),
    ) -> Response:
        try:
            metadata = service.audio_metadata(analysis_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Not Found") from None
        total = metadata.plaintext_size
        try:
            start, end = _parse_range(range_header, total)
        except InvalidByteRange:
            return Response(
                status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
                headers={
                    "Accept-Ranges": "bytes",
                    "Content-Range": f"bytes */{total}",
                },
            )
        first_end = min(end + 1, start + AUDIO_STREAM_CHUNK_BYTES)
        try:
            first_chunk = service.read_audio(metadata, start, first_end)
        except (DestroyedAudioKeyError, KeyError):
            raise HTTPException(status_code=404, detail="Not Found") from None
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(end - start + 1),
        }
        status_code = status.HTTP_200_OK
        if range_header is not None:
            status_code = status.HTTP_206_PARTIAL_CONTENT
            headers["Content-Range"] = f"bytes {start}-{end}/{total}"
        return StreamingResponse(
            _stream_audio(service, metadata, first_chunk, first_end, end + 1),
            status_code=status_code,
            media_type=metadata.media_type,
            headers=headers,
        )

    return router


def _stream_audio(
    service: AnalysisLifecycleService,
    metadata: EncryptedAudioMetadata,
    first_chunk: bytes,
    current: int,
    end: int,
) -> Iterator[bytes]:
    yield first_chunk
    while current < end:
        next_end = min(end, current + AUDIO_STREAM_CHUNK_BYTES)
        yield service.read_audio(metadata, current, next_end)
        current = next_end


def _parse_range(value: str | None, total: int) -> tuple[int, int]:
    if total <= 0:
        raise InvalidByteRange
    if value is None:
        return 0, total - 1
    match = _SINGLE_RANGE.fullmatch(value.strip())
    if match is None:
        raise InvalidByteRange
    start_text, end_text = match.groups()
    if not start_text and not end_text:
        raise InvalidByteRange
    if len(start_text) > 20 or len(end_text) > 20:
        raise InvalidByteRange
    if not start_text:
        length = int(end_text)
        if length <= 0:
            raise InvalidByteRange
        return max(0, total - length), total - 1
    start = int(start_text)
    if start >= total:
        raise InvalidByteRange
    end = total - 1 if not end_text else min(int(end_text), total - 1)
    if end < start:
        raise InvalidByteRange
    return start, end


__all__ = ["InvalidByteRange", "create_audio_router"]
