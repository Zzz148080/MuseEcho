# Task 3 recovery report

## Status

Implemented the browser format contract, documentation, and final fail-closed release-boundary
refresh in `D:\智软工程师大项目\format-recovery` only.

Browser commit: `99c9169` (`feat: align browser audio format contract`).

The release-evidence refresh and this report are committed together after the final verification
record below. No result-page, timeline, or analysis-algorithm file changed in Task 3.

## Browser contract

- The file chooser uses exact suffix filters only:
  `.wav,.mp3,.flac,.m4a,.aac,.ogg,.opus`.
- Client preflight accepts exactly those seven suffixes, case-insensitively, while retaining the
  existing 30 MB and non-empty checks.
- `.mp4` and `.oga` are deliberately absent from the chooser and rejected by client preflight,
  including when the browser supplies `audio/mp4` or `audio/ogg` MIME values.
- The UI and README explain that M4A supports AAC/ALAC only and the Ogg family supports
  Vorbis/Opus only (`.ogg` for Vorbis and `.opus` for Opus).
- Browser MIME and extension checks are early guidance only; server signature, container,
  all-stream, and codec validation remain authoritative.
- DRM and proprietary encrypted downloads are deliberately unsupported.

## Strict TDD evidence

The production change that the first test catches is a broad or adjacent chooser filter that
shows inputs outside the exact public suffix contract. The second table catches removal of any
server-supported suffix from browser preflight.

1. RED 1:
   `npm --prefix frontend test -- src/features/upload/UploadForm.test.tsx --reporter=verbose`
   produced `1 failed, 8 passed`. The exact chooser assertion expected
   `.wav,.mp3,.flac,.m4a,.aac,.ogg,.opus` and observed the old
   `.wav,.mp3,audio/wav,audio/mpeg` value. A first incorrectly directed Vitest invocation lacked
   the frontend jsdom config and was explicitly discarded as an environment error, not counted
   as RED evidence.
2. Minimal GREEN 1 changed the chooser to suffixes only and updated the stale unsupported-format
   preflight presentation. The focused rejection/chooser behavior then passed.
3. RED 2 added literal, table-driven preflight expectations for all seven supported suffixes.
   The focused run produced `5 failed, 11 passed`: WAV and MP3 passed while FLAC, M4A, AAC, OGG,
   and OPUS failed against the old two-suffix set.
4. Minimal GREEN 2 extended the preflight set and updated user/server guidance. The focused file
   then produced `16 passed`.
5. Final frontend rerun: `12 passed` test files and `78 passed` tests; typecheck and production
   build both exited zero.

## Fail-closed release refresh

The first complete host Pytest run after the browser work produced `797 passed, 5 skipped,
35 failed in 301.03s`. Investigation classified the failures without hiding them:

- 26 real-media/pipeline/performance tests could not start because Windows had no
  `ffmpeg.exe`/`ffprobe.exe`.
- Nine acceptance, engineering, and image-audit failures were the expected frozen source/runtime
  boundary drift from Tasks 1 and 2.

The release refresh preserves the existing policy schema and equality checks:

- refreshed four reviewed evidence-file hashes (`decode.py`, `uploads.py`, upload tests, decode
  tests);
- refreshed the complete runtime boundary for changed `decode.py`, `waveform.py`,
  `coordinator.py`, and `uploads.py`, and added the new registry `audio_formats.py`;
- refreshed the canonical policy digest, runtime-boundary digest, security-manifest digest and
  fixed checker contract;
- refreshed the E004 current browser/source/test boundary while retaining its historical commit
  and truthful `boundary-state=DRIFT` conclusion.

No checker comparison, required field, reviewed CVE statement, retained raw finding, VEX
statement, or image identity was removed or relaxed.

Fail-closed verification:

- Current policy plus six schema/probe/missing-file/hash mutation cases, current-source checker
  recomputation, and acceptance boundary: `8 passed`.
- Complete acceptance matrix, engineering audit, and image vulnerability audit modules:
  `172 passed, 1 skipped in 35.11s`.

## Complete retained verification

- Frontend: `12` files / `78` tests passed; TypeScript typecheck passed; Vite production build
  passed (`95` modules transformed).
- Python static/locked gates: `uv lock --check`, Ruff format (`88 files`), Ruff lint, mypy
  (`47 source files`), and root E2E TypeScript check passed.
- Real media boundary: bounded host search found no Windows FFmpeg. A local, no-network
  verification image combined the retained Task 23 audited FFmpeg 5.1.9 runtime with the Task 2
  locked pytest environment. With the current repository mounted read-only, upload, decode,
  encrypted pipeline, and five-minute performance suites passed `102 passed in 84.28s`.
- Production smoke: `scripts/container-smoke.ps1` exited zero after building current app/gateway
  images, uploading and analyzing a real WAV, restarting the app, checking persisted access,
  checking no plaintext audio in the volume, and cleaning its containers/network/volume/task
  temp.
- Dependency/security gates: license audit passed; root and frontend npm audits found zero
  vulnerabilities; real Secret scan and synthetic fail-closed scan passed.
- Platform contract gates: container-pytest cleanup, development-smoke lifecycle, container
  no-build contract, and fresh-checkout shell parse/EOL tests passed.
- Playwright browser E2E did not execute because the hard-coded `127.0.0.1:4173` port was already
  owned by the pre-existing user development container `museecho-gateway-dev-1`. Task 3 did not
  stop or mutate that user environment. Its prerequisite frontend production build passed before
  the server bind failed with WinError 10048.
- Host versions: uv was updated to the required 0.11.29. The available host Node is 24.16.0,
  outside the declared Node 22 range; final frontend tests/type/build still passed, while the
  production Docker build used the pinned Node 22.23.0 image.

## Supported and deliberately unsupported inputs

Supported public suffix/content pairings:

- `.wav`: bounded PCM/IEEE-float WAV variants in the server registry;
- `.mp3`: regular MPEG Layer III (with the existing attached-MJPEG artwork exception);
- `.flac`: FLAC;
- `.m4a`: AAC or ALAC in the allowed ISO-BMFF audio container;
- `.aac`: AAC/ADTS;
- `.ogg`: Ogg/Vorbis;
- `.opus`: Ogg/Opus.

Deliberately unsupported: `.mp4`, `.oga`, video/container variants, wrong suffix/container/codec
pairings, extra disallowed streams, free-format MP3, malformed or ambiguous signatures, DRM, and
proprietary encrypted downloads.
