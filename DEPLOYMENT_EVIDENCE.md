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
