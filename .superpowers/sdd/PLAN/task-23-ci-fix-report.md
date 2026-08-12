# Task 23 CI Secret-scan cleanup fix

## Root cause

GitHub Actions `quality` ran `pytest` with the non-ignored repository-local
temporary root `.pytest-ci`.  Pytest preserves per-test files below that root
after a successful run.  The later Secret scan correctly enumerates all tracked
and non-ignored untracked files and therefore sometimes attempts to read a
pytest file that has disappeared between enumeration and read.  Run
`31577576808` failed closed on exactly that race:
`scan-error: missing tracked or untracked file:
.pytest-ci/test_accepted_finding_requirescurrent`.

Local reproduction with `.venv\\Scripts\\python.exe -m pytest
tests\\unit\\test_engineering_audit.py -q --basetemp .pytest-ci` passed 92
tests and left non-ignored `.pytest-ci/test_*` files visible to
`git ls-files --cached --others --exclude-standard`.  This confirms the CI
temporary root, rather than a scanner false positive, is the source.

The production scanner is intentionally unchanged: it still fails closed for
any enumerated missing or unreadable file.  The correction removes only the
known test root before that scanner begins its enumeration.

## TDD evidence

### RED

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-red
```

Expected and observed: exit `1`, `StopIteration` because no `Clean CI pytest
temporary root` step existed.

### GREEN

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-green
```

Observed: exit `0`, `9 passed in 0.60s`.  The new contract asserts that the
exact `.pytest-ci` root is removed with `if: always()` before `Repository
secret scan`; it does not permit ignoring arbitrary missing paths.

## Change

- `.github/workflows/ci.yml`: add an unconditional `rm -rf -- .pytest-ci`
  step after Python/frontend tests and before all Secret-scan steps.
- `tests/unit/test_task20_final_delivery_contract.py`: bind that lifecycle and
  ordering contract.

## Verification

- Focused delivery/audit suites:
  `.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py tests\unit\test_engineering_audit.py -q --basetemp tmp\task23-ci-focused-postformat`
  -> exit `0`, `101 passed in 14.53s`.
- Synthetic Secret scan: `scripts\test-secret-scan.ps1` -> exit `0`.
- Real Secret scan after removing only `.pytest-ci`: `scripts\secret-scan.ps1`
  -> exit `0`, `210 tracked/non-ignored files checked`.
- Static checks: Ruff format/check and `mypy src` -> exit `0`, 46 source files.
- Broader host Python regression:
  `.venv\Scripts\python.exe -m pytest -q --basetemp tmp\task23-ci-full -p no:cacheprovider`
  -> `742 passed, 4 skipped, 14 failed in 97.15s`.  The 14 failures are existing
  host-environment integrations/performance tests requiring unavailable
  `ffmpeg`/`ffprobe`; they are outside this CI workflow change and CI installs
  `ffmpeg` before running them.

## Self-review

The cleanup is scoped to the sole deterministic CI pytest root and happens
before the first security gate.  `if: always()` also removes it if pytest
fails, preventing stale files from affecting later diagnostic execution.  No
Secret-scanner detection, candidate enumeration, or fail-closed error handling
was relaxed.  `git diff --check` returned zero.

## Commit

`e64697c8638d9acdbf6af86b7323c356a358b411` — `fix: clean CI pytest temp root`.

## Concerns

The full Windows-host suite cannot be completely green without `ffmpeg` and
`ffprobe`; the focused changed boundary, static checks, and both Secret scans
are green.  Remote GitHub execution is not performed here and must be rerun by
the owning workflow after this commit is pushed.

## Fix round 1/5 — cleanup ordering contract

### Review finding and root cause

The first cleanup contract only required `cleanup_index < secret_scan_index`.
It did not require cleanup to occur after the step that creates `.pytest-ci`,
so moving cleanup before pytest would leave the recreated root available to the
Secret scanner and reintroduce the original race.

### Mutation proof and RED

First, the minimal workflow mutation moved `Clean CI pytest temporary root`
immediately before `Unit and integration tests`.  The old contract command

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round1-mutation
```

still returned exit `0`, `9 passed in 0.57s`, proving the original test missed
the bad ordering.  With the stricter assertion added while that same mutation
remained in place, the RED command

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round1-red
```

returned exit `1`, with `assert 7 < 6` for the required strict ordering.

### Change and GREEN

