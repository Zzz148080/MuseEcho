# 100 MB Audio Upload Limit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accept and analyze audio files up to 100 MiB without weakening streaming, duration, cleanup, or server-side enforcement.

**Architecture:** Raise the authoritative Python file ceiling to 100 MiB and keep the request ceiling derived as file bytes plus 64 KiB multipart overhead. Mirror that exact boundary in browser preflight and user-facing documentation while leaving the 600-second decode and PCM-memory limits unchanged.

**Tech Stack:** Python 3.12, FastAPI/Starlette, pytest, React 19, TypeScript, Vitest.

## Global Constraints

- Accept exactly `100 * 1024 * 1024` file bytes and reject the first byte above it.
- Keep `DEFAULT_REQUEST_OVERHEAD_BYTES = 64 * 1024` and derive the request-body ceiling from the file ceiling.
- Keep the decoded duration ceiling at 600 seconds.
- Do not change supported formats, FFmpeg allowlists, encrypted retention, or result presentation.
- Do not add a Caddy body cap or a new runtime dependency.

---

### Task 1: Server file and request boundaries

**Files:**
- Modify: `tests/api/test_upload.py`
- Modify: `src/museecho/application/uploads.py`

**Interfaces:**
- Consumes: `UploadSubmissionService.submit(source, filename, media_type)` and the installed default `UploadBodyLimitMiddleware`.
- Produces: `DEFAULT_MAX_UPLOAD_BYTES == 100 * 1024 * 1024`; `DEFAULT_MAX_UPLOAD_REQUEST_BYTES == DEFAULT_MAX_UPLOAD_BYTES + 64 * 1024` remains derived in `museecho.api.analyses`.

- [ ] **Step 1: Add a failing service regression test**

Add a test that submits a generated WAV-named stream of `30 * 1024 * 1024 + 1` bytes through a default `UploadSubmissionService`, uses the existing valid probe and recording collaborators, and asserts one job, one encrypted-store write, and one queued analysis. This catches a regression to the old 30 MiB ceiling through observable submission behavior.

- [ ] **Step 2: Add a failing default middleware boundary test**

Exercise the real `UploadBodyLimitMiddleware` with no explicit override. Send an analysis-upload ASGI scope whose `Content-Length` is `100 * 1024 * 1024 + 64 * 1024`; assert the downstream application is called. Repeat with one additional byte and assert the emitted response status is 413 with no downstream call.

- [ ] **Step 3: Verify RED**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/api/test_upload.py -q --basetemp=tmp/100mb-red
```

Expected: the new service test raises `UploadTooLargeError` at the old 30 MiB boundary, and the new default middleware test returns 413 for the now-valid 100 MiB-plus-overhead request.

- [ ] **Step 4: Implement the minimal server change**

Change only the authoritative value in `src/museecho/application/uploads.py`:

```python
DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024
```

Keep `DEFAULT_MAX_UPLOAD_REQUEST_BYTES` derived from it and keep both constructors fail-closed above their supported ceilings.

- [ ] **Step 5: Verify GREEN**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/api/test_upload.py -q --basetemp=tmp/100mb-server-green
```

Expected: all upload API tests pass, including early `Content-Length` rejection and chunked-request enforcement.

---

### Task 2: Browser and current product contract

**Files:**
- Modify: `frontend/src/features/upload/UploadForm.test.tsx`
- Modify: `frontend/src/features/upload/UploadForm.tsx`
- Modify: `README.md`
- Modify: `SPEC.md`
- Modify if required by the audit checker: `docs/audits/FUNCTIONAL_AUDIT.md`

**Interfaces:**
- Consumes: browser `File.size`, `validateFile(file)`, and `uploadErrorPresentation(reason)`.
- Produces: browser preflight and all current product guidance consistently expose a 100 MB limit.

- [ ] **Step 1: Replace the old frontend size test with failing boundary behavior**

Use lightweight `File` objects whose `size` properties are overridden without allocating 100 MiB. Assert that exactly `100 * 1024 * 1024` returns no validation error and that `100 * 1024 * 1024 + 1` renders an alert containing `不能超过 100 MB` before any upload transport call.

- [ ] **Step 2: Verify frontend RED**

Run:

```powershell
npm.cmd --prefix frontend test -- --run src/features/upload/UploadForm.test.tsx
```

Expected: the exactly-100-MiB case is rejected and the error still says 30 MB.

- [ ] **Step 3: Implement browser and documentation alignment**

Set `MAX_UPLOAD_BYTES` to `100 * 1024 * 1024`; change the help text, local validation message, and `upload_too_large` presentation to 100 MB. Change current limits in `README.md` and all current requirements/risk entries in `SPEC.md` from 30 MB/MiB to 100 MB/MiB. Leave historical Superpowers design/plan documents unchanged because they record earlier approved boundaries; this plan and its design supersede them.

- [ ] **Step 4: Verify frontend GREEN and static types**

Run:

```powershell
npm.cmd --prefix frontend test -- --run src/features/upload/UploadForm.test.tsx
npm.cmd --prefix frontend run typecheck
npm.cmd run typecheck
```

Expected: focused Vitest, frontend TypeScript, and E2E TypeScript all pass.

- [ ] **Step 5: Verify the immutable historical audit boundary**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_acceptance_matrix.py tests/unit/test_engineering_audit.py -q --basetemp=tmp/100mb-audit
.venv\Scripts\python.exe scripts/check_acceptance_matrix.py SPEC.md docs/audits/FUNCTIONAL_AUDIT.md
```

E004 is bound to its exact historical commit/tree and historical boundary digest. Never refresh it from
mutable current files. If verification fails, restore or fetch the exact historical Git object and investigate
the mismatch; do not rewrite historical evidence to match the checkout.

- [ ] **Step 6: Run complete verification and publish**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/container-pytest.ps1 -Image museecho-task3-verification-env:latest
npm.cmd --prefix frontend test -- --run
npm.cmd --prefix frontend run build
.venv\Scripts\python.exe scripts/license_audit.py
git diff --check
```

Expected: the locked-container Python suite, all frontend tests, production frontend build, license audit, and diff integrity pass. Commit only the intended files, push `codex/expand-common-audio-formats`, and monitor PR #3's `quality`, `e2e`, and `distribution` jobs to successful terminal state.
