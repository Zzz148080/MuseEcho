# MuseEcho V1 Functional Audit

- **Generated at UTC:** `2026-08-11T12:15:00Z`
- **Readiness:** `PARTIALLY_READY`
- **Scope:** `SPEC.md` AC-A through AC-F plus Definition of Done
- **Method:** Current commands are preferred. Exact historical commits are used only where the tested implementation has not changed; external, future-task, and student-only work stays explicitly not run.

`PARTIALLY_READY` is mandatory: current real-browser E2E, target-server/public
deployment evidence, remote CI, Product Audit, and the student's
own final acceptance do not exist yet.
No local functional item is currently classified `FAIL`.

## Evidence index

| Evidence ID | Kind | Command | Path | Coverage | Result | Boundary SHA256 | Observed at UTC | Exit code | Commit | Summary |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E001 | CURRENT_COMMAND | npm.cmd --prefix frontend test -- --run | frontend/src | AC-A-3, AC-B-1, AC-B-2, AC-B-3, AC-C-1, AC-C-2, AC-D-4, AC-F-1, AC-F-4, DOD-01, DOD-03, DOD-05, DOD-06, DOD-07 | vitest-files=12; vitest-tests=66 | - | 2026-08-11T08:59:27Z | 0 | - | Current Vitest run: 12 files and 66 tests passed, including upload, DNA, timeline, chord, explanation, privacy, and source-kind behavior. |
| E002 | CURRENT_COMMAND | npm.cmd --prefix frontend run typecheck; npm.cmd --prefix frontend run build; npm.cmd run typecheck | frontend | AC-F-1, AC-F-4, DOD-07 | frontend-typecheck=0; frontend-build=0; e2e-typecheck=0 | - | 2026-08-11T08:59:43Z | 0 | - | Frontend typecheck/build and the independent E2E TypeScript gate passed. |
| E003 | CURRENT_COMMAND | powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/secret-scan.ps1 | scripts/secret-scan.ps1 | AC-E-4, DOD-09, DOD-14 | secret-scan-files=202 | - | 2026-08-11T10:17:29Z | 0 | - | Fresh fail-closed Secret scan passed for 202 tracked/non-ignored files. |
| E004 | HISTORICAL_COMMIT | git show 1047ce242884b6ba83a525524e88dcc44ab76a69:AGENT_LOG.md 1047ce242884b6ba83a525524e88dcc44ab76a69:PLAN.md | AGENT_LOG.md | AC-A-4, AC-C-3, AC-F-1, DOD-01, DOD-03, DOD-07 | browser-tests=4; benchmark-seconds=11.201268; boundary-state=DRIFT | f309344288c6c9b4ed4030e44eb29d3f16f3f92eedb2699c091d7b972e350cda | 2026-08-11T11:51:30Z | 0 | 1047ce242884b6ba83a525524e88dcc44ab76a69 | Exact Task 19 anchor exposes 4 browser tests and the benchmark, but the 108-file current browser/source/test manifest differs from its 105-file historical manifest; this record cannot support a current PASS. |
| E005 | CURRENT_COMMAND | .venv\Scripts\python.exe -m pytest tests/unit/test_task20_final_delivery_contract.py -q --basetemp=tmp/task22-delivery-contract | tests/unit/test_task20_final_delivery_contract.py | AC-F-2, AC-F-3, DOD-11, DOD-12 | pytest-tests=7; github=parsed; gitlab=parsed; gitlab-unit-test=present; readme=verified | - | 2026-08-11T10:17:47Z | 0 | - | Current contract parses both CI definitions, proves GitLab unit-test, checks the README cold-start/HTTPS/health/cleanup path, and anchors truthful process documents. |
| E006 | CURRENT_COMMAND | ..\feat-20-production-delivery\.venv\Scripts\python.exe -m pytest tests/unit/test_acceptance_matrix.py -q | tests/unit/test_acceptance_matrix.py | DOD-15 | red=ModuleNotFoundError:scripts.check_acceptance_matrix | - | 2026-08-11T08:56:00Z | 1 | - | Required TDD RED: collection failed because scripts.check_acceptance_matrix did not yet exist. Passing revalidation is recorded separately in E008 and E014. |
| E008 | CURRENT_COMMAND | powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/container-pytest.ps1 -Image museecho-app:task20-final | tests | AC-A-1, AC-A-2, AC-A-3, AC-A-4, AC-D-1, AC-D-2, AC-D-3, AC-D-4, AC-E-1, AC-E-2, AC-E-3, AC-F-1, DOD-01, DOD-02, DOD-04, DOD-05, DOD-06, DOD-07, DOD-14, DOD-15 | pytest-tests=649 | - | 2026-08-11T10:16:51Z | 0 | - | Current locked Linux production runtime passed 649 backend, integration, security, performance, delivery-contract, and Task 22 tests in 244.21 seconds; container and task-temp cleanup were empty. |
| E009 | CURRENT_COMMAND | powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/container-smoke.ps1 | scripts/container-smoke.ps1 | AC-E-1, AC-E-3, AC-F-1, AC-F-3, DOD-07, DOD-08 | smoke=real-wav+restart+ciphertext+image-history+cleanup | - | 2026-08-11T09:17:12Z | 0 | - | Current production smoke passed real WAV upload/analysis, restart persistence, no plaintext in the volume, image-history Secret check, and exact cleanup. Its mandatory build unexpectedly fetched 167 lockfile-pinned npm packages; manifests stayed unchanged and the process concern is not hidden. |
| E010 | CURRENT_COMMAND | .venv\Scripts\python.exe -m ruff format --check src tests scripts; .venv\Scripts\python.exe -m ruff check .; .venv\Scripts\python.exe -m mypy src; .venv\Scripts\python.exe -m mypy scripts/check_acceptance_matrix.py | scripts/check_acceptance_matrix.py | AC-F-1, DOD-07 | ruff-files=89; mypy-src-files=45; mypy-checker-files=1 | - | 2026-08-11T10:17:29Z | 0 | - | Current quality gates cover formatting, lint, application typing, and checker typing. |
| E011 | CURRENT_COMMAND | .venv\Scripts\python.exe scripts/license_audit.py | scripts/license_audit.py | DOD-14 | license-audit=pass | - | 2026-08-11T09:22:50Z | 0 | - | Current license inventory matched the reviewed Python, npm, container, build-tool, Go, and OS-package policy. |
| E012 | CURRENT_COMMAND | powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-secret-scan.ps1 | scripts/test-secret-scan.ps1 | AC-E-4, DOD-09, DOD-14 | secret-mutations=pass | - | 2026-08-11T10:17:29Z | 0 | - | All synthetic credential, unreadable-file, and missing-file mutations passed. |
| E013 | CURRENT_COMMAND | powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-secret-scan.ps1 | scripts/test-secret-scan.ps1 | AC-E-4, DOD-09 | red=wrapped-unreadable-filename | - | 2026-08-11T09:22:50Z | 1 | - | RED: scanner correctly failed closed, but PowerShell wrapped tracked-unreadable.txt across whitespace and the harness misclassified its output; production scan policy was not weakened. |
| E014 | CURRENT_COMMAND | uv run pytest tests/unit/test_acceptance_matrix.py -q && uv run python scripts/check_acceptance_matrix.py SPEC.md docs/audits/FUNCTIONAL_AUDIT.md | tests/unit/test_acceptance_matrix.py | AC-F-1, DOD-15 | pytest-tests=35; pass=29; partial=11; fail=0 | - | 2026-08-11T10:23:11Z | 0 | - | Exact brief gate uses cached uv 0.11.29, network none, pull never, no sync, and a read-only worktree; final pristine output is recorded in the review report. |
| E900 | EXTERNAL_NOT_RUN | NOT RUN: Tencent Cloud target-server benchmark and public smoke require account, Lighthouse, DNS, SSH, and OCI authorization | DEPLOYMENT_EVIDENCE.md | AC-A-4, AC-F-5 | NOT_RUN | - | 2026-08-11T09:02:23Z | NOT_RUN | - | No target-server five-minute result, public URL, trusted public TLS smoke, cross-network check, 24-hour observation, or live rollback exists. |
| E901 | EXTERNAL_NOT_RUN | NOT RUN: GitHub Actions and GitLab CI have no pipeline result for the merged Task 20 and Task 21 state | TASK20_HANDOFF.md | DOD-10 | NOT_RUN | - | 2026-08-11T09:02:23Z | NOT_RUN | - | CI files and local contracts exist, but configuration presence is not a remote pass. |
| E902 | CURRENT_COMMAND | .venv\Scripts\python.exe scripts/check_engineering_audit.py docs/audits/ENGINEERING_AUDIT.md | docs/audits/ENGINEERING_AUDIT.md | AC-F-6, DOD-13 | findings=9; fixed-high=4; fixed-medium=2; blocked-medium=3; open=0 | - | 2026-08-11T12:14:30Z | 0 | - | Task 23 Engineering Audit passed its fail-closed checker with no OPEN Critical/High; three Medium external/environment evidence gaps remain blocked. |
| E903 | EXTERNAL_NOT_RUN | NOT RUN: Task 24 Product Audit starts only after Task 23 | PLAN.md | AC-F-6, DOD-13 | NOT_RUN | - | 2026-08-11T09:02:23Z | NOT_RUN | - | Product Audit and final delivery verification have not run. |
| E904 | EXTERNAL_NOT_RUN | NOT RUN: the student must personally perform the final acceptance checklist and write REFLECTION.md | SPEC.md | DOD-16 | NOT_RUN | - | 2026-08-11T09:02:23Z | NOT_RUN | - | Student participation is deliberately reserved; this audit neither performs nor claims it. |
| E905 | EXTERNAL_NOT_RUN | NOT RUN: current Chrome E2E requires the missing locked root Playwright dependency cache; no npm download or outbound-capable browser container is authorized | e2e | AC-C-3, AC-F-1, DOD-01, DOD-03, DOD-07 | NOT_RUN | - | 2026-08-11T12:01:00Z | NOT_RUN | - | Host Chrome exists and the production no-build HTTPS service was reachable, but the four-test Playwright harness could not start without restoring locked dependencies. |