Only `tests/unit/test_task20_final_delivery_contract.py` changed in this
round.  It now asserts exactly one each of the test, cleanup, and repository
scan steps; verifies the test step runs `uv run python -m pytest -q --basetemp
.pytest-ci`; and enforces `test_step_index < cleanup_index <
secret_scan_index`.  The corrected workflow was restored unchanged.

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py tests\unit\test_engineering_audit.py -q --basetemp tmp\task23-ci-round1-final
.venv\Scripts\python.exe -m ruff format --check src tests
.venv\Scripts\python.exe -m ruff check tests\unit\test_task20_final_delivery_contract.py
git diff --check
```

Observed: exit `0`; `101 passed in 14.80s`; 86 files formatted; Ruff clean;
no whitespace errors.

### Commit

`44f2ecdc646f73ca23e00decd012bcba77add1a5` — `test: enforce CI pytest cleanup ordering`.

### Concerns

The same host `ffmpeg`/`ffprobe` limitation remains outside this test-only
round; no remote CI run or push was performed.

## Fix round 2/5 — container harness process exit and Node24 Actions

### Remote evidence and root cause

GitHub run `31584247546`, job `94074238583` passed all preceding quality gates,
including the new pytest-root cleanup and both Secret scans.  Its container
cleanup step printed `Container pytest synthetic cleanup tests passed.` but the
step process returned exit `1`.

The synthetic runner deliberately invokes a fake `docker rm --force` that
returns `23`, and correctly proves that `container-pytest.ps1` surfaces that
cleanup failure.  The harness catches that expected nonzero result, but left
`$LASTEXITCODE=1` from the nested PowerShell invocation.  A `-File` child can
mask this under local Windows PowerShell, while a parent that subsequently
exits `$LASTEXITCODE` demonstrates the leaked state cross-shell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\test-container-pytest.ps1'; exit `$LASTEXITCODE"
```

Before the fix it printed the success line and returned exit `1`.

### TDD RED → GREEN

New process-boundary test
`test_container_pytest_synthetic_harness_exits_zero_after_expected_failure_mutation`
uses an independent `pwsh`/`powershell.exe` child and explicitly exits its
post-script `$LASTEXITCODE`.  RED:

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round2-red
```

Observed exit `1`: the harness printed its passed line and the test observed
child return code `1`.  The minimal production-harness fix sets
`$global:LASTEXITCODE = 0` only after all expected failure assertions and
residue checks have passed.  Unexpected fake-Docker cleanup failure still
throws before that point.  GREEN:

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round2-green
```

Observed exit `0`, `10 passed in 2.50s`; direct synthetic script execution
also returned `0` with its passed line.

### Node20 deprecation compatibility migration

The remote Node20 warning was not the exit-1 root cause above.  Separately,
the GitHub-official Node24-capable majors were adopted without changing the
application runtimes or enabling an unsafe fallback:

- all checkout steps: `actions/checkout@v7` (3 occurrences);
- all Python setup steps: `actions/setup-python@v6` (2 occurrences);
- all Node setup steps: `actions/setup-node@v6` (2 occurrences);
- retained `python-version: 3.12.13` and `node-version: 22.23.0`;
- no `ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION` setting.

The new CI contract test was RED against the old `@v4`/`@v5` workflow:

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round2-actions-red
```

Observed exit `1`, expected zero `actions/checkout@v7` occurrences.  It now
parses every workflow step, requires the exact counts and forbids every older
major or unsafe fallback.

### Final verification

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py tests\unit\test_engineering_audit.py -q --basetemp tmp\task23-ci-round2-actions-final
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\test-container-pytest.ps1
.venv\Scripts\python.exe -m ruff format --check src tests
.venv\Scripts\python.exe -m ruff check tests\unit\test_task20_final_delivery_contract.py
git diff --check
```

Observed exit `0`: `103 passed in 16.79s`; synthetic cleanup passed with exit
`0`; 86 files formatted; Ruff clean; no diff whitespace errors.  A complete
occurrence scan found only the action majors above and no unsafe fallback.

### Commit

`1fdb2a2ca0cf98abd5e8c463799a118cb94978ee` — `fix: stabilize CI cleanup harness`.

### Concerns

Remote GitHub CI has not yet rerun these two fixes.  The pre-existing host
`ffmpeg`/`ffprobe` limitation remains outside the changed CI-harness and action
compatibility boundaries.

## Fix round 3/5 — Buildx Docker exporter and artifact action

### Remote evidence and root cause

GitHub run `31586197390` completed `quality` and `e2e`. Distribution job
`94081478061` failed in `Validate and build both non-root images` after 0.5s:
`Docker exporter is not supported for the docker driver`. The workflow needs
the `type=docker,...,dest=...tar` exporter to preserve release tar identity,
Trivy input, and subsequent security evidence. The runner defaulted to the
incompatible Docker driver and no Buildx setup action had selected the
docker-container-capable builder.

### TDD RED → GREEN

New contract `test_distribution_uses_buildx_and_node24_artifact_without_weakening_evidence`
parses the distribution job. RED:

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round3-red
```

Observed exit `1`: zero `docker/setup-buildx-action@v4` occurrences (and the
workflow still referenced `actions/upload-artifact@v4`). The minimal workflow
change adds exactly one `docker/setup-buildx-action@v4` directly after the
distribution checkout and before the first `docker buildx build`, retaining
the action default docker-container driver. It also upgrades the retained
evidence action to `actions/upload-artifact@v7`.

The contract asserts unique permitted majors and strict checkout → Buildx →
build → artifact order; rejects any old Buildx/artifact major; and protects
both exact `type=docker` tar destination fragments, release identity record,
and the artifact evidence path. It does not permit deleting or weakening the
tar/exporter security chain.

