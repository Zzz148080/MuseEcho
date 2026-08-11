# Task 22 — Functional Audit and acceptance-gap closure report

## Status

`DONE_WITH_CONCERNS`. The local Task 22 deliverables and proportionate
verification are complete. The machine-readable audit validates all 40 SPEC
items as `29 PASS / 11 PARTIAL / 0 FAIL` and deliberately reports
`PARTIALLY_READY`. Public/target-server evidence, remote CI, Task 23/24 audits,
the current browser E2E, and the student's own acceptance remain open and
prevent `READY`.

One process constraint was violated during current Docker smoke: the existing
smoke script's mandatory build encountered an invalid gateway cache and ran the
lockfile-bound `npm ci --ignore-scripts`, fetching 167 packages. No manifest,
lockfile, host installation, or dependency version changed. The event is
recorded in full under **Constraint concern** and is the reason for the
`DONE_WITH_CONCERNS` status.

## Approved design decisions

- `docs/audits/FUNCTIONAL_AUDIT.md` is the human-readable source of truth. Its
  exact Markdown metadata and tables are also a deliberately small parser
  contract; the checker does not infer verdicts from prose or file presence.
- The item contract is fixed to 24 AC items (`AC-A-1` through `AC-F-6`) plus 16
  ordered DoD items (`DOD-01` through `DOD-16`). The checker traces the AC
  counts/order and DoD fragments back to `SPEC.md`.
- Evidence has an ID, kind, exact command, repository-relative path, explicit
  item coverage, measurable result, optional boundary digest, real UTC
  observation time, exit status, and summary. Executed evidence is checked
  against independent code policy, not merely accepted because audit text is
  internally consistent.
- Historical browser evidence additionally requires its fixed full commit,
  current source/test boundary SHA-256, a repository PLAN anchor, and fixed
  historical content assertions. Git-enabled runs also verify the commit and
  historical archive; Git-less runs retain the independent policy and current
  boundary checks.
- `PASS` requires successful executed evidence. `FILE_EXISTENCE` and
  `EXTERNAL_NOT_RUN` cannot make an item pass. Important `PARTIAL`/`FAIL` items
  need a linked open blocker or passing fix/revalidation evidence.
- Required external, follow-up, and manual conditions are explicit open
  blockers. Any non-PASS item or open blocker contradicts `READY`.

The repository PLAN was already the approved design, so brainstorming recorded
these decisions and implementation continued without a second approval wait.

## TDD evidence

### Initial RED

The acceptance test was created before the checker or audit. Fresh command at
`2026-08-11T08:56:00Z`:

```powershell
..\feat-20-production-delivery\.venv\Scripts\python.exe -m pytest tests/unit/test_acceptance_matrix.py -q
```

Exit `1` during collection with the expected
`ModuleNotFoundError: scripts.check_acceptance_matrix`.

### First GREEN and mutation scope

The minimal parser/checker and matrix made the focused suite pass. The final
focused suite contains 26 tests and covers:

- the complete 40-ID contract, missing and duplicate items;
- illegal verdicts and PASS without evidence;
- missing command/path/UTC, future time, and future audit generation time;
- duplicate evidence IDs and the same record reindexed under another ID;
- historical exact commit/command/path binding and operation without Git;
- important PARTIAL/FAIL without a blocker or passing fix;
- `READY` contradicting non-PASS/open blockers;
- file-presence or external-not-run evidence masquerading as PASS;
- falsely resolving target/public, remote-CI, future-audit, or student work;
- the checker CLI against the real audit.

Focused GREEN at `2026-08-11T09:12:22Z` was `26 passed`, exit `0`.

### Real checker portability gap: RED to GREEN

The first locked-Linux full run completed with `612 passed, 23 failed`. All 23
failures had one root cause: the production image intentionally contains no
Git, while historical evidence validation launched `git cat-file` directly
and raised `FileNotFoundError`.

