# Tencent Cloud deployment evidence

## Status

No public URL is claimed. No Tencent Cloud account, Lighthouse instance,
domain/DNS control, or SSH authorization was available for Task 21. Therefore
this file records only local script evidence and the real-server evidence that
remains pending; it is not a public-deployment completion claim.

## Local evidence

- The delivery scripts are contract-tested in a disposable filesystem root
  with command doubles. These tests exercise digest rejection, no-mutation
  check-only mode, idempotent owned-path install, firewall/systemd invocation,
  atomic health-failure rollback, backup exclusion, and integrity metadata.
- `install.sh --check-only` is designed to check Linux, capacity, disk budget,
  Docker/Compose, curl, systemd, and deployment bundle assumptions without
  creating paths, secrets, firewall rules, unit files, or containers.
- No secret values or cloud-provider credentials were used in local evidence.

### Mandatory ShellCheck gate (local, 2026-08-11)

The already-present official image was run without pulling, network access, or
host-tool installation. Exact image identity:

```text
koalaman/shellcheck-alpine:v0.10.0@sha256:7c6a5115899d99323b22fc84b29e924aef5b6fa985612e450a8c356969ebb577
```

Raw offline `shellcheck --version` command and output (exit 0):

```powershell
docker run --pull=never --rm --network none --entrypoint shellcheck koalaman/shellcheck-alpine:v0.10.0@sha256:7c6a5115899d99323b22fc84b29e924aef5b6fa985612e450a8c356969ebb577 --version
```

```text
ShellCheck - shell script analysis tool
version: 0.10.0
license: GNU General Public License, version 3
website: https://www.shellcheck.net
```

Offline lint command and result:

```powershell
docker run --pull=never --rm --network none --entrypoint shellcheck -v "$PWD:/work:ro" -w /work koalaman/shellcheck-alpine:v0.10.0@sha256:7c6a5115899d99323b22fc84b29e924aef5b6fa985612e450a8c356969ebb577 deploy/tencent-cloud/lib.sh deploy/tencent-cloud/install.sh deploy/tencent-cloud/deploy.sh deploy/tencent-cloud/rollback.sh deploy/tencent-cloud/backup.sh
```

The lint exit 0. stdout/stderr were empty.

## Pending real-server evidence

After authorization, record the UTC timestamp, exact digest references, and
redacted command result for each item below. Do not record secret values.

1. Confirm Lighthouse region, capacity, disk, current system updates, Docker
   and Compose versions; run `install.sh --check-only` then `install.sh`.
2. Confirm only TCP 22/80/443 are reachable in both Lighthouse security groups
   and the host firewall. Confirm a key-authenticated SSH session survives
   before disabling password authentication.
3. Publish or obtain the exact app and gateway OCI digests, deploy them with
   `deploy.sh`, and record the health response through the trusted domain
   certificate (without `--insecure`).
4. From at least two mainland networks where available, perform a real legal
   WAV/MP3 upload, wait for analysis, play a range, ask a question, delete the
   result, and confirm the 24-hour cleanup schedule with timestamped evidence.
5. Run `backup.sh`, validate its `SHA256SUMS`, restore it in an isolated
   environment, then deploy a known-good prior release and document the
   automatic and manual rollback health checks.

The absent authorization is an external delivery gate, not a reason to claim
that local implementation or review has been blocked.
