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

## Review fix round 2 (2026-08-14)

The scoped re-review found that the round-1 exact container-control tuple was syntactically
fail-closed but semantically wrong: `compose.yaml:17` names the optional provider-secret
environment variable and does not enforce container hardening. Because both policy and checker
shared that tuple, all 24 container-bound VEX statements passed the exact-contract test while
citing a false control.

### Strict TDD RED/GREEN

Before changing the checker or policy, a focused mutation test supplied the hand-inspected
hardening tuple `compose.yaml:18`, `compose.yaml:22`, and `compose.yaml:24`, then changed only the
read-only anchor from line 18 to the provider-secret line 17 and required that mutation to fail
the fixed contract. RED failed at the first assertion because
the checker rejected the correct tuple and still required the provider-secret anchor.

Minimal GREEN changed the fixed contract and all 24 affected policy statements to:

- `compose.yaml:18`: `read_only: true`;
- `compose.yaml:22`: `no-new-privileges:true`;
- `compose.yaml:24`: `ALL` under `cap_drop`.

The focused test then passed and proved that substituting only the provider-secret anchor produces
`audio boundary controls do not match the fixed contract`.

### Regenerated evidence and verification

- Normalized policy SHA256:
  `3be55b3898d232bf3018cd59a6cb17253d5cd6e6fd6dccebad15bc260dc3f2b9`.
- Regenerated OpenVEX SHA256:
  `ed4df519b5bc2df00bec0326a13a8f34b5ded840e5d31f01e0f4fe09fab3e2bc`.
- Normalized security-manifest SHA256:
  `91f675aff5af8d45a805eab730e0f9f2227e0c2be3be7fbd5d82213f871fda44`.
- Each digest matched the manifest and fail-closed engineering checker constant.
- Focused image-security, engineering-audit, and acceptance-audit suite:
  `176 passed, 1 skipped in 41.40s`.
- Functional checker: `40 acceptance items validated: PASS=34 PARTIAL=6 FAIL=0`.
- Engineering checker tracked schema/fixed-contract validation (`--schema-only`) retained the
  same 10 finding dispositions.
- Focused Ruff formatting and lint passed.

No runtime Compose setting, product source, CVE disposition, raw finding, or image identity was
changed. This round corrects only the VEX control references, their generated hashes, the
fail-closed checker contract, its regression test, and this retained report.

## Final whole-branch review fix wave (2026-08-14)

The final reviewer identified two remaining correctness issues:

- Functional E008/E009/E010 and Engineering E012/E013/E022 mixed current-source claims with
  pre-feature Task 23 image/static evidence. In particular, the old production smoke and image
  scan could still be read as support for the changed decoder/upload/frontend branch.
- `AudioFormat.validator_kind` documented signature behavior but upload validation still chose
  validators through a hard-coded suffix chain, so the registry was not the owner of that
  behavior.

The approved design uses a `ValidatorKind` `StrEnum` and a total kind-to-handler map. The registry
stores only enum values, not callables, and import-time equality plus a public test seam requires
the handler keys to equal the kinds used by every registered format.

### Strict TDD RED

Five focused tests were written before implementation and failed as intended:

- every registered format required an available signature-validator kind, but the API did not
  exist;
- Functional E008/E009/E010 still required the old image/count/kind contract;
- a mutation changing E009 back to `CURRENT_COMMAND` was accepted;
- Engineering E012/E013/E022 still required the old count/image/kind contract;
- a mutation changing E022 back to `CURRENT_COMMAND` was accepted.

The initial RED result was five failures. After the registry refactor, its focused GREEN covered
all seven formats and every signature family. A first complete Linux run then exposed call-site
regressions that narrower host tests could not execute: nine ambiguous MP3-signature cases passed
an unrelated `.bin` suffix to the new API, the integration suite still used the former one-argument
private API, and one concurrency test still used the former validator signature. That run also
exposed one frozen `34/6` process-document contract and four PowerShell-only harnesses in the
minimal Linux verification image. It failed truthfully as `31 failed, 812 passed, 3 skipped`.

The call sites now pass the registry entry explicitly. The PowerShell harness tests skip only on a
host without PowerShell and pass separately on the Windows/PowerShell host; no PowerShell runtime
was added to the production-like Linux image. Current-status blocks in PLAN/log/blocker/reflection
documents and the frozen delivery contract now agree with the audited `31 PASS / 9 PARTIAL /
0 FAIL` result.