Two focused tests were added first: exact historical structure must validate
with an empty `PATH`, and a changed commit must be rejected unless the command
binds that exact commit and path. Both failed before the fix. The minimal fix
requires the exact 40-character commit plus command/path binding everywhere,
uses `git cat-file` when Git exists, and retains offline structural checking
when it does not. The two tests then passed, the 26-test focused suite passed,
and the locked Linux regression became `637 passed in 177.01s`, exit `0`.

### Real Secret test-harness gap: RED to GREEN

Fresh `scripts/test-secret-scan.ps1` initially exited `1`. The production
scanner correctly failed closed on its locked unreadable fixture and emitted
`scan-error`; PowerShell formatted `tracked-unreadable.txt` across whitespace,
so the synthetic harness's raw substring assertion misclassified the result.

The minimal fix normalizes whitespace only in the captured diagnostic before
matching the complete filename. Scanner behavior and credential policy were
not changed. Fresh GREEN at `2026-08-11T09:23:31Z` was
`Secret scan synthetic tests passed.`, exit `0`.

## Functional evidence summary

The detailed command/path/time/exit mapping is in
`docs/audits/FUNCTIONAL_AUDIT.md`. Key current results are:

| Gate | UTC | Result |
| --- | --- | --- |
| Frontend Vitest | `2026-08-11T08:59:27Z` | 12 files / 66 tests passed |
| Frontend typecheck/build + root E2E TypeScript | `2026-08-11T08:59:43Z` | exit 0 |
| Secret scan | `2026-08-11T09:00:03Z` | 200 files, exit 0 |
| Locked Linux full suite | `2026-08-11T09:12:46Z` | 637 passed in 177.01s, exit 0 |
| Production container smoke | `2026-08-11T09:17:12Z` | real WAV, persistence, ciphertext boundary, image history, cleanup; exit 0 |
| Ruff format/lint + mypy | `2026-08-11T09:21:39Z` | 89 formatted files, 45 source files plus checker; exit 0 |
| License audit | `2026-08-11T09:22:50Z` | exit 0 |
| Secret synthetic suite | `2026-08-11T09:23:31Z` | exit 0 |
| Exact brief gate | `2026-08-11T09:26:21Z` | 26 passed; 40 items validated; exit 0 |

The 120-second first Linux attempt was terminated by its explicit outer time
limit before the historically expected 171–185 second completion window; its
container and task temp cleanup were confirmed empty. It was not classified as
a product failure. One non-concurrent rerun used a 240-second hard bound and
produced the final 637-pass result above.

The exact brief command was run with cached `uv 0.11.29` in the existing
`museecho-python-builder:task20-final` image. Because the image lacks pytest,
the already locked Task 20 virtual-environment pytest modules were mounted
read-only with a small ignored command wrapper. The container used
`--pull=never --network none` and `UV_NO_SYNC=1`; no package resolution,
installation, or download occurred. The command itself remained exactly:

```sh
uv run pytest tests/unit/test_acceptance_matrix.py -q && uv run python scripts/check_acceptance_matrix.py SPEC.md docs/audits/FUNCTIONAL_AUDIT.md
```

The pre-review output, superseded by review fix round 1, was `26 passed in
2.93s` followed by
`40 acceptance items validated: PASS=34 PARTIAL=6 FAIL=0;
readiness=PARTIALLY_READY`, exit `0`.

The pre-review verification, superseded by review fix round 1, repeated this
exact inner command against the then-completed audit. The three bounded setup
attempts all remained offline and demonstrated fail-closed behavior rather than
being hidden:

1. Mounting `scripts`, `tests`, `docs`, and `SPEC.md` without `src/` exited `4`
   because the repository `tests/conftest.py` could not import `museecho`.
2. Adding `src/` but not all evidence paths ran 23 tests successfully and
   failed 3; the checker reported the absent `frontend/`, `AGENT_LOG.md`,
   `TASK20_HANDOFF.md`, `DEPLOYMENT_EVIDENCE.md`, and `PLAN.md` paths.
