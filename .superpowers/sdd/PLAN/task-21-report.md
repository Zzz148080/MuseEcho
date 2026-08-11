# Task 21 — Tencent Cloud delivery report

## Status

`DONE_WITH_CONCERNS`. Local delivery
controls and documentation are implemented and verified. No Tencent Cloud,
registry, DNS, domain, SSH, firewall, or public URL mutation was attempted.

## Approved design decisions

- The Task 20 image identity artifact is a Docker tar/config identity, not a
  registry reference. `deploy.sh` accepts only lowercase digest-qualified
  `name@sha256:<64 hex>` app and gateway inputs, with no tag fallback.
- Production paths remain fixed at `/srv/museecho` and
  `/etc/museecho/secrets`. `MUSEECHO_TEST_ROOT` is a test-only disposable-root
  adapter; real operations require root and preserve the root/GID 10001 modes.
- A release stages under `releases/.stage.*`, contains only non-secret
  compose/Caddy/runtime identity, is marked verified, then replaces `current`
  via same-filesystem symlink rename. Failed restart/health restores the prior
  verified target (or stops the first failed deployment).
- Each release has non-secret `release.env`; systemd uses it so the exact
  digest identity and optional provider settings are coherent. Provider mode
  is disabled by default: all three provider variables are empty unless the
  operator sets the complete trio. No script reads secret content or accepts
  it as an argument.
- Backup archives only SQLite plus non-secret runtime/release metadata and
  include `SHA256SUMS` plus an explicit encryption/recovery boundary. Encrypted
  audio and wrapped-key material are excluded deliberately.

## RED → GREEN evidence

### Initial RED

Before the Task 21 scripts existed, the WSL command sequence exited 127:

```text
bash tests/deploy/test_tencent_cloud.sh  # missing delivery artifacts
shellcheck deploy/tencent-cloud/*.sh     # command not found
bash deploy/tencent-cloud/install.sh --check-only  # script not found
```

The test harness was written before production scripts. It exercises scripts
against a temporary root and fake Docker/systemd/UFW/curl commands, except for
`docker compose config`, which validates the staged compose interpolation.

### Green

Fresh WSL2 command, exit 0:

```bash
cd /mnt/d/*/.worktrees/ops-21-tencent-delivery
bash tests/deploy/test_tencent_cloud.sh
bash deploy/tencent-cloud/install.sh --check-only
for file in deploy/tencent-cloud/*.sh tests/deploy/test_tencent_cloud.sh; do bash -n "$file"; done
```

Result: all eight contract cases passed; the real check-only command reported
Linux, capacity, disk, Docker/Compose, curl, systemd, and bundle assumptions,
then `check-only: no host changes made`.

The green cases cover: syntax/artifacts; check-only no mutation; repeat-install
idempotency, paths/modes/UFW 22/80/443/systemd; tag rejection and no secret
logging/staging; health-failure atomic rollback; default KEK-only compose;
backup exclusion and integrity metadata; and evidence truthfulness.

### Follow-up RED

The first KEK-only compose-config check failed because systemd consumed only
`runtime.env`, which did not supply the staged image variables, while the
generated compose always set a provider secret path. The minimal fix generated
per-release non-secret `release.env`, pointed the unit at it, and made all
provider fields conditional/empty by default. The same focused WSL command
above then passed.

### Regression investigation

A later fresh run failed after adding a production layout precondition: the
temporary test root correctly lacks `/srv` before install. The root cause was
the precondition applying a real-host assumption to the test adapter. The
small correction validates the explicit test root in that mode and retains the
real `/srv` precondition. The next fresh run passed.

## Additional verification

