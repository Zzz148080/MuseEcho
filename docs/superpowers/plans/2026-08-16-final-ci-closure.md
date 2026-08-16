# Final CI Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely consolidate the intentional course-delivery documentation, update its fail-closed contracts, refresh the current-source security boundary, repair the Ruff failure, push the existing PR branch, and obtain a green GitHub CI result for the final branch SHA.

**Architecture:** Keep the product behavior from `7f8412b` unchanged. Treat the work as three reviewable units: course/process documentation plus its validator contract, current-source security-boundary synchronization, and the exact formatter repair reported by GitHub Actions; verify locally before pushing and use the live PR checks as the final authority.

**Tech Stack:** Git, GitHub Actions/CLI, Markdown, Python 3.12, uv, Ruff, mypy, pytest, Node.js/npm, Vitest, Playwright, Docker/OCI CI.

## Global Constraints

- Preserve all user-owned changes and stage only files reviewed for this task; never use a blind `git add -A`.
- Record the student's reported rule faithfully: passing requires completing at least 6 of the 9 listed deliverables; do not claim the other 3 are complete.
- Do not rewrite the student's reflection or claim student-only acceptance work.
- Keep current PR #3 failure logs and the most recent successful branch/main evidence while cleaning only regenerable Actions artifacts/caches.
- Do not touch files outside `D:\智软工程师大项目\MuseEcho` during repository work.
- Completion requires fresh local verification plus `quality`, `e2e`, and `distribution` success on the final pushed SHA.

---

### Task 1: Reconcile course and maintenance records