### Final verification

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py tests\unit\test_engineering_audit.py -q --basetemp tmp\task23-ci-round3-final3
.venv\Scripts\python.exe -m ruff format --check src tests
.venv\Scripts\python.exe -m ruff check tests\unit\test_task20_final_delivery_contract.py
git diff --check
```

Observed exit `0`: `104 passed in 16.75s`; 86 files formatted; Ruff clean;
no whitespace errors. Local `docker buildx ls` showed only `docker`-driver
builders, matching the incompatible remote default, so no local rebuild or
new builder was created. The workflow action supplies the required
docker-container builder in CI.

### Commit

`8ca991aaac22319b0f2946bf17592977a32e445d` — `fix: configure CI Buildx exporter`.

### Concerns

Remote distribution must rerun to exercise the Buildx action on the GitHub
runner. The host remains unsuitable for a full image rebuild under the
available builder/cache boundary.

## Fix round 4/5 — explicit active docker-container Buildx configuration

### Review finding and mutation proof

The round-3 contract verified Buildx action presence and ordering but not its
effective builder selection. A minimal workflow mutation added:

```yaml
with:
  driver: docker
  use: false
```

This recreates the Docker-exporter incompatibility but the old direct contract
still returned exit `0`, `12 passed in 2.43s`, proving the configuration was
not bound.

### TDD RED → GREEN

The contract now reads the unique Buildx step and requires parsed YAML values
`with.driver == "docker-container"` and `with.use is True` (unquoted YAML
`true` is a boolean). With the bad mutation still applied:

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round4-red
```

returned exit `1`, expected `docker-container` but observed `docker`. The
workflow was then minimally restored to its explicit active configuration:

```yaml
- uses: docker/setup-buildx-action@v4
  with:
    driver: docker-container
    use: true
```

No tar exporter, release identity, vulnerability evidence, or artifact-chain
configuration changed.

### Final verification

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py tests\unit\test_engineering_audit.py -q --basetemp tmp\task23-ci-round4-final
.venv\Scripts\python.exe -m ruff format --check src tests
.venv\Scripts\python.exe -m ruff check tests\unit\test_task20_final_delivery_contract.py
git diff --check
```

Observed exit `0`: `104 passed in 16.32s`; 86 files formatted; Ruff clean; no
whitespace errors.

### Commit

`887aa9485fb548e624023bb3a7e820120e1bb0cb` — `fix: select CI Buildx container driver`.

### Concerns

Remote distribution still needs to execute this explicit Buildx configuration.
The host has no docker-container builder/cache suitable for a local full image
rebuild.

## Fix round 5/5 — cross-platform container-contract fake commands

### Remote evidence and root cause

Run `31589466440` reached distribution after quality, E2E, Buildx, and both
image build/load gates succeeded. `scripts/test-container-contract.ps1` then
failed at line 191 in job `94091811091`: Linux pwsh attempted to open the
fixture's `/tmp/.../fake-bin/docker.cmd` through `xdg-open`, ending with
`Cannot run a document in the middle of a pipeline`.

The synthetic contract unconditionally created Windows `.cmd` fake Docker and
curl commands, then passed their explicit paths to `container-smoke.ps1`.
Unlike the established `test-container-pytest.ps1` convention, it had no Unix
executable path. That fixture defect is independent of the production smoke
and did not represent a valid failure-path assertion.

### TDD RED → GREEN

The new delivery contract binds the exact cross-platform fixture contract:
platform detection, Windows `docker.cmd`/`curl.cmd`, Unix `docker`/`curl`,
UTF-8-without-BOM fixture writes, `chmod 700` on both Unix commands, and fake
bin PATH precedence. RED:

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round5-red
```

Observed exit `1`: the old harness had no `$isWindowsPlatform` branch. The
minimal fixture-only repair now selects `.cmd` files and the existing batch
fakes on Windows; on Unix it writes LF shell scripts with shebangs, equivalent
fake Docker identity/mutation responses and curl JSON responses, then requires
both files to become executable. All existing wrong-tag, swapped-manifest,
duplicate-identity, and running-image-drift checks remain unchanged and still
fail closed.

### Final verification

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round5-green
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\test-container-contract.ps1
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py tests\unit\test_engineering_audit.py -q --basetemp tmp\task23-ci-round5-related
.venv\Scripts\python.exe -m ruff format --check src tests
.venv\Scripts\python.exe -m ruff check tests\unit\test_task20_final_delivery_contract.py
git diff --check
```

Observed exit `0`: direct contract `13 passed in 2.33s`; synthetic container
contract passed; combined suite `105 passed in 17.74s`; 86 files formatted;
Ruff clean; no whitespace errors.

This Windows host has no `pwsh` binary and no cached Linux PowerShell image,
so the exact Linux pwsh execution cannot be locally rerun without installing
or pulling a tool. It is intentionally left for the next GitHub distribution
run rather than substituted with a claimed local Linux result.

### Commit

`bfc05529dff83013d9c8f3d2e88c5fcf737f11e8` — `fix: support Unix container contract fixtures`.

### Concerns

Remote distribution must rerun the Unix fake-command branch. The host remains
unsuitable for an independent Linux pwsh execution or full image rebuild.

## Fix round 6/10 — container-contract successful harness exit status

### Remote evidence and root cause

GitHub run `31591331876` completed quality, E2E, Buildx, and both image builds
successfully. Its Linux production Compose contract ran every synthetic probe
and printed `Container contract synthetic tests passed.`, then the step exited
`1`. The final `runtime-drift` probe intentionally launches a child PowerShell
process that exits nonzero; its expected failure is asserted, but the child
leaves `$LASTEXITCODE=1` in the harness process. The subsequent success line
does not reset that state, so a caller that exits `$LASTEXITCODE` reports a
failure despite every contract assertion passing.

### TDD RED → GREEN

New real process-boundary regression
`test_container_contract_synthetic_harness_exits_zero_after_expected_failure_mutation`
invokes `pwsh`/`powershell.exe` independently with:

```powershell
& '.\scripts\test-container-contract.ps1'; exit $LASTEXITCODE
```

RED:

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round6-red
```