Fresh Windows command, exit 0:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\secret-scan.ps1
git diff --check
```

Result: `Secret scan passed: 193 tracked/non-ignored files checked.` and no
whitespace errors. Remote GitHub Actions/GitLab CI was not run.

## Initial ShellCheck constraint

ShellCheck was not installed in WSL. The initial Docker manifest query timed
out, so the original implementation evidence recorded only `bash -n` and the
behavioral contract suite. Review fix round 1 later completed the bounded
official digest-pinned container run recorded below.

## Files delivered

- `deploy/tencent-cloud/{README.md,lib.sh,install.sh,deploy.sh,rollback.sh,backup.sh,museecho.service}`
- `tests/deploy/test_tencent_cloud.sh`
- `DEPLOYMENT_EVIDENCE.md`
- Root README KEK-only optional-provider diagnostic correction and truthful
  `TASK20_HANDOFF.md`, blocker, agent-log, and reflection entries.

## Self-review

- Confirmed no mutable image reference is accepted and no secret value is read,
  echoed, staged, backed up, or passed as a command-line argument.
- Confirmed `--check-only` performs only prerequisite probes; its test asserts
  no filesystem, UFW, or systemd operation.
- Confirmed real install refuses an unrelated unit, creates owned paths and
  idempotently reapplies modes, and gives SSH hardening guidance without
  editing sshd automatically.
- Confirmed health failures restore only a verified preceding release and
  backup content excludes encrypted audio rather than making recovery claims.
- Confirmed evidence says no public URL and labels all public checks pending.

## External blockers / concerns

- Real Tencent Cloud authorization, a Lighthouse, DNS/domain control, SSH,
  and publishable digest-qualified OCI references are absent. Public HTTPS,
  complete product smoke, cross-mainland testing, 24-hour cleanup observation,
  backup restore, and live rollback remain pending and must be recorded only
  after they occur.
- ShellCheck is covered by the one scoped pinned-container run in review fix
  round 1; it remains unavailable as a host binary by design.
- The existing Task 20 remote CI status remains unrun.

## Commit

- `1bc9f724124cbc0a6769fea8a72b4c9fb9dbf660` —
  `ops: deploy verified Tencent Cloud release` (delivery implementation).

## Review fix round 1/5

### Root-cause verification and RED

The review findings were reproduced before changing production code. Fresh
WSL `bash tests/deploy/test_tencent_cloud.sh` exited 1 with 12 expected
assertion failures: a failed release was still `.verified`; rollback made only
one health request and retained an unhealthy `current`; an archive copied from
an active WAL database lacked `backup_probe`; an existing `8080/tcp ALLOW IN`
rule did not stop pre-install writes; and a one-field provider configuration
still pulled images and switched current.

### GREEN

- Deploy writes `.verified` only after its restart and health request pass.
  Failed activation verifies the restored prior release; if that check fails,
  it clears `current` and stops the owned service.
- Backup uses Python's standard-library SQLite online backup API, verifies
  `PRAGMA integrity_check`, then hashes/archives the resulting standalone
  snapshot. The new test holds committed data in WAL and restores both `ok`
  and `committed-in-wal` from the archive.
- Install audits active UFW/default deny-or-reject and numbered ALLOW IN rules
  before writes. A non-22/80/443 inbound allow fails closed; clean desired
  rules remain idempotent.
- Provider base URL, model, and secret-file setting are now validated as an
  all-empty or all-configured trio before image pull/staging.

Fresh WSL green command, exit 0:

```bash
bash tests/deploy/test_tencent_cloud.sh
bash deploy/tencent-cloud/install.sh --check-only
for file in deploy/tencent-cloud/*.sh tests/deploy/test_tencent_cloud.sh; do bash -n "$file"; done
```

All 11 delivery contract cases passed. Fresh Windows `scripts/secret-scan.ps1`
also passed (194 files), and `git diff --check` exited 0.

### ShellCheck evidence

One official scoped image was resolved and used:

```text
koalaman/shellcheck-alpine:v0.10.0
sha256:7c6a5115899d99323b22fc84b29e924aef5b6fa985612e450a8c356969ebb577
docker pull koalaman/shellcheck-alpine@sha256:7c6a5115899d99323b22fc84b29e924aef5b6fa985612e450a8c356969ebb577
docker run --rm --network none --entrypoint shellcheck -v "$PWD:/work:ro" -w /work koalaman/shellcheck-alpine@sha256:7c6a5115899d99323b22fc84b29e924aef5b6fa985612e450a8c356969ebb577 deploy/tencent-cloud/lib.sh deploy/tencent-cloud/install.sh deploy/tencent-cloud/deploy.sh deploy/tencent-cloud/rollback.sh deploy/tencent-cloud/backup.sh
```

The final offline run against all five delivery scripts exited 0. The first
attempt after the single pull exited 1 because that image's default command is
`/bin/sh`, which tried to execute bash-shebang script paths; `docker image
inspect` identified that root cause and the same image was rerun with its
`shellcheck` entrypoint. No other image or host tool was installed.

## Review fix round 2/5 — pinned ShellCheck evidence

### RED

Before documentation changes, focused command
`bash tests/deploy/test_shellcheck_evidence.sh` exited 1 with 11 expected
evidence-contract failures: `DEPLOYMENT_EVIDENCE.md` had no ShellCheck record,
and this report separated `v0.10.0` from a digest-only image reference without
capturing version output or a lint result.

### GREEN

No new image or tool was downloaded. The existing image was used with the
complete version-and-digest reference:

```text
koalaman/shellcheck-alpine:v0.10.0@sha256:7c6a5115899d99323b22fc84b29e924aef5b6fa985612e450a8c356969ebb577
```

Raw `shellcheck --version` command, exit 0:

The version command exit 0 is recorded with its raw captured stdout below.

```powershell
docker run --pull=never --rm --network none --entrypoint shellcheck koalaman/shellcheck-alpine:v0.10.0@sha256:7c6a5115899d99323b22fc84b29e924aef5b6fa985612e450a8c356969ebb577 --version
```

Captured stdout:

```text
ShellCheck - shell script analysis tool
version: 0.10.0
license: GNU General Public License, version 3
website: https://www.shellcheck.net
```

Offline lint command:

```powershell
docker run --pull=never --rm --network none --entrypoint shellcheck -v "$PWD:/work:ro" -w /work koalaman/shellcheck-alpine:v0.10.0@sha256:7c6a5115899d99323b22fc84b29e924aef5b6fa985612e450a8c356969ebb577 deploy/tencent-cloud/lib.sh deploy/tencent-cloud/install.sh deploy/tencent-cloud/deploy.sh deploy/tencent-cloud/rollback.sh deploy/tencent-cloud/backup.sh
```

The lint exit 0; captured stdout/stderr were empty. The focused evidence contract
now verifies the complete reference, `--network none`, raw version banner and
line, version command, and lint exit in both evidence files.

## Review fix round 3/5 — evidence contract mutations

### RED

The checker was first made to read `MUSEECHO_EVIDENCE_ROOT`, so mutations could
run against task-local temporary evidence copies without changing real records.
Fresh command:

```bash
bash tests/deploy/test_shellcheck_evidence.sh
bash tests/deploy/test_shellcheck_evidence_mutations.sh
```

The unstrengthened checker passed after each required fact was deleted:
`--pull=never` and, separately, each of `lib.sh`, `install.sh`, `deploy.sh`,
`rollback.sh`, and `backup.sh` (six accepted mutations). This reproduced the
review finding. Adding the new assertions then exposed two expected document
failures for the missing explicit `version command exit 0` wording.

### GREEN

The contract now requires in **each** evidence file: complete
`v0.10.0@sha256` reference, `--pull=never`, `--network none`, raw version
banner and version line, `shellcheck --version` plus version-command exit,
lint empty stdout/stderr and exit, and every one of the five script paths.

Fresh mutation output:

```text
PASS: legacy checker accepted missing --pull=never evidence
PASS: rejected mutation: --pull=never
PASS: rejected mutation: deploy/tencent-cloud/lib.sh
PASS: rejected mutation: deploy/tencent-cloud/install.sh
PASS: rejected mutation: deploy/tencent-cloud/deploy.sh
PASS: rejected mutation: deploy/tencent-cloud/rollback.sh
PASS: rejected mutation: deploy/tencent-cloud/backup.sh
ShellCheck evidence mutations rejected.
```

The same cached full tag@digest image was rerun with `--pull=never --network
none` for version and lint; no image pull or production deployment behavior
occurred in this round.

## Review fix round 4/5 — legacy mutation acceptance evidence

### Root cause and focused RED

The round-3 mutation harness created a task-local legacy checker only for the
missing `--pull=never` case. Each of the five script-path mutations called only
`expect_rejected`, so its output proved final-checker rejection but did not run
or prove legacy-checker acceptance.

The missing five legacy calls were added first, while the legacy copy still
retained the script-path assertion loop. Fresh focused commands:

```bash
bash tests/deploy/test_shellcheck_evidence.sh
bash tests/deploy/test_shellcheck_evidence_mutations.sh
```

The evidence checker exited 0. The mutation suite exited 1 with the expected
five focused failures:

```text
FAIL: legacy checker unexpectedly rejected deploy/tencent-cloud/lib.sh mutation
FAIL: legacy checker unexpectedly rejected deploy/tencent-cloud/install.sh mutation
FAIL: legacy checker unexpectedly rejected deploy/tencent-cloud/deploy.sh mutation
FAIL: legacy checker unexpectedly rejected deploy/tencent-cloud/rollback.sh mutation
FAIL: legacy checker unexpectedly rejected deploy/tencent-cloud/backup.sh mutation
5 ShellCheck evidence mutation(s) accepted
```

### GREEN

The minimal harness fix removes the six round-3 guards from its disposable
legacy-checker copy: the `--pull=never` assertion and the script-path assertion
loop. It still mutates only copied evidence under `mktemp`; tracked evidence is
never changed. Each mutation now runs the legacy copy and final checker, with
its exact name visible.

The same two focused commands exited 0 with this output:

```text
ShellCheck evidence contract passed.
PASS: legacy checker accepted missing --pull=never evidence
PASS: rejected mutation: --pull=never
PASS: legacy checker accepted missing deploy/tencent-cloud/lib.sh evidence
PASS: rejected mutation: deploy/tencent-cloud/lib.sh
PASS: legacy checker accepted missing deploy/tencent-cloud/install.sh evidence
PASS: rejected mutation: deploy/tencent-cloud/install.sh
PASS: legacy checker accepted missing deploy/tencent-cloud/deploy.sh evidence
PASS: rejected mutation: deploy/tencent-cloud/deploy.sh
PASS: legacy checker accepted missing deploy/tencent-cloud/rollback.sh evidence
PASS: rejected mutation: deploy/tencent-cloud/rollback.sh
PASS: legacy checker accepted missing deploy/tencent-cloud/backup.sh evidence
PASS: rejected mutation: deploy/tencent-cloud/backup.sh
ShellCheck evidence mutations rejected.
```

### Proportional verification

No image or tool was downloaded. `docker image inspect` confirmed the cached
image ID was the required digest. Version and lint used the complete
tag@digest reference with `--pull=never --network none`:

```powershell
docker run --pull=never --rm --network none --entrypoint shellcheck koalaman/shellcheck-alpine:v0.10.0@sha256:7c6a5115899d99323b22fc84b29e924aef5b6fa985612e450a8c356969ebb577 --version
docker run --pull=never --rm --network none --entrypoint shellcheck -v "$PWD:/work:ro" -w /work koalaman/shellcheck-alpine:v0.10.0@sha256:7c6a5115899d99323b22fc84b29e924aef5b6fa985612e450a8c356969ebb577 deploy/tencent-cloud/lib.sh deploy/tencent-cloud/install.sh deploy/tencent-cloud/deploy.sh deploy/tencent-cloud/rollback.sh deploy/tencent-cloud/backup.sh
```

Both exited 0. Version stdout reported `version: 0.10.0`; lint stdout/stderr
were empty. The remaining fresh gates were:

```bash
bash tests/deploy/test_tencent_cloud.sh
bash deploy/tencent-cloud/install.sh --check-only
for file in deploy/tencent-cloud/*.sh tests/deploy/test_tencent_cloud.sh tests/deploy/test_shellcheck_evidence*.sh; do bash -n "$file"; done
```

All 11 delivery contracts passed; check-only reported no host changes; all
syntax checks exited 0. Windows Secret scan passed for 196 tracked/non-ignored
files, and `git diff --check` exited 0. No production deployment behavior or
real deployment evidence changed.