## Acceptance matrix

| Item ID | Verdict | Importance | Evidence IDs | Owner | Disposition | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| AC-A-1 | PASS | IMPORTANT | E008 | Task 22 | - | Current locked Linux API/integration suite covers legal WAV/MP3 upload, real queued analysis, completion, and persisted real results. |
| AC-A-2 | PASS | IMPORTANT | E008 | Task 22 | - | Current backend/API/security evidence covers oversize and corrupt rejection plus silence and short-input conservative paths. |
| AC-A-3 | PASS | IMPORTANT | E001, E008 | Task 22 | - | Current client and backend tests bind results to the current analysis and preserve real source_kind without fixed demo facts. |
| AC-A-4 | PARTIAL | IMPORTANT | E004, E008, E900 | Task 21 / operator | BLOCKER:TC-021 | The two-core local 300-second run was 11.201268 seconds and its gate passes currently, but SPEC requires a target-server measurement; no target server was authorized. |
| AC-B-1 | PASS | IMPORTANT | E001 | Tasks 14, 17 | - | Current DNA/workspace tests render only strictly parsed current TrackAnalysis data. |
| AC-B-2 | PASS | IMPORTANT | E001 | Tasks 8-10, 17 | - | Current tests verify unknown/cautious display for absent, invalid, or low-confidence facts. |
| AC-B-3 | PASS | IMPORTANT | E001 | Tasks 14, 17 | - | real, demo, and synthetic_test source kinds are parsed and visibly labeled. |
| AC-C-1 | PASS | IMPORTANT | E001 | Task 17 | - | Current player/timeline tests exercise one duration/currentTime/selection coordinate for waveform, sections, chords, energy, and playhead. |
| AC-C-2 | PASS | IMPORTANT | E001 | Tasks 17-19 | - | Current interaction tests cover chord seek, pointer/keyboard selection, citation seek, and shared playhead updates. |
| AC-C-3 | PARTIAL | IMPORTANT | E004, E905 | Task 24 | BLOCKER:CURRENT-BROWSER-E2E | The exact historical responsive browser run has a drifted current source/test boundary; current HTTPS is host-reachable, but the locked Playwright dependency cache is unavailable without a prohibited download. |
| AC-D-1 | PASS | IMPORTANT | E008 | Task 22 | - | Current deterministic theory and no-provider tests operate without an LLM. |
| AC-D-2 | PASS | IMPORTANT | E008 | Task 22 | - | Current Evidence policy/provider tests revalidate allowed kinds, confidence, values, and time windows before provider input. |
| AC-D-3 | PASS | IMPORTANT | E008 | Task 22 | - | Current tests cover missing key, timeout, transport/status, oversized, malformed JSON, and invalid citation fallback paths. |
| AC-D-4 | PASS | IMPORTANT | E001, E008 | Task 22 | - | Current service and UI tests expose mode plus the actual cited Evidence IDs. |
| AC-E-1 | PASS | IMPORTANT | E008, E009 | Task 22 | - | Current encryption tests and production smoke verify persisted content is authenticated ciphertext, not plaintext audio. |
| AC-E-2 | PASS | IMPORTANT | E008 | Task 22 | - | Current API/security suite compares unauthorized and nonexistent resources and verifies indistinguishable 404 behavior. |
| AC-E-3 | PASS | IMPORTANT | E008, E009 | Task 22 | - | Current delete/expiry tests and smoke cover grant revocation, wrapped-key destruction, result cascade, ciphertext cleanup, persistence, and post-delete invisibility. |
| AC-E-4 | PASS | IMPORTANT | E003, E012 | Task 22 | FIXED:E012 | Fresh Secret scan found no real credential; synthetic fail-closed mutations pass after correcting only PowerShell output normalization in the harness. |
| AC-F-1 | PARTIAL | IMPORTANT | E001, E002, E004, E008, E009, E010, E014, E905 | Task 22 / Task 24 | BLOCKER:CURRENT-BROWSER-E2E | Current frontend, locked Linux, Docker, lint, type, and audit gates pass, but the browser E2E record is historical with a drifted boundary and was not rerun under the no-network constraint. |
| AC-F-2 | PASS | IMPORTANT | E005 | Task 20 | - | Exact delivery contracts parse both CI definitions and require GitLab job unit-test; this is configuration evidence only, not remote execution. |
| AC-F-3 | PASS | STANDARD | E005, E009 | Task 20 | - | Current README/Compose contracts and production smoke cover locked setup, secrets, HTTPS startup, health, persistence, and cleanup. |
| AC-F-4 | PASS | STANDARD | E001, E002 | Tasks 15-18 | - | Current UI tests/type/build exercise approved semantic tokens, Warm Editorial components, responsive layout, and accessibility behavior. |
| AC-F-5 | PARTIAL | IMPORTANT | E900 | Task 21 / operator | BLOCKER:TC-021 | No public URL or trusted-certificate full product smoke exists. |
| AC-F-6 | PARTIAL | IMPORTANT | E902, E903 | Task 24 | BLOCKER:TASK24-AUDIT | Engineering Audit passed; Product Audit and final delivery verification remain future work. |
| DOD-01 | PARTIAL | IMPORTANT | E001, E004, E008, E905 | Task 22 / Task 24 | BLOCKER:CURRENT-BROWSER-E2E | A-D modules pass current backend/UI regression, but the end-to-end browser record does not have an unchanged current boundary. |
| DOD-02 | PASS | IMPORTANT | E008 | Task 22 | - | Real synthetic-fixture WAV/MP3 upload and analysis pass in the current production runtime. |
| DOD-03 | PARTIAL | IMPORTANT | E001, E004, E905 | Task 22 / Task 24 | BLOCKER:CURRENT-BROWSER-E2E | Current component tests cover the shared timeline, while real-browser interaction remains historical across a drifted source/test boundary. |
| DOD-04 | PASS | IMPORTANT | E008 | Task 22 | - | Deterministic theory has current reproducible parameterized backend coverage. |
| DOD-05 | PASS | IMPORTANT | E001, E008 | Task 22 | - | Evidence-grounded explanation, citations, and selection have current coverage. |
| DOD-06 | PASS | IMPORTANT | E001, E008 | Task 22 | - | No-key deterministic fallback has current service/UI coverage and exact E2E evidence. |
| DOD-07 | PARTIAL | IMPORTANT | E001, E002, E004, E008, E009, E010, E905 | Task 22 / Task 24 | BLOCKER:CURRENT-BROWSER-E2E | Latest applicable local tests, lint/type/build, locked Linux, and Docker evidence succeed; current real-browser E2E remains unrun. |
| DOD-08 | PASS | IMPORTANT | E009 | Task 22 | - | Current production container smoke covered health, upload/analysis, restart persistence, encryption boundary, and cleanup. |
| DOD-09 | PASS | IMPORTANT | E003, E012 | Task 22 | FIXED:E012 | Current real and synthetic Secret audit gates pass; the fix normalized wrapped diagnostic whitespace without weakening detection. |
| DOD-10 | PARTIAL | IMPORTANT | E901 | Repository owner | BLOCKER:REMOTE-CI | Local branches/merges are traceable, but current remote GitHub/GitLab pipelines and PR state were not run or claimed. |
| DOD-11 | PASS | STANDARD | E005 | Task 20 | - | Both CI configurations and the GitLab unit-test job have local parsed contract evidence. |
| DOD-12 | PASS | STANDARD | E005 | Tasks 1-22 | - | A current contract reads SPEC/PLAN/log/handoff/deployment anchors and README truth boundaries instead of relying on historical file statistics. |
| DOD-13 | PARTIAL | IMPORTANT | E902, E903 | Task 24 | BLOCKER:TASK24-AUDIT | Functional and Engineering audits now exist; Product Audit remains future work. |
| DOD-14 | PASS | IMPORTANT | E003, E008, E011, E012 | Task 22 | - | No known Critical functional bug or unaccepted High security issue is open; license/Secret gates pass, and raw image findings remain visible behind exact VEX evidence rather than suppression. |
| DOD-15 | PASS | IMPORTANT | E008, E014 | Task 22 | FIXED:E014 | The missing-checker RED is preserved separately in E006; focused, locked-Linux, and exact brief gates pass without fabricating external evidence. |
| DOD-16 | PARTIAL | IMPORTANT | E904 | Student | BLOCKER:STUDENT-MANUAL | README cold start, real personal music upload, core interaction, PR/CI/Secret review, and REFLECTION.md remain student-only work. |