### Registry-owned validation

`src/museecho/audio_formats.py` now defines `ValidatorKind` and assigns one kind to every exact
suffix registry entry. `src/museecho/application/uploads.py` owns an immutable exhaustive handler
map and dispatches only through `audio_format.validator_kind`. Both Ogg variants intentionally map
to the shared Ogg parser while retaining distinct registry kinds, and every other kind maps to its
own WAV, MP3, FLAC, ISO-BMFF, or ADTS parser. The upload service passes the already-resolved registry
entry to validation and then uses the same entry for demuxer/codec pairing.

### Audit truth and fail-closed mutations

- Functional E008 and Engineering E013 now bind fresh current-source execution in the retained
  FFmpeg-capable Linux verification image plus the separate PowerShell-host delivery-contract run.
- Functional E009 is `IMPLEMENTATION_BOUNDARY_COMMAND`, is explicitly non-supporting for PASS,
  and is covered by a mutation that rejects restoring `CURRENT_COMMAND`.
- Engineering E022 is likewise an implementation-boundary record for the pre-feature Task 23
  image and has a mutation that rejects restoring current-image language.
- Functional E010 and Engineering E012 bind the fresh 96-file Ruff and 47-file host/Linux mypy
  counts.
- Only the exact rows that depended on current distribution/production execution were downgraded:
  AC-F-1, DOD-07, and DOD-08 are `PARTIAL` behind
  `CURRENT-BRANCH-DISTRIBUTION`. Other PASS rows rely only on fresh current-source tests or a
  precisely scoped parsed contract.
- The generated audit status and all tracked current-status blocks now state
  `31 PASS / 9 PARTIAL / 0 FAIL`.

### Boundary refresh

The two security-policy test evidence hashes were refreshed after adapting the validator call
sites. The reviewed CVE statements and source controls did not change, so regenerating the
canonical OpenVEX structure produced the same VEX digest. The runtime source boundary also stayed
unchanged after final formatting.

- normalized policy SHA256:
  `bbfc2bd24a2c653fc1ba205233e15e705cffa82cf70d7e43b16d4ead39d92e28`;
- OpenVEX SHA256:
  `5a99f65ff2876867117e257903df87a63c0821c614ea82a88d61ccbef833f372`;
- runtime-boundary SHA256:
  `a26f11a94d171b6edbbb8bff124b6ac2f9d2bf7069f0d57a29017fb0112c070f`;
- normalized security-manifest SHA256:
  `3729d1c1f1cc6af7554bffdbd399f45fc8a0b5885045638eb0c17dbd45feb63f`;
- current browser/source/test boundary SHA256:
  `379190a08d81c07d086d0b6e3fd220c8aaf31fd4299d5569ece910d50992ad0c`.

### Final verification

- Final read-only current-source Linux container suite:
  `839 passed, 7 skipped in 589.82s`; container and task-temp cleanup succeeded. Four skips are
  the PowerShell-only harnesses; the other three are retained environment/tool skips.
- Current PowerShell-host delivery-contract suite: `20 passed in 169.70s`, including all four
  Linux-skipped PowerShell harnesses.
- Focused registry/ambiguous-signature/concurrency suite: `11 passed`.
- Focused acceptance, engineering, and image-policy suite:
  `180 passed, 1 skipped in 45.56s`.
- Frontend: 12 files and 78 tests passed; typecheck passed; the production build transformed
  95 modules.
- Static/type gates: 96 files formatted; Ruff lint passed; strict mypy passed 47 source files on
  the host and explicit Linux target; the acceptance checker passed as one typed source file.
- Functional checker: `40 acceptance items validated: PASS=31 PARTIAL=9 FAIL=0`.
- Engineering checker `--schema-only`: all 10 declared finding dispositions and fixed contracts
  validated. This mode does not claim that absent external retained raw scan materials were
  recomputed in this fix wave; the committed manifest/policy/current-boundary contracts and their
  focused mutation tests were validated.
- `git diff --check` passed; its only output was existing Windows LF-to-CRLF checkout warnings.

No result page, shared timeline, analysis algorithm, accepted suffix, CVE disposition, raw image
finding, production image identity, or Compose runtime setting changed in this wave.