3. Mounting the whole worktree read-only passed all 26 tests and the 40-item
   checker, exit `0`, but emitted one expected `PytestCacheWarning` because its
   cache provider tried to write below `/repo`.

For the pre-review pristine run, which review fix round 1 superseded, the same
whole-worktree read-only mount added only `PYTEST_ADDOPTS=-p no:cacheprovider`;
the brief command itself was unchanged. At `2026-08-11T09:34:42Z`, cached uv
`0.11.29` reported `26 passed in 5.96s`; the superseded pre-review checker
reported `PASS=34 PARTIAL=6 FAIL=0` and
`readiness=PARTIALLY_READY`. Exit was `0`, with no warnings. All four attempts
used `--pull=never --network none`, `UV_NO_SYNC=1`, and the same existing
builder/locked modules; none performed a fetch or install.

## Pre-review acceptance result and open blockers (superseded)

At the pre-review checkpoint, the six then-current PARTIAL items were:

- `AC-A-4`: no five-minute benchmark from the actual target server
  (`TC-021`);
- `AC-F-5`: no public URL or trusted-certificate complete smoke (`TC-021`);
- `AC-F-6`: Engineering and Product audits have not run (`TASK23-AUDIT`);
- `DOD-10`: current GitHub Actions/GitLab CI and PR state were not run
  (`REMOTE-CI`);
- `DOD-13`: only the Functional Audit exists; Tasks 23/24 remain
  (`TASK24-AUDIT`);
- `DOD-16`: personal cold-start/core-flow acceptance and `REFLECTION.md` are
  reserved for the student (`STUDENT-MANUAL`).

These conditions do not block local Task 22 completion, but every one prevents
a `READY` claim. No cloud account, DNS, SSH, remote repository/CI, registry,
or public-service mutation occurred.

## Historical and not-run boundaries

- Current real-browser E2E was not rerun. The host lacks the product audio
  runtime expected by that path, and after the network constraint incident no
  fetch was allowed. The audit instead binds the exact Task 19 commit
  `1047ce242884b6ba83a525524e88dcc44ab76a69`, whose tracked record contains four
  real HTTPS Chrome E2E passes. It is not described as current public evidence.
- The same exact Task 19 record contains a two-core local five-minute benchmark
  of 11.201268 seconds. It supports the local gate only and does not substitute
  for the required target-server result.
- Remote CI, the public/target-server checks, Tasks 23/24, and student manual
  acceptance were not run and appear as `EXTERNAL_NOT_RUN` evidence.
- `.superpowers/sdd/PLAN/task-20-final-fix-wave-report.md` was absent from this
  base. The audit does not cite it; Task 20 evidence is bound to the existing
  `TASK20_HANDOFF.md` at exact commit
  `c65a16b3430c298c4bd10420ba1cd5b71a87931d`.

## Constraint concern

