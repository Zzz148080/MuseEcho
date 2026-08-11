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

## ShellCheck constraint

ShellCheck is not installed in WSL. An attempt to query the manifest for the
single allowed official, version/digest-pinned ShellCheck container timed out
before it returned a digest. No container or host tool was downloaded or run.
This report therefore does **not** claim a ShellCheck pass; `bash -n` and the
behavioral contract suite were run instead.

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
- ShellCheck was unavailable and its allowed pinned-container discovery timed
  out. This is a verification gap, not a claimed green gate.
- The existing Task 20 remote CI status remains unrun.

## Commit

- `1bc9f724124cbc0a6769fea8a72b4c9fb9dbf660` —
  `ops: deploy verified Tencent Cloud release` (delivery implementation).
