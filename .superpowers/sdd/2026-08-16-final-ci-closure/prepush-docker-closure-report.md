# Pre-push Docker verification closure report

## Scope

- Base commit: `9764b7778d664303e6b2c8bf83eee1ba5558f539`.
- Authority: `scripts/container-pytest.ps1 -Image museecho-app:local` with
  `D:\DockerDesktop\App\resources\bin` prepended to `PATH`.
- The production image remained Git-less, the repository mount remained read-only, and the
  container remained network-disabled.
- No checker behavior, GitLab/dual-CI wording, final-SHA CI wording, or retained historical Task
  23 evidence was changed.

## Systematic debugging and RED evidence

The unchanged base reproduced the authoritative failure set exactly:

```text
9 failed, 846 passed, 7 skipped in 318.96s (0:05:18)
```

The nine deterministic failures divided into three root causes:

1. `scripts/image-vulnerability-policy.json` retained the pre-guard digest
   `5e344024...e611dd` for `src/museecho/analysis/rhythm.py`, while the reviewed current source
   normalized to `f622cf3a...d6f8e`.
2. `test_course_status_documents_reject_stale_draft_and_final_ci_claims` wrote and restored
   `/workspace/PLAN.md` directly. The authoritative harness deliberately mounts `/workspace`
   read-only, so both the mutation and its `finally` restoration raised `EROFS` before the
   validator behavior could be exercised.
3. Seven historical-tree integration cases required a real Git executable and retained object
   database. The production image intentionally has neither. Four acceptance-matrix cases failed
   closed with `E004 exact historical commit/tree is unavailable`; three engineering-audit test
   instances could not enter their intended success or commit-specific error branch because
   `git cat-file` could not execute.

## Minimal changes

- Refreshed only the current runtime-boundary digest for
  `src/museecho/analysis/rhythm.py` in `scripts/image-vulnerability-policy.json`.
- Added local Git/object-database prerequisite helpers to the acceptance-matrix and
  engineering-audit test modules. Calls were added only to the four and three test instances that
  require real historical objects. Checker code was not weakened.
- Kept `test_historical_evidence_fails_closed_when_git_is_unavailable` active and focused-GREEN,
  preserving deterministic proof that the acceptance checker fails closed without Git.
- Reworked the course-document mutation helper to copy only the validator's required repository
  files into `tmp_path`, mutate that isolated copy, and validate against the copied repository
  root. It no longer writes any tracked document.

## GREEN and verification evidence

Focused host verification:

```text
acceptance focused (including missing-Git fail-closed): 5 passed, 44 deselected
engineering historical focused:                       3 passed, 102 deselected
delivery-report read-only regression:                  1 passed
current policy/runtime boundary:                       1 passed
all four affected test modules:                        213 passed, 1 skipped in 56.58s
```

Checker and static/security verification:

```text
check_acceptance_matrix.py: 40 items validated; PASS=31 PARTIAL=9 FAIL=0
check_engineering_audit.py --schema-only: 10 findings validated
check_delivery_report.py: 17 sections; evidence=16; blockers=3; PARTIALLY READY
Ruff on changed Python: All checks passed
secret scan before report: 234 tracked/non-ignored files checked
secret scan after staging the report: 235 tracked/non-ignored files checked
```

Mypy was not required because no production or checker Python was changed.

Final authoritative Docker GREEN:

```text
848 passed, 14 skipped in 315.74s (0:05:15)
```

The count is closed against the RED run: two deterministic failures became passes and the seven
real-Git historical integration instances became narrow prerequisite skips. The other 848 tests,
including the explicit missing-Git fail-closed case, executed successfully.

## Final commit hygiene

The complete change set received a fresh secret scan after the report was written, and
`git diff --check` exited `0` (with only the repository's existing LF-to-CRLF checkout warnings).
Only the five reviewed paths listed below are staged for the single commit, and the cached diff is
inspected before committing:

- `scripts/image-vulnerability-policy.json`
- `tests/unit/test_acceptance_matrix.py`
- `tests/unit/test_delivery_report.py`
- `tests/unit/test_engineering_audit.py`
- `.superpowers/sdd/2026-08-16-final-ci-closure/prepush-docker-closure-report.md`

## Concerns

- The production image intentionally reports seven additional skips because Git and the object
  database are not production dependencies. The same cases execute and pass on the host where
  those prerequisites exist.
- Retained historical policy/evidence was deliberately not refreshed. Only the current-source
  distribution-boundary digest changed.
- Final PR-SHA and post-push CI claims remain pending by design and were not edited in this
  closure.