At `2026-08-11T09:17:12Z`, this existing command was launched for current
production smoke:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/container-smoke.ps1
```

The script calls `docker compose ... build` unconditionally at
`scripts/container-smoke.ps1:117`. A gateway build cache miss reached the
existing Dockerfile instruction `RUN npm ci --ignore-scripts` and fetched 167
packages from the lockfile in approximately 39 seconds; npm reported zero
vulnerabilities. This was not an intentional dependency update, but it is
nonetheless a network package fetch and violates the Task 22 no-download
constraint.

After discovery, no further network retrieval was attempted. Read-only checks
confirmed:

- `git diff --exit-code 863fd2a2cf29c1fd0e0291b9a3eb986dbd620f50 -- package.json package-lock.json frontend/package.json frontend/package-lock.json pyproject.toml uv.lock` exited `0`;
- no host package/tool installation occurred; the only ignored environment
  links point at the existing Task 20 `.venv` and `node_modules`;
- no new image name was introduced. Normal smoke tags were refreshed to
  `museecho-app:local` (`sha256:6587f529...`) and
  `museecho-gateway:local` (`sha256:256225b...`);
- no MuseEcho containers, volumes, or smoke temporary directories remained.

All later container commands used existing images with `--pull=never` and
`--network none`. Any gate that would have needed network was left not run.

## Parked Task 21 engineering item

The multi-file `bash -n` shape in
`tests/deploy/test_shell_line_endings.ps1` does not independently prove every
shell input was parsed. Per the Task 22 brief, this is recorded for Task 23 and
was not modified, described as closed, or used to alter a functional verdict.

## Files delivered

- `docs/audits/FUNCTIONAL_AUDIT.md`
- `scripts/check_acceptance_matrix.py`
- `tests/unit/test_acceptance_matrix.py`
- the focused diagnostic-output correction in `scripts/test-secret-scan.ps1`
- Task 22 status/evidence updates in `PLAN.md`, `AGENT_LOG.md`,
  `REFLECTION_NOTES.md`, and `BLOCKERS.md`
- this report

`REFLECTION.md` was not written or modified.

## Self-review

- Compared the matrix one-for-one against AC-A through AC-F and the ordered DoD
  text: 40 unique items, with no merged or unclassified item.
- Exercised fail-closed mutation behavior rather than treating the audit as a
  file-presence checklist.
- Checked all audit evidence timestamps against its generation time and current
  UTC; no future evidence or fabricated execution is present.
- Kept current, exact historical, file-only, and not-run evidence semantically
  distinct; no public, remote-CI, Task 23/24, or student event is claimed.
- Reviewed the diff for secrets and protected/unrelated paths. Neither
  `ai4coding-agentos-lab/` nor `docs/input/` was read or changed.
- Confirmed the parked Task 21 harness issue remains assigned to Task 23.

## Review fix round 1/5 — evidence authenticity

### Findings reproduced and RED

The review findings were verified against `4ca6be8`. The root issue was not a
single weak command: the checker treated audit-text coherence as authenticity.
For `CURRENT_COMMAND`, kind plus exit `0` and a short denylist were sufficient.
For historical evidence in a Git-less runtime, commit/command/path agreement
inside the same editable Markdown row was sufficient. E005 used a historical
`git show --stat` and never read either CI definition or README.

Nine audit-only mutation tests were written before the implementation change.
The old checker accepted every mutation, so the focused RED was `9 failed, 26
deselected`, exit `1`. The mutations covered:

- replacing E008 command, result, and summary coherently with a vacuous success;
- valid evidence claiming an unrelated item, and coherent result rewriting;
- coherent fake E004 commit/command in a Git-less process;
- E004 boundary path drift, missing/zero boundary SHA, and a drifted historical
  record used as the sole support for PASS;
- E005 omitting a current CI/README contract while its Markdown row remained
  superficially successful.

### Minimal implementation and GREEN

`scripts/check_acceptance_matrix.py` now owns a compact immutable contract for
each executed evidence ID: kind, exact command, path, exact item coverage,
measurable result, exit status, and whether it may support PASS. A PASS row must
cite a passing contract that explicitly covers that item. This policy cannot be
changed by editing only the audit. The nine review mutations then passed (`9
passed, 26 deselected`), and the full focused suite passed (`35 passed`).

Historical E004 is fixed to commit
`1047ce242884b6ba83a525524e88dcc44ab76a69` and command
`git show 1047ce242884b6ba83a525524e88dcc44ab76a69:AGENT_LOG.md
1047ce242884b6ba83a525524e88dcc44ab76a69:PLAN.md`. The current canonical
browser/source/test boundary contains 107 files and has SHA-256
`dc3ccfff5d317e489be27454425ffd1e48a07c5e292cb3638a3d07d0b562f489`.
The historical boundary contains 105 files and has SHA-256
`063f1dd0e3b9a27aa7772e3e2320e681facd7df2ff9e58e8e9e3c204f02bdc5d`.
The checker verifies the current digest and exact PLAN anchor in every runtime;
with Git it additionally verifies the commit and a single canonical archive of
the historical boundary, including the recorded browser count and benchmark.
Consequently E004 is explicitly `boundary-state=DRIFT` and cannot support PASS.

The first boundary implementation performed roughly 105 `git show` processes
per checker invocation and the focused run hit its 124-second bound. A trace
identified repeated process startup, not a product failure. One offline `git
-c core.autocrlf=false archive` replaced the per-file calls; the explicit Git
configuration also removed a Windows line-ending digest mismatch. The suite
then completed in seconds without a cache or fail-open fallback.

E005 is now a current seven-test delivery contract. It parses both
`.github/workflows/ci.yml` and `.gitlab-ci.yml`, requires the GitLab `unit-test`
stage/script and relevant GitHub commands, reads the README locked cold-start,
development HTTPS, production smoke, health, and cleanup instructions, and
checks SPEC/PLAN/log/handoff/deployment truth anchors. Its initial run was `6
passed, 1 failed` because PLAN abbreviated the Task 19 evidence commit; after
recording the already-authoritative full hash it passed `7 passed in 0.52s` at
`2026-08-11T10:17:47Z`.

### Current browser attempt and verdict changes

The current frontend built successfully from existing local dependencies. A
bounded Chrome E2E attempt then launched the existing FFmpeg-capable app image
on a Docker `--internal` network. The app started and was healthy inside the
container, but Docker Desktop did not expose the published port to host Chrome;
the 60-second loopback health bound expired before Playwright started. The
container and temporary network were removed. No outbound-capable bridge was
tried because that would relax the explicit no-network boundary, and no
dependency, image, browser, or tool was downloaded.

Because the only completed Chrome record has a drifted boundary, AC-C-3,
AC-F-1, DOD-01, DOD-03, and DOD-07 were downgraded from PASS to important
PARTIAL with `CURRENT-BROWSER-E2E`. The matrix is therefore `29 PASS / 11
PARTIAL / 0 FAIL`; readiness remains `PARTIALLY_READY`. This is an environment
and evidence gap, not a claimed product failure.

### Review verification evidence

- Git-less pristine gates: existing cached uv `0.11.29`, `--pull=never`,
  `--network none`, read-only worktree, `UV_NO_SYNC=1`, and pytest cache provider
  disabled. The first review pass was `35 passed in 69.04s`, checker `29 PASS /
  11 PARTIAL / 0 FAIL`, exit `0`, wall 80.4 seconds. The completed-audit run was
  `35 passed in 67.98s`, the same checker result, exit `0`, wall 77.78 seconds,
  with no warning. The processes had no `git` executable.
- Locked Linux regression: existing `museecho-app:task20-final`, network none
  and read-only repository; `649 passed in 244.21s`, exit `0`, wall 256.7
  seconds. Containers and task temporary directories were empty afterward.
- Current CI/README/process contract: `7 passed in 0.52s`, exit `0`.
- Quality: Ruff format check covered 89 files, Ruff lint passed, mypy passed for
  45 application sources and the checker; license audit passed.
- Secret gates: all synthetic mutations passed and the fresh real scan checked
  202 tracked/non-ignored files, both exit `0`.

Remote CI, public/target-server smoke and benchmark, Task 23/24 audits, and the
student acceptance were not run. The earlier mandatory Docker smoke build's
167-package locked npm fetch remains a process concern; this review round made
no network retrieval and changed no package or lock manifest.

Two final-run setup probes also failed closed before test collection and are
not hidden: making the entire container root read-only prevented uv from
creating its own cache lock (exit `2`, 0.77 seconds), and omitting
`UV_PROJECT_ENVIRONMENT=/app/.venv` made uv reject the read-only repository
`.venv` junction (exit `2`, 0.83 seconds). The final invocation preserved the
required read-only worktree while using the existing writable container overlay
and existing `/app/.venv`; it performed no sync, install, or download.

A final short-gate pass initially found one documentation-contract regression:
updating AGENT_LOG had preserved the historical browser fact but removed the
exact phrase `4 个真实 HTTPS 浏览器 E2E` required by E005. The 7-test contract
reported `6 passed, 1 failed`; restoring that exact fact while explicitly
retaining the drift/non-PASS qualification made it `7 passed in 0.49s`. The
same final batch produced focused `35 passed in 14.67s`, checker `29/11/0`,
Ruff/mypy/Secret/license success, unchanged package/lock manifests, no protected
path diff, and a clean diff check.

## Review fix round 2/5 — current-stat documentation consistency

The review finding was reproduced at `d6d3eab`: the audit and checker said
`29 PASS / 11 PARTIAL / 0 FAIL`, while REFLECTION_NOTES still described six
PARTIAL items as current. The pre-review exact-gate section also preserved the
real 34/6 command output but called it `final verification`, `pristine final`,
and a completed-audit result without saying that review fix round 1 superseded
it.

The existing seven-test process contract was extended before editing prose. It
derives verdict counts by parsing the current functional audit, pins the
expected `29/11/0` result, requires the canonical status in REFLECTION_NOTES,
AGENT_LOG, BLOCKERS, PLAN, and this report, rejects the stale Chinese
`保持 6 个 PARTIAL` statement, and allows 34/6 history only when `pre-review`
and `superseded` occur next to each old result. This preserves real historical
output without allowing it to masquerade as current/final state.

The focused RED was `1 failed` because REFLECTION_NOTES lacked the current
29/11/0 status. After the first prose change it remained RED because the
superseded marker was too far from the second 34/6 output to survive a bounded
context read. Moving `superseded pre-review` directly next to that checker
result produced the targeted GREEN (`1 passed in 0.17s`). The full process
contract then passed `7 passed in 0.51s` after Ruff's mechanical formatting.

Fresh review-round verification:

- host acceptance suite: `35 passed in 14.48s`;
- current process contract: `7 passed in 0.51s`;
- host checker: 40 items, `29 PASS / 11 PARTIAL / 0 FAIL`,
  `PARTIALLY_READY`;
- Git-less pristine exact gate: cached uv `0.11.29`, `--pull=never`,
  `--network none`, read-only worktree, no sync, pytest cache disabled;
  `35 passed in 67.70s`, the same checker result, no warning, exit `0`, wall
  76.80 seconds;
- focused Ruff format/lint clean; fresh Secret scan checked 202 files; package
  and lock manifests unchanged; protected-path and diff checks clean.

No checker policy, audit evidence, functional verdict, package/lock file, or
Task 19 browser boundary input changed, so the locked Linux suite and boundary
policy did not require regeneration. This round used no network and performed
no external-state operation.

## Commit

The primary implementation/evidence commit is
`abb33e036965f877a860ad5916f4b23ea7ffa417` —
`audit: verify functional acceptance criteria`. This hash backfill is delivered
in a subsequent documentation-only commit so the primary commit remains
independently identifiable.

Review fix round 1 is
`22d587beb68170ab4af79a7665d1942881700499` —
`fix: bind functional audit evidence contracts`. Its hash is backfilled in the
following documentation-only commit.

Review fix round 2 is
`86be4968ed3b6abf14c3d058f22409a923e33f1f` —
`docs: keep functional audit statistics current`. Its hash is backfilled in the
following documentation-only commit.

## Superseded by Task 23 review round 1

Task 23 did not rerun frontend typecheck/build because the exact locked cache
was unavailable and downloads were prohibited. Therefore the Task 22 current
claim above is historical, not current evidence. The authoritative matrix is
now `28 PASS / 12 PARTIAL / 0 FAIL`, with AC-F-4 changed to PARTIAL and linked
to the still-open current-browser/frontend environment blocker.