## Open blockers

| Blocker ID | Class | Status | Owner | Evidence IDs | Notes |
| --- | --- | --- | --- | --- | --- |
| TC-021 | EXTERNAL | OPEN | Cloud operator | E900 | Supply Tencent Cloud/Lighthouse, domain/DNS, SSH, and digest-qualified registry authorization; then run target benchmark and complete public smoke. |
| REMOTE-CI | EXTERNAL | OPEN | Repository owner | E901 | Run GitHub Actions and GitLab CI for the actual commit; record URLs/status only after real pipelines finish. |
| TASK24-AUDIT | FOLLOW_UP | OPEN | Task 24 | E903 | Perform Product Audit and final delivery verification after Task 23. |
| STUDENT-MANUAL | MANUAL | OPEN | Student | E904 | Complete the explicitly reserved personal acceptance checklist and write REFLECTION.md without agent substitution. |
| CURRENT-BROWSER-E2E | ENVIRONMENT | OPEN | Task 24 | E905 | Restore the exact locked root/frontend dependency cache or provide a prebuilt no-egress browser environment, then rerun all four current Chrome tests; otherwise keep dependent items PARTIAL. |

## Definition of Done trace map

The DOD IDs preserve the SPEC order: A-D end-to-end, real upload, interactive
timeline, deterministic theory, Evidence Explanation, no-Key fallback, full
tests/build, Docker runtime, Secret audit, Git/PR history, dual CI config,
process documentation, three audits, no known Critical/High issue, no fabricated
evidence, and the student's reserved final acceptance.

## Parked engineering follow-up

`tests/deploy/test_shell_line_endings.ps1` currently invokes the multi-file
`bash -n` portion through a harness shape that does not prove every file was
parsed independently. Task 21's real `.gitattributes` LF fix and other shell
evidence remain recorded, but this test-harness defect is neither called a
closed functional defect nor allowed to change an AC-A through AC-F verdict.
It is explicitly handed to Task 23 for RED-to-GREEN repair.