**Files:**
- Modify: `COURSE_REQUIREMENT_UPDATE.md`
- Modify: `COURSE_DELIVERY_CHECKLIST.md`
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`
- Review and retain if truthful: `README.md`, `SPEC.md`, `BLOCKERS.md`, `DELIVERY_REPORT.md`, `DEPLOYMENT_EVIDENCE.md`, `REFLECTION.md`, `REFLECTION_NOTES.md`
- Delete if confirmed superseded: `TASK20_HANDOFF.md`
- Modify: `tests/unit/test_delivery_report.py`
- Modify: `scripts/check_delivery_report.py`

**Interfaces:**
- Consumes: the teacher requirements supplied by the student and the existing Task 24+ repository history.
- Produces: a truthful mapping of the 9 deliverables, the reported 6-of-9 pass threshold, and maintenance provenance for the audio-format/player/rhythm work.

- [ ] **Step 1: Review every tracked and untracked documentation diff**

Run: `git status --short && git diff --check && git diff -- <each changed path>`

Expected: only intentional course-status, audio-support, and superseded-handoff changes; no whitespace errors.

- [ ] **Step 2: Add the missing teacher-rule and maintenance provenance facts**

Record that the student reported a minimum of 6 completed items out of 9, while retaining item-by-item truth and not marking deferred items complete. Add the actual Task 24+ maintenance scope and verification state to `PLAN.md` and `AGENT_LOG.md`.

- [ ] **Step 3: Write and verify the updated delivery-contract red tests**

Update focused tests so the current report requires exactly the three still-open course blockers, requires GitLab/cloud evidence to remain `NOT_RUN` but `DEFERRED`, allows a student-authored reflection draft without treating the student acceptance checklist as complete, and rejects regressions back to false completion claims. Run the focused tests before changing the validator.

Expected before validator repair: focused failures demonstrate the old five-blocker/blank-reflection contract.

- [ ] **Step 4: Implement and verify the minimal delivery-contract update**

Update `scripts/check_delivery_report.py` and the exact `DELIVERY_REPORT.md` evidence fields/headings needed by the new tests. Keep student checklist items reserved and keep deferred external work explicitly unexecuted. Run `tests/unit/test_delivery_report.py`, the checker CLI, and `git diff --check`.

Expected: focused delivery tests and checker pass; false READY, missing open blocker, false external execution, or false student acceptance still fail closed.

- [ ] **Step 5: Commit the reviewed documentation unit**

Stage only the reviewed documentation paths and commit them as one course/process-maintenance unit after inspecting `git diff --cached`.

Expected: the commit contains no product-code change, credential, generated bulk data, or unreviewed file.

### Task 2: Repair the exact CI formatter failure

**Files:**
- Modify: `src/museecho/analysis/decode.py`
- Modify: `src/museecho/analysis/rhythm.py`
- Modify: `tests/api/test_analysis_api.py`

**Interfaces:**
- Consumes: GitHub Actions run `31813100956`, whose `quality` job reports only these three Ruff formatting violations.
- Produces: Ruff-formatted source with no behavior or assertion changes.

- [ ] **Step 1: Reproduce the red formatter gate**

Run: `uv run ruff format --check src tests`

Expected before repair: exit 1 naming exactly the three files above.

- [ ] **Step 2: Apply the minimal formatter repair**

Run: `uv run ruff format src/museecho/analysis/decode.py src/museecho/analysis/rhythm.py tests/api/test_analysis_api.py`

Expected: exactly three files reformatted.

- [ ] **Step 3: Re-run focused and static gates**

Run: `uv lock --check`, `uv run ruff format --check src tests`, `uv run ruff check .`, `uv run mypy src`, and the focused decode/rhythm/API tests selected from the changed files.

Expected: every command exits 0.

- [ ] **Step 4: Commit the formatter-only repair**

Stage exactly `src/museecho/analysis/decode.py`, `src/museecho/analysis/rhythm.py`, and `tests/api/test_analysis_api.py`, inspect `git diff --cached`, and commit the CI formatting repair.

Expected: the commit changes layout only and contains no behavior or assertion change.

### Task 3: Synchronize the current-source security boundary

**Files:**
- Modify: `scripts/image-vulnerability-policy.json`
- Create if needed to preserve immutable Task 23 recomputation: `docs/audits/evidence/task23-image-vulnerability-policy.json`
- Modify only if required by the fixed evidence schema: `docs/audits/evidence/task23-security-manifest.json`
- Modify only if required by the fixed evidence schema: `scripts/check_engineering_audit.py`
- Modify: `tests/unit/test_image_vulnerability_audit.py` and/or `tests/unit/test_engineering_audit.py`
- Modify: `docs/audits/ENGINEERING_AUDIT.md` only to clarify historical versus current-source evidence; never relabel retained historical scans as current scans.

**Interfaces:**
- Consumes: the existing failing policy/runtime-boundary test, the formatter commit, and Task 24+ runtime changes in five source files.
- Produces: a policy whose runtime-boundary digests match current source while the Task 23 retained artifact facts remain immutable and explicitly historical.

- [ ] **Step 1: Capture the red security-boundary tests**

Run the committed-policy boundary test and engineering-audit validator tests using a repository-local pytest base temp.

Expected before repair: current source differs from the policy boundary; historical manifest validation must not be silently rewritten as current image evidence.

- [ ] **Step 2: Add the narrow historical/current boundary regression test**

Write the smallest test proving retained Task 23 artifact facts stay fixed while current-source policy drift is independently detected by the policy test and final distribution job.

Expected: the new test fails for the intended old coupling, not for fixture or temp-directory errors.

- [ ] **Step 3: Refresh only current-source policy and explicitly version historical validation**

Regenerate exact current runtime file digests after the formatter repair. If the retained Task 23 audit needs its old policy to remain reproducible, preserve that exact policy as a clearly named historical snapshot and make the historical checker validate/recompute against the snapshot without claiming it matches current source. Do not weaken the runtime-boundary equality enforced by `image_vulnerability_audit.py` for current distribution builds.

Expected: current policy matches current source; retained manifest/tar/scan facts remain unchanged and are labelled historical.

- [ ] **Step 4: Verify and commit the security-boundary unit**

Run the focused image-vulnerability and engineering-audit tests/checkers with repository-local temp paths, then inspect and commit only the reviewed security policy, checker, test, and audit-document paths.

Expected: focused gates pass with no false current-image or formal-release claim.

### Task 4: Verify, publish, and close CI

**Files:**
- Verify and publish the reviewed commits from Tasks 1 through 3; do not introduce unrelated product changes.
- Modify if required by the pre-push full-suite RED: `scripts/check_acceptance_matrix.py`, `tests/unit/test_acceptance_matrix.py`, `tests/unit/test_task20_final_delivery_contract.py`, and the exact current audit/process records they validate.

**Interfaces:**
- Consumes: reviewed documentation/contracts, current-source security boundary, and formatter-only source changes.
- Produces: one or more intentional commits on `codex/expand-common-audio-formats`, pushed PR #3, and a green final SHA.

- [ ] **Step 1: Run the complete local verification appropriate to CI risk**

Run the repository's documented verification commands, including backend tests, frontend type/tests/build, E2E or its repository wrapper, secret scan, and distribution/container contract gates available in the local environment.

Expected: all runnable gates exit 0; any environment-only limitation is recorded rather than hidden.

- [x] **Step 2: TDD-close non-environment full-suite contract drift**

Separate missing ffmpeg/ffprobe and paused-Docker failures from deterministic repository failures. For deterministic failures, capture focused RED tests, then minimally update the current GitHub-only course contract and historical evidence lookup so historical commit evidence is never compared to mutable current files. Replace the obsolete `TASK20_HANDOFF.md` process-document dependency with durable current records; do not restore stale status prose merely to satisfy a test.

Expected: focused acceptance-matrix and process-document tests pass while historical evidence remains commit-bound and current course requirements remain GitHub-only.

Completed locally with focused RED (`5 failed, 1 passed`) and deterministic GREEN (`51 passed`). E004 is bound to exact commit `1047ce242884b6ba83a525524e88dcc44ab76a69`, tree `835981d848f42b1dfda147d25aed606c4d249f35`, and historical boundary digest; the deleted Task 20 pause handoff is replaced by durable current records.

- [ ] **Step 3: Review the completed commit range**

Run: `git diff --check`, inspect the reviewed Task 1 through Task 4 commit range and confirm any remaining working-tree path is intentional and explicitly identified.

Expected: commits contain no credentials, generated bulk data, or unrelated files; the worktree has no unexplained change.

- [ ] **Step 4: Push and monitor PR #3**

Run: `git push origin codex/expand-common-audio-formats`, then use `gh pr checks 3 --watch --repo Zzz148080/MuseEcho` and inspect any failing job log before making a new fix.

Expected: `quality`, `e2e`, and `distribution` all pass on the same final head SHA.

- [ ] **Step 5: Fresh completion audit**

Run: compare local `HEAD`, `origin/codex/expand-common-audio-formats`, PR head SHA, and the successful workflow head SHA; run `git status --short --branch`.

Expected: all SHA values match, GitHub CI is green, and any remaining working-tree files are explicitly identified rather than silently omitted.
