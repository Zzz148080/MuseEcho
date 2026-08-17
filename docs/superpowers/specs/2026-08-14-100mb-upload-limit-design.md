# 100 MB Audio Upload Limit Design

## Goal

Raise MuseEcho's accepted audio-file size from 30 MiB to 100 MiB while retaining the existing 10-minute duration limit, bounded streaming behavior, encrypted retention, and format-validation controls.

## Boundary contract

- The application file limit is exactly `100 * 1024 * 1024` bytes.
- The multipart request-body limit remains the file limit plus the existing 64 KiB request-overhead allowance.
- A file of exactly 100 MiB is accepted for validation; the first byte above 100 MiB is rejected.
- Requests with an oversized `Content-Length` are rejected before multipart parsing.
- Requests without a usable `Content-Length` remain bounded while streaming and cannot bypass the request-body limit.
- The maximum decoded duration remains 600 seconds. Codec, demuxer, protocol, decode-timeout, and PCM-memory controls remain unchanged.

## Architecture and data flow

The server continues to own the authoritative limit through `DEFAULT_MAX_UPLOAD_BYTES`. `UploadBodyLimitMiddleware` derives its multipart ceiling from that value, and `UploadSubmissionService` copies the uploaded stream to its isolated plaintext staging file in bounded chunks before validation and encrypted persistence. FastAPI/Starlette may spool multipart input to disk, so the application does not require a 100 MiB in-memory request buffer.

The browser uses the same numeric limit for immediate preflight and presents 100 MB in all upload and server-error messages. The browser check remains advisory: the server enforces both the complete request-body ceiling and the extracted file ceiling independently.

No Caddy request-body configuration is required because the current gateway has no smaller body cap. The existing data volume remains the storage boundary for multipart spooling, isolated plaintext staging, and encrypted audio.

## Error handling

Oversized requests continue to return HTTP 413 with `upload_too_large`. Oversized extracted files continue to be deleted with their isolated temporary directory, create no analysis job, write no encrypted audio, and enqueue no work. Client copy and retry guidance changes only from 30 MB to 100 MB.

## Verification

Tests must prove observable behavior at each boundary:

1. the browser accepts a file at exactly 100 MiB and rejects 100 MiB plus one byte before transport;
2. the upload service accepts a configured ceiling of 100 MiB and still rejects any configured ceiling above the supported maximum;
3. the API middleware accepts the derived 100 MiB-plus-overhead ceiling, rejects larger `Content-Length` requests, and bounds chunked requests without `Content-Length`;
4. existing cleanup, zero-byte, unsupported-format, 10-minute duration, and encrypted-storage tests remain green;
5. user-facing specifications describe 100 MB consistently, and the acceptance/audit contracts remain internally valid.

## Operational impact

A concurrent upload can temporarily occupy space in multipart spooling, isolated plaintext staging, and encrypted storage. Deployment capacity planning should therefore allow roughly 200–300 MiB of transient disk per active maximum-size upload. The target 70 GB data disk and 10-minute duration ceiling remain compatible with this limit; no new dependency or infrastructure component is introduced.
