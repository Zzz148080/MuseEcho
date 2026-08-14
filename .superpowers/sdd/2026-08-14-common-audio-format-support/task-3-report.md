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

## Review fix round 1 (2026-08-14)

The final review correctly identified two retained-evidence defects that were not caught by the
first release refresh:

- 66 media-bound VEX statements still described the old WAV/MP3 or PCM/MP3 reachability model
  and cited line numbers from the old upload/decode implementation;
- Functional Audit E001 and its fail-closed acceptance contract still claimed the superseded
  66-test frontend suite, despite the retained Task 3 run containing 78 tests.

This round deliberately supersedes the earlier report sentence saying no VEX statement changed.
The raw Trivy findings, package inventory, reviewed CVE inventory, image identities, and product
statuses remain unchanged, but the 66 affected VEX impact statements and their control anchors
were re-reviewed and updated because their security rationale had become semantically stale.

### Strict TDD RED

Two focused mutation contracts were added before checker or evidence changes:

- substituting the old six upload/decode line anchors into a committed media CVE must produce
  `audio boundary controls do not match the fixed contract`;
- restoring a WAV/MP3-only or PCM/MP3-only impact statement must produce
  `contains stale WAV/MP3-only rationale`;
- Functional Audit E001 must accept `vitest-files=12; vitest-tests=78` and reject a coherent
  mutation back to 66 as a fixed evidence-contract mismatch.

The RED run failed all three parameterized cases: stale anchors were accepted, stale rationale
was accepted, and the truthful 78-test record was rejected by the old 66-test contract.

### Minimal GREEN and retained-evidence consistency

The image policy checker now binds the exact current media control contract for the 42
audio-bound CVEs and the corresponding media-plus-container contract for 24 additional CVEs.
The fixed anchors cover the registry, registry-derived demuxer/codec/protocol allowlists,
per-format signature dispatch, suffix/container/codec pairing, FFprobe/FFmpeg protocol and codec
allowlists, validation of every stream, and the MP3-only attached-MJPEG exception. Each pinned
line was manually inspected after formatting. The checker also requires the current
registry-derived rationale marker and explicitly rejects the two stale fixed phrases.

All affected policy statements now rely on the current registry-derived boundary instead of the
old two-format gate. FFmpeg-family statements enumerate PCM WAV, MP3, FLAC, AAC, ALAC, Vorbis,
and Opus; they additionally state that MJPEG is admitted only as MP3 `attached_pic` metadata,
never selected for decoding, and that all streams are validated before the selected audio stream
is decoded to raw mono PCM. Other media/library statements identify their own unreachable
primitive and bind that assessment to the same precise registry-derived controls.

The canonical policy, OpenVEX digest, security manifest, and fail-closed engineering checker
contract were refreshed after the semantic correction. The app runtime-boundary digest and
reviewed image identities did not change. Functional Audit E001 and the companion Engineering
Audit frontend record now truthfully retain the fresh 12-file/78-test result. Adding the new
acceptance mutation test increased the focused acceptance module from 44 to 45 tests, so E014,
E030, and their fixed contracts were updated consistently rather than leaving a second stale
count.

### Final round-1 verification

- Focused mutation/audit suite:
  `tests/unit/test_image_vulnerability_audit.py`,
  `tests/unit/test_acceptance_matrix.py`, and
  `tests/unit/test_engineering_audit.py` passed `175 passed, 1 skipped in 38.26s`.
- Functional checker: `40 acceptance items validated: PASS=34 PARTIAL=6 FAIL=0`.
- Engineering checker tracked schema/fixed-contract validation (`--schema-only`): 10 findings
  validated with
  `FIXED/High=4`, `FIXED/Medium=2`, `VERIFIED/Medium=1`, and the three declared external/build
  `BLOCKED/Medium` findings unchanged.
- Current frontend evidence rerun: `12 passed` files and `78 passed` tests, including the exact
  suffix chooser plus `.mp4`/`.oga` rejection tests.
- Focused Ruff formatting and lint passed for all changed Python checker/test files.
- `git diff --check` passed; the only output was Git's existing Windows LF-to-CRLF checkout
  warning, not a whitespace error.

No product runtime, result-page, timeline, analysis algorithm, CVE disposition, retained raw
finding, or container/image identity changed in this review fix.