Observed exit `1`: the child output contained `Container contract synthetic
tests passed.` but the new test observed return code `1`. The minimal harness
repair sets `$global:LASTEXITCODE = 0` immediately after all successful
assertions and the success message. It is deliberately before no cleanup or
mutation change: any assertion or `finally` cleanup exception still terminates
the harness nonzero, and all wrong-tag, swapped-manifest, duplicate-identity,
and runtime-drift expected-failure assertions remain fail-closed.

### Final verification

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round6-green-final
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\test-container-contract.ps1'; exit `$LASTEXITCODE"
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py tests\unit\test_engineering_audit.py -q --basetemp tmp\task23-ci-round6-final
.venv\Scripts\python.exe -m ruff format --check src tests
.venv\Scripts\python.exe -m ruff check tests\unit\test_task20_final_delivery_contract.py
git diff --check
```

Observed exit `0`: independent contract regression `14 passed in 16.12s`;
direct harness printed the success line and returned zero; delivery plus
engineering contracts `106 passed in 30.89s`; 86 files formatted; Ruff clean;
and no whitespace errors.

### Commit

`d2012766e76bd70bd53116977393bc19fef23689` —
`fix: preserve container contract success exit`. No push was performed.

### Concerns

The direct confirmation used this Windows host's `powershell.exe`; the next
GitHub Linux distribution run remains the required remote confirmation of the
same pwsh boundary. No mutations or assertions were relaxed.

## Fix round 7/10 — cross-platform documented development-smoke curl selection

### Root cause

GitHub Actions run `31594559058`, job `94108022926`, showed both development
images building and both development services reaching healthy before the
documented same-origin smoke failed at `scripts/development-smoke.ps1:36`.
The script defaulted `CurlCommand` to `curl.exe`; Ubuntu PowerShell cannot
resolve that Windows executable. The preceding Node 20 deprecation notice is
unrelated. Explicit `-CurlCommand` values must remain supported for synthetic
tests and callers.

### TDD RED → GREEN

The regression is behavioral: a new delivery-contract test launches
`test-development-smoke.ps1` as a child PowerShell process. The lifecycle
harness creates a controlled Linux-semantics default-command child: it makes
`curl.exe` throw, removes the Windows `curl` alias, sets `OS=Linux`, and runs
the copied smoke without `-CurlCommand`. Thus the test only passes when the
smoke chooses an executable `curl` default. It also preserves the existing
explicit-injection lifecycle probes.

Initial RED, before the production default changed:

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round7-red-linux-default
```

returned exit `1`, `1 failed, 14 passed`: the harness reported `Linux curl
command was not selected`, proving a Linux default attempted `curl.exe`.

The minimal production change selects `curl.exe` only when
`$env:OS -eq 'Windows_NT'`, otherwise `curl`. The harness was also completed
for its already-required Ubuntu execution: both fake Docker and explicitly
injected fake curl use Unix shell scripts with UTF-8-without-BOM content and
`chmod 700` on non-Windows. No health, frontend, cleanup, or explicit-command
assertions were weakened.

### GREEN and verification

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\test-development-smoke.ps1'; if ($?) { exit 0 } else { exit 1 }"
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round7-green-focused
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py tests\unit\test_engineering_audit.py -q --basetemp tmp\task23-ci-round7-related
.venv\Scripts\python.exe -m ruff format --check src tests
.venv\Scripts\python.exe -m ruff check tests\unit\test_task20_final_delivery_contract.py
git diff --check
```

Observed before the final formatting-only pass: lifecycle harness exit `0` and
printed its success line; focused contract `15 passed in 23.35s`; related
delivery/engineering contracts `107 passed in 38.28s`; Ruff check clean; and
`git diff --check` clean. The focused test was additionally observed GREEN
after the production selection change.

### Concerns

This Windows host has Windows PowerShell but no local `pwsh`, so the exact
GitHub Ubuntu pwsh process remains the remote confirmation. The Unix fixture
files are now shebang-based and executable by construction; no dependencies
were installed or downloaded.

### Takeover verification and fixture correction

The interrupted implementation was independently reviewed in the
`audit/23-engineering` worktree before committing. The production change was
temporarily reversed to the previous literal `curl.exe` default while retaining
the new behavioral regression. This observed RED:

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round7-takeover-red
```

