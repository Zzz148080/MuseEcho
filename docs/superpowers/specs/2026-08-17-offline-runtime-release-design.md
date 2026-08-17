# MuseEcho v0.1.0 Offline Runtime Release Design

## Purpose and approval

The user approved an offline runtime package and instructed Codex to continue
automatically until the formal GitHub Release succeeds. The package must let a
recipient run and verify MuseEcho without downloading container layers or build
dependencies after the Release assets have been downloaded.

This work does **not** claim that the current Dockerfile can be rebuilt from
source with `--network none`. Engineering finding `ENG-010` therefore remains
`BLOCKED` after this Release.

## Release shape

The formal non-prerelease GitHub Release is `v0.1.0`. It contains four assets:

1. `museecho-app.tar`, the exact app image produced and audited by the final
   `main` distribution job;
2. `museecho-gateway.tar`, the exact gateway image produced and audited by that
   same job;
3. `museecho-offline-runtime-v0.1.0.zip`, the recipient-facing runtime kit;
4. `SHA256SUMS.txt`, checksums for both image archives and the runtime kit.

The assets are separate because GitHub limits the size of each Release asset.
The automatically generated source archives remain source distributions and
are not substitutes for the image archives.

## Runtime kit

The zip contains:

- `offline-runtime.ps1`, with `Verify`, `Import`, `Start`, `Smoke`, and `Stop`
  actions;
- `compose.yaml`, containing only runtime image references and no `build`
  sections;
- `release-images.json`, copied from the distribution job and binding the exact
  app/gateway image IDs and tar SHA-256 values;
- `scripts/container-smoke.ps1`, reused from the repository for a real WAV
  upload, completed analysis, restart, persistence, encryption, image identity,
  and cleanup check;
- `README.md` and `release-version.txt`.

`Verify` fails closed on missing files, malformed identity data, invalid image
IDs, or SHA-256 mismatches. `Import` performs verification before `docker load`
and checks that the loaded `museecho-app:local` and
`museecho-gateway:local` IDs equal the manifest. `Start` imports first, creates
an external 32-byte Base64 `audio-kek` only when one does not already exist,
and starts Compose with `--no-build`. The Compose file uses
`pull_policy: never`, loopback-only HTTPS on port 4173, a read-only Secret bind,
read-only root filesystems, dropped capabilities, and persistent encrypted
data. `Stop` preserves the data volume. No routine action deletes volumes.

`Smoke` imports and verifies the images, then runs the existing isolated
container smoke in no-build mode. Its generated Secret, WAV, containers,
network, and volume are temporary and are removed even on failure.

## Maintainer packaging flow

The distribution job remains the single producer of release image tar files.
A PowerShell packaging script receives that job's evidence directory and the
semantic version, verifies the identity manifest against both tars, stages the
runtime kit, builds the zip, and emits `SHA256SUMS.txt`. It does not rebuild or
retag images.

The CI distribution job runs the packaging script only after the existing
image identity, Compose, Secret, license, vulnerability, and VEX gates pass. It
retains both image archives and the generated offline runtime assets in one
short-lived Actions artifact. The formal Release is populated from the final
green `main` run so the published tar bytes are the audited bytes.

## Recipient flow

The recipient downloads all four assets into one directory, extracts the zip
there, starts Docker Desktop, and runs:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\offline-runtime.ps1 -Action Verify
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\offline-runtime.ps1 -Action Smoke
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\offline-runtime.ps1 -Action Start
```

They then open `https://localhost:4173`. Caddy uses a local internal CA, so the
browser may require a localhost-only certificate exception. The optional
third-party model key is not required. To stop while retaining analyses:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\offline-runtime.ps1 -Action Stop
```

## Failure handling

- Missing or modified assets fail before image import.
- A loaded image identity mismatch fails before Compose starts.
- A missing Docker engine or Compose plugin returns the original command
  failure and does not report success.
- Compose never builds or pulls an image in the runtime flow.
- Smoke cleanup reports cleanup failures without hiding the primary failure.
- Release publication stops if the tag target is not the final green `main`
  SHA or if any uploaded asset checksum differs from the local release set.

## Tests and acceptance

The implementation follows TDD. Synthetic PowerShell tests use fake Docker and
small fixture archives to prove fail-closed hashes, identity checks, no-build
startup, no-pull Compose configuration, Secret generation, and volume-
preserving stop behavior. Packaging tests prove deterministic file selection,
manifest verification, zip contents, and checksum emission.

Final acceptance additionally requires:

1. full repository quality gates;
2. real local packaging from the current Docker images or the final CI
   evidence;
3. an isolated no-build smoke that reaches analysis `complete`;
4. PR CI green after retargeting to `main`;
5. merged `main` CI green;
6. a non-draft, non-prerelease GitHub Release `v0.1.0` whose tag targets that
   verified `main` SHA and whose four assets match `SHA256SUMS.txt`;
7. delivery documents updated with the Release URL, tag, SHA, run ID, exact
   distinction between offline runtime and offline source build, and remaining
   student/manual/deployment boundaries.