returned exit `1`, `1 failed, 14 passed in 19.10s`. The failing real
process-boundary test reported `Linux curl command was not selected`: its
child bootstrap aliases `curl.exe` to a throwing function, removes any
PowerShell `curl` alias when present, sets `OS=Linux`, and invokes the copied
smoke without `-CurlCommand`. This demonstrates the old Linux behavior, rather
than grepping the production source.

The platform selection was restored. During takeover review, the Unix fake
Docker script's log format was confirmed and retained as POSIX
`printf '%s\\n'`, so each compose invocation produces a physical line for the
existing partial-up and cleanup failure assertions. The Unix fake Docker and
curl fixtures use shebang shell scripts, UTF-8 without a BOM, LF-normalized
contents, and `chmod 700`; Windows retains `.cmd` fixtures. The harness's
partial-start cleanup, cleanup-only error, combined error, health response,
frontend response, and explicit `-CurlCommand` injection assertions remain
unchanged.

Fresh focused GREEN:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\test-development-smoke.ps1'; if ($?) { exit 0 } else { exit 1 }"
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round7-takeover-green-focused
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py tests\unit\test_engineering_audit.py -q --basetemp tmp\task23-ci-round7-takeover-related
.venv\Scripts\python.exe -m ruff format --check tests\unit\test_task20_final_delivery_contract.py
.venv\Scripts\python.exe -m ruff check tests\unit\test_task20_final_delivery_contract.py
git diff --check
```

Observed exit `0`: lifecycle harness printed its success line; focused
delivery contract `15 passed in 24.24s`; related delivery and engineering
contracts `107 passed in 37.53s`; Ruff format/check clean; and no diff
whitespace errors. This host's WSL Ubuntu installation has `/bin/sh`, `chmod`,
and `curl` but no `pwsh`; therefore the exact Unix PowerShell fixture
execution remains remote CI confirmation and is not claimed as locally run.

### Follow-up: successful lifecycle harness exit status

Review found that the final `combinedFailure` probe intentionally observes a
nonzero child process. Although its failure assertions passed and the harness
printed its success line, that probe left `$LASTEXITCODE=1`; therefore a CI
caller using `& scripts/test-development-smoke.ps1; exit $LASTEXITCODE` could
still fail. A new real process-boundary regression
`test_development_smoke_synthetic_harness_exits_zero_after_expected_failures`
uses that exact command.

RED:

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round7-exit-red
```

Observed exit `1`, `1 failed, 15 passed in 31.05s`: the test captured
`Development smoke synthetic lifecycle tests passed.` with child return code
`1`. The minimal repair assigns `$global:LASTEXITCODE = 0` immediately after
the final success message, after all lifecycle assertions. It cannot mask an
assertion or `finally` cleanup exception, which still terminates the harness.

Historical report rounds 1–6 were force-added along with round 7 because the
plan directory is ignored; the full existing report was intentionally retained
as audit evidence. This follow-up reordered the already-recorded round 6 ahead
of round 7 without dropping or changing that evidence.

Final follow-up GREEN:

`powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\test-development-smoke.ps1'; exit $LASTEXITCODE"
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round7-exit-green
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py tests\unit\test_engineering_audit.py -q --basetemp tmp\task23-ci-round7-exit-related
.venv\Scripts\python.exe -m ruff format --check tests\unit\test_task20_final_delivery_contract.py
.venv\Scripts\python.exe -m ruff check tests\unit\test_task20_final_delivery_contract.py
git diff --check
`

Observed prior to formatting the newly added Python test: the direct lifecycle
process returned exit 0 and printed its success line; focused contract 16
passed in 31.04s; and related delivery/engineering contracts 108 passed in
45.26s. Ruff then reported the new test required formatting; it was formatted,
and fresh Ruff format/check plus git diff --check exited 0. The preceding
focused/related test results exercised the same final PowerShell change; no
production behavior changed during formatting.

## Fix round 8/10 — Linux PowerShell cleanup-error formatting

### Remote RED and root cause

GitHub Actions run `31601188608`, quality job `94128717977`, ran the complete
suite under Ubuntu PowerShell and reported exactly two new development-smoke
behavioral failures. The synthetic cleanup-only probe itself was correct: it
printed the cleanup-only marker, identified Docker Compose down, retained exit
code `29`, and did not report an HTTPS API-health primary failure. PowerShell
had inserted line wrapping and location records between `exit` and `code 29`,
however, while the harness required the single contiguous text
`docker compose down failed with exit code 29`. Windows formatting had kept
that phrase contiguous.

### TDD RED → GREEN

The focused local regression adds a formatter-boundary mode only to the
existing behavioral probe: after the real copied smoke emits its cleanup-only
failure, it inserts the Linux-style location record between `exit` and
`code 29`. No production smoke text, fake command behavior, cleanup behavior,
or primary failure path is changed.

RED:

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round8-red
```

Observed exit `1`, `2 failed, 14 passed`: the lifecycle probe contained every
required cleanup fact but threw `development smoke did not isolate
cleanup-only failure` because the exact contiguous phrase was absent.

The assertion now requires the existing cleanup marker and accepts only
whitespace/newline or PowerShell location-format records between `exit` and
the exact `code 29`. The no-API-primary-failure requirement remains unchanged;
the combined-failure probe retains its required API-primary assertion and uses
the same exact cleanup-code matcher.

GREEN:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\test-development-smoke.ps1'; exit $LASTEXITCODE"
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round8-green
```

Observed exit `0`: lifecycle harness printed its success line; focused
delivery contract `16 passed in 30.74s`.

### Final verification and self-review

The change is assertion-only and retains exact cleanup identification, Docker
Compose-down context, exit code `29`, and both cleanup-only/combined primary
failure boundaries. It does not change `development-smoke.ps1`, curl platform
selection, Unix/Windows fixtures, fake command exits, or process-exit reset.
Remote Ubuntu PowerShell remains the authoritative confirmation; no tool was
downloaded and no push was performed.

### Review follow-up — exact cleanup exit-code boundary

Review correctly identified that the formatting-tolerant matcher ended at
`code 29` without a numeric boundary, so `code 290` or `code 291` could satisfy
it. The defect was confined to the round-8 assertion, not the production smoke
or fake Docker exit behavior.

The behavioral harness now takes a formatter-mode cleanup exit-code value. It
first runs the real copied smoke failure and then formats the resulting output
as the Linux location boundary. A new `290` probe rejects the harness if that
output matches the cleanup-code assertion; it does not inspect source text or
use a change detector.

RED:

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round8-exact-code-red
```

Observed exit `1`, `2 failed, 14 passed`: the probe raised
`development smoke accepted cleanup exit code other than 29`, with the
formatted `code 290` output captured in both affected real process-boundary
contracts.

The minimal fix adds `(?!\d)` immediately after `29`. It retains the complete
formatter-tolerant prefix and rejects every decimal continuation of the exact
required exit code.

GREEN:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\test-development-smoke.ps1'; exit $LASTEXITCODE"
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round8-exact-code-green
```

Observed exit `0`: lifecycle harness printed its success line; focused
delivery contract `16 passed in 32.78s`.

## Fix round 9/10 — ANSI SGR-normalized smoke assertions

### Root cause

GitHub Actions run `31603816007`, quality job `94137540206`, again failed only
the two development-smoke behavioral checks on Ubuntu/pwsh. The captured
cleanup-only error record carried the required cleanup category, Compose-down
context, and exact exit code `29`, but PowerShell inserted ANSI SGR bytes
(`ESC[31;1m` and `ESC[0m`) around and between those tokens. Round 8's matcher
accepts whitespace and location records but cannot traverse those raw control
bytes. The existing `(?!\d)` boundary remains necessary to reject `290`.

### TDD RED → GREEN

The regression extends the real copied-smoke lifecycle probe. After that child
emits its cleanup-only error, the fixture inserts literal ANSI SGR escapes
around `docker`, `compose down failed with exit`, and `code 29`; the existing
location-format fixture remains in place. It also applies the same ANSI
formatting to the `290` rejection probe. This exercises captured output rather
than grepping implementation text, and diagnostics continue to emit the
unmodified captured output.

RED on the pre-fix matcher:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\test-development-smoke.ps1'; exit $LASTEXITCODE"
```

Observed exit `1`: `development smoke did not isolate cleanup-only failure`.
The diagnostic contained the original ANSI-decorated cleanup error record,
including `docker compose down failed with exit`, the PowerShell location
record, and `code 29`; this proves the matcher, not the smoke failure behavior,
was the failing boundary.

The minimal repair derives `SemanticOutput` from captured output by removing
only ANSI SGR sequences (`ESC[` followed by decimal/semicolon parameters and
`m`) and applies the existing cleanup category and exact-code matcher to that
copy. `Output` remains untouched for failure diagnostics. Cleanup-only,
combined API-primary-plus-cleanup, exit-failure, and exact-`29`/reject-`290`
assertions remain fail closed.

GREEN:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\test-development-smoke.ps1'; exit $LASTEXITCODE"
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round9-green-focused
```

Observed exit `0`: the lifecycle harness printed its success line; the focused
delivery-contract suite reported `16 passed in 33.24s`.

### Final verification and self-review

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py tests\unit\test_engineering_audit.py -q --basetemp tmp\task23-ci-round9-related
.venv\Scripts\python.exe -m ruff format --check tests\unit\test_task20_final_delivery_contract.py
.venv\Scripts\python.exe -m ruff check tests\unit\test_task20_final_delivery_contract.py
git diff --check
```

Observed exit `0`: related contracts reported `108 passed in 47.74s`; Ruff
format/check and diff whitespace validation were clean. PowerShell parser
validation also reported `0 errors`. No product smoke script, fake Docker
behavior, or error-reporting diagnostics changed.

### Commit

Recorded with this round's local commit; no push was performed.

### Concerns

The local host runs Windows PowerShell rather than the remote Ubuntu `pwsh`, so
the remote runner remains the authoritative environment confirmation. Ruff is
not a PowerShell formatter and reports expected `invalid-syntax` if pointed at
the `.ps1` fixture; Python Ruff checks were clean and the PowerShell parser plus
behavioral lifecycle harness were run instead.

## Fix round 10/10 — semantic cleanup facts across pwsh continuation gutters

### Root cause

GitHub Actions run `31606620285`, quality job `94147088414`, still failed the
two development-smoke behavioral tests after ANSI normalization. The captured
child output preserved all required cleanup facts, but Linux `pwsh` inserted
its visual continuation gutter between the Compose failure category and exit
code: `docker compose down failed with exit`, followed by a newline and
`      | code 29`. The previous single bridging regex enumerated
human-oriented rendering fragments and rejected `|`; its architecture coupled
semantic requirements to presentation details.

### TDD RED → GREEN

The existing real process-boundary fixture now transforms the copied smoke's
actual cleanup output into the remote gutter shape, and applies the same
formatter shape to the `290` rejection probe. This is behavioral coverage: the
harness invokes the copied smoke child, captures its output, then verifies the
observable cleanup contract rather than searching source text.

RED, before replacing the coupled bridge assertion:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\test-development-smoke.ps1'; exit $LASTEXITCODE"
```

Observed exit `1`, with `development smoke did not isolate cleanup-only
failure`. Diagnostics showed the real child error with ANSI-decorated
`docker compose down failed with exit`, then `      | code 29`; the old matcher
rejected the gutter despite the cleanup marker, Compose-down category, exact
code, and absence of the API-health primary failure.

The minimal correction keeps raw `Output` for diagnostics and checks the
ANSI-stripped `SemanticOutput` as independent facts: cleanup-only marker;
Compose-down-with-exit category; exact numeric `code 29` with digit
boundaries; and no API-health primary failure. The combined failure continues
to require its API-health primary category plus the Compose-down category and
exact `29`. The `290` probe remains an explicit rejection. No product smoke,
curl selection, fake-command exit behavior, cleanup mechanics, or process-exit
handling changed.

GREEN:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\test-development-smoke.ps1'; exit $LASTEXITCODE"
```

Observed exit `0`: `Development smoke synthetic lifecycle tests passed.` The
gutter-formatted cleanup-only, combined-failure, and `290` rejection probes all
completed within this lifecycle harness. PowerShell parser validation reported
zero errors in the same invocation.

### Final verification and self-review

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round10-focused
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py tests\unit\test_engineering_audit.py -q --basetemp tmp\task23-ci-round10-related
.venv\Scripts\python.exe -m ruff format --check tests\unit\test_task20_final_delivery_contract.py
.venv\Scripts\python.exe -m ruff check tests\unit\test_task20_final_delivery_contract.py
git diff --check
```

Observed exit `0`: focused delivery contracts `16 passed in 34.11s`; related
delivery plus engineering contracts `108 passed in 47.63s`; Ruff format
reported `1 file already formatted`; Ruff check reported `All checks passed!`;
and `git diff --check` was clean. The PowerShell lifecycle harness and parser
check also exited `0` after the production change.

### Commit

Recorded with this round's local commit; no push was performed.

### Concerns

The local host supplies Windows PowerShell, not Ubuntu `pwsh`; the remote
runner remains the authoritative confirmation of the precise formatter output.
No further implementation round is authorized by this task.

## Fix round 11/15 — explicit combined API-failure curl state

### Remote symptom and root cause

GitHub Actions run `31608709397` showed that the remaining combined-failure
failure was a fixture state error, not another PowerShell rendering variant.
The product smoke now correctly defaults to `curl` on Linux. Because the
synthetic fake bin is first on `PATH`, an omitted curl argument resolved the
successful fake curl. The `combinedFailure` probe therefore had successful API
health/frontend checks, printed the product success line, and only failed the
Compose cleanup with exit `29`; the harness nevertheless expected an API
primary failure. Windows had accidentally hidden this because its prior default
resolved outside the fake bin.

### Scenario-table self-review

| Probe | Docker state | Curl state | Expected primary | Expected cleanup | Result |
| --- | --- | --- | --- | --- | --- |
| `partialUp` | `up-fail` | not reached | Compose start | none | retained |
| `defaultCurl` | success | platform default resolves fake success | none | none | retained |
| `cleanupOnly` | `down-fail` | explicit fake success | none | exact 29 | retained |
| `wrongCleanupExitCode` | `down-fail` | explicit fake success, formatted as 290 | none | 290 rejected | retained |
| `combinedFailure` | `down-fail` | explicit fake failure | API health | exact 29 | corrected |

The harness saves/restores the new curl-mode environment variable. Every
success, cleanup-only, API-primary-plus-cleanup, exact-code boundary, and
formatter-normalization path remains exercised through a copied product smoke
child; this is not a source-text assertion.

### Behavioral TDD RED -> GREEN

RED changed only `combinedFailure` to request the wished-for `-FailingCurl`
state, before adding that interface or fake behavior:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\test-development-smoke.ps1'; exit $LASTEXITCODE"
```

Observed exit `1` with `A parameter cannot be found that matches parameter
name 'FailingCurl'`. The failure occurred at the real lifecycle process
boundary and proves the combined test no longer depends on platform command
resolution.

GREEN adds only an explicit `MUSEECHO_FAKE_CURL_MODE` state to the harness.
`Invoke-SmokeProbe` rejects conflicting success/failure requests, passes the
fake curl path explicitly for either requested state, and restores the prior
environment afterwards. Both fixture forms obey it: Windows batch exits
stable nonzero `17`; Unix shell prints a diagnostic and exits `17`. The
combined probe requests failure, requires API-health primary plus Compose-down
and exact `29`, and rejects the product success line.

### Final verification

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\test-development-smoke.ps1'; exit $LASTEXITCODE"
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round11-focused
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py tests\unit\test_engineering_audit.py -q --basetemp tmp\task23-ci-round11-related
.venv\Scripts\python.exe -m ruff format --check tests\unit\test_task20_final_delivery_contract.py
.venv\Scripts\python.exe -m ruff check tests\unit\test_task20_final_delivery_contract.py
git diff --check
```

Observed: lifecycle child exit `0` with `Development smoke synthetic lifecycle
tests passed.`; focused delivery contracts `16 passed in 29.27s`; related
delivery plus engineering contracts `108 passed in 43.09s`; Ruff format/check,
PowerShell parser (`0` errors), and diff whitespace validation all exited `0`.

### Commit

Recorded with this round's local commit; no push was performed.

### Concerns

The local host verifies the Windows batch fixture and PowerShell process
boundary. Ubuntu `pwsh` remains the remote authority for execution of the Unix
shell fixture; its behavior is intentionally specified by executable fixture
content rather than a platform-dependent omitted command.

## Fix round 12/15 — structured child outcome protocol

### Root cause and architecture

GitHub run `31611183962` proved round 11's combined state contract: explicit
fake curl failure produced the API primary, Compose cleanup failure, exact code
29, and no product success. The parent still derived those facts from the
rendered `ErrorRecord`; Ubuntu `pwsh` may insert visual gutters between
otherwise-adjacent terms. That renderer is not a machine protocol.

Every real copied-product-smoke child now runs through one PowerShell wrapper.
On success it writes the unique `MUSEECHO_SMOKE_PROBE:SUCCESS` marker and exits
zero. On a terminating error it catches in the child, UTF-8/Base64 encodes only
`Exception.Message` after `MUSEECHO_SMOKE_PROBE:EXCEPTION_MESSAGE_BASE64:`, and
exits nonzero. The parent retains raw `Output` solely for thrown diagnostics,
requires exactly one marker, binds marker kind to exit status, requires
canonical valid Base64 and nonempty strict-UTF8 message, and exposes only
`ExceptionMessage` for failure semantics. Explicit self-checks fail closed for
missing and duplicate markers, malformed or empty Base64 payloads, unknown or
success-with-payload marker forms, and both status/payload inconsistencies
(success marker with nonzero exit; failure payload with zero exit).

The ANSI SGR removal, location/gutter formatting mutations, `SemanticOutput`,
and bridging regex were removed. The cleanup exact-code assertion remains
independently bounded by `(?<!\\d)code 29(?!\\d)`. Its explicit 290 rejection is
now derived from the stable exception message, not a terminal-format mutation.

### Behavioral TDD

RED changed the real lifecycle assertions to the wished-for
`ExceptionMessage` before the wrapper existed:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\test-development-smoke.ps1'; exit $LASTEXITCODE"
```

Observed exit `1`: `development smoke did not preserve the partial-up failure`.
The diagnostics contained PowerShell-rendered ErrorRecord text while the new
field was absent, demonstrating that the old process boundary supplied only
`Output`.

GREEN adds the wrapper/decoder protocol and fail-closed invalid-marker probes.
The same lifecycle command then exited `0` and printed `Development smoke
synthetic lifecycle tests passed.`

### State table and verification

| Probe | Expected result |
| --- | --- |
| `partialUp` | start primary, cleanup performed, no cleanup failure |
| `defaultCurl` | platform-default fake curl success and product success |
| `cleanupOnly` | cleanup/Compose exact 29 only; no API primary |
| `wrongCleanupExitCode` | stable-message 290 mutation rejected |
| `combinedFailure` | explicit fake curl API primary plus cleanup exact 29; no product success |

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\test-development-smoke.ps1'; exit $LASTEXITCODE"
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py -q --basetemp tmp\task23-ci-round12-focused
.venv\Scripts\python.exe -m pytest tests\unit\test_task20_final_delivery_contract.py tests\unit\test_engineering_audit.py -q --basetemp tmp\task23-ci-round12-related
.venv\Scripts\python.exe -m ruff format --check tests\unit\test_task20_final_delivery_contract.py
.venv\Scripts\python.exe -m ruff check tests\unit\test_task20_final_delivery_contract.py
# PowerShell parser and git diff --check
```

Observed: lifecycle harness plus parser exited `0` (`0 parser errors`); focused
contracts `16 passed in 26.36s`; related contracts `108 passed in 40.97s`;
Ruff format/check and diff whitespace validation exited `0`.

### Self-review and concerns

All failing scenario assertions inspect decoded `ExceptionMessage`; raw output
appears only in diagnostics. The wrapper continues to invoke copied product
smoke across a real PowerShell child boundary, preserves round-11 explicit curl
state and environment restoration, and deletes its exact task-temp fixture.
Windows PowerShell was the local host; Ubuntu `pwsh` remains remote authority,
but rendering differences are no longer protocol input. No product smoke,
workflow, runtime version, or unrelated file changed.

### Commit

Recorded with this round's local commit; no push performed.
