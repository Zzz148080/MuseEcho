# MuseEcho v0.1.0 Offline Runtime Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a formal `v0.1.0` GitHub Release whose audited app and gateway image archives can be verified, imported, smoked, and run without builds or pulls.

**Architecture:** The existing distribution job remains the image producer and security gate. A small PowerShell receiver script verifies the existing release identity manifest, loads the exact image tars, and starts a runtime-only Compose file; a maintainer script packages those files and checksums without rebuilding images. The final Release is populated only from the green `main` distribution artifact.

**Tech Stack:** PowerShell 7/Windows PowerShell 5.1, Docker Engine/Desktop, Docker Compose v2, GitHub Actions, Python release-identity verifier, Markdown, Git/GitHub Release.

## Global Constraints

- Release version is exactly `v0.1.0`; it is neither draft nor prerelease.
- Runtime assets are `museecho-app.tar`, `museecho-gateway.tar`, `museecho-offline-runtime-v0.1.0.zip`, and `SHA256SUMS.txt`.
- Receiver startup never builds or pulls; Compose uses `pull_policy: never` and every `up` uses `--no-build`.
- Release image bytes come from one green `main` distribution job and retain its `release-images.json` identity.
- The default receiver flow preserves the encrypted data volume and never exposes a volume-deletion switch.
- No third-party model key is required.
- `ENG-010` remains `BLOCKED`: offline runtime is not offline source rebuilding.
- Existing Task 23 evidence remains historical and is not rewritten as current Release evidence.
- `REFLECTION.md` changes are limited to the previously authorized stale GitHub-evidence sentence and objective Release facts; subjective student conclusions are not rewritten.

---

### Task 1: Receiver runtime contract

**Files:**
- Create: `release/offline-runtime/offline-runtime.ps1`
- Create: `release/offline-runtime/compose.yaml`
- Create: `release/offline-runtime/README.md`
- Create: `release/offline-runtime/release-version.txt`
- Create: `scripts/test-offline-runtime.ps1`

**Interfaces:**
- Consumes: `release-images.json`, `museecho-app.tar`, and `museecho-gateway.tar` in one artifact directory.
- Produces: `offline-runtime.ps1 -Action Verify|Import|Start|Smoke|Stop` and a runtime-only Compose project named `museecho-offline`.

- [ ] **Step 1: Write the receiver RED test**

Create a task-temp fixture containing two small archive stand-ins, a literal
schema-v1 release identity, a fake Docker executable, and the real receiver
script. The test must assert observable behavior:

```powershell
$verify = Invoke-Receiver -Action Verify
if ($verify.ExitCode -ne 0) { throw $verify.Output }

$start = Invoke-Receiver -Action Start -SecretsDirectory $secretRoot
if ($start.ExitCode -ne 0) { throw $start.Output }
$dockerLog = Get-Content -Raw -LiteralPath $fakeDockerLog
if ($dockerLog -match '(?m)\b(build|pull)\b') { throw 'offline receiver used network/build path' }
if ($dockerLog -notmatch 'compose .* up .*--no-build') { throw 'offline receiver omitted --no-build' }

$key = [Convert]::FromBase64String((Get-Content -Raw "$secretRoot/audio-kek"))
if ($key.Length -ne 32) { throw 'receiver did not generate a 32-byte KEK' }
```

Add separate fixture runs proving a modified tar fails before any Docker call,
a wrong loaded app image ID fails before Compose, and `Stop` omits `--volumes`.

- [ ] **Step 2: Run the receiver test and verify RED**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-offline-runtime.ps1
```

Expected: non-zero with `offline-runtime.ps1` or its actions missing. The
failure must occur before the fake Docker success path can satisfy assertions.

- [ ] **Step 3: Implement the minimal receiver and Compose runtime**

The receiver validates the manifest and archive hashes before import:

```powershell
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
foreach ($name in @('app', 'gateway')) {
    $entry = $manifest.images.$name
    if ($entry.image_id -notmatch '^sha256:[0-9a-f]{64}$') {
        throw "$name release image id is invalid"
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $tarPaths[$name]).Hash.ToLowerInvariant()
    if ($actual -ne $entry.tar_sha256) { throw "$name release tar SHA-256 mismatch" }
}
```

`Import` runs `docker load --input` for each verified tar and compares
`docker image inspect --format '{{.Id}}'` with the manifest. `Start` creates the
external Secret only if absent, then runs:

```powershell
docker compose --file $composePath --project-name museecho-offline config --quiet
docker compose --file $composePath --project-name museecho-offline up --detach --wait --no-build
```

The Compose file contains no `build` key, uses `pull_policy: never`, binds only
`127.0.0.1:${MUSEECHO_HTTPS_PORT:-4173}:8443`, mounts the Secret directory
read-only, and retains the existing non-root/read-only/cap-drop health boundary.
`Stop` runs `down --remove-orphans` without `--volumes`. `Smoke` imports first
and invokes the bundled `scripts/container-smoke.ps1 -NoBuild` with the current
release manifest.

- [ ] **Step 4: Run receiver GREEN and mutation probes**

Run the same test command. Expected: `Offline runtime synthetic tests passed.`
Then temporarily change the fake app ID and a tar byte through the test's own
fixture modes; each run must fail on its named contract and leave no fixture
residue.

- [ ] **Step 5: Commit Task 1**

```powershell
git add -- release/offline-runtime scripts/test-offline-runtime.ps1
git commit -m "feat: add verified offline runtime loader"
```

---

### Task 2: Current release identity no-build smoke

**Files:**
- Modify: `scripts/container-smoke.ps1`
- Modify: `scripts/test-container-contract.ps1`

**Interfaces:**
- Consumes: legacy Task 23 security manifests or current `release-images.json` manifests.
- Produces: one no-build smoke entrypoint that derives current app/gateway IDs from `images.<name>.image_id` while preserving legacy validation.

- [ ] **Step 1: Add failing current-manifest tests**

Extend the synthetic contract with this literal current manifest:

```powershell
[ordered]@{
    schema_version = 1
    images = [ordered]@{
        app = [ordered]@{ image_id = $appDaemonId; tar_sha256 = ('a' * 64) }
        gateway = [ordered]@{ image_id = $gatewayDaemonId; tar_sha256 = ('b' * 64) }
    }
} | ConvertTo-Json -Depth 4
```

Invoke `container-smoke.ps1 -NoBuild -ReleaseManifest <path>` without the four
legacy expected-ID arguments. Assert success, then mutate one ID to a malformed
value and assert failure before Compose `up`.

- [ ] **Step 2: Verify RED**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-container-contract.ps1
```

Expected: the current manifest fails because the existing smoke requires four
legacy IDs and reads `app.daemon_image_id`.

- [ ] **Step 3: Implement dual-schema identity parsing**

Add one parser that returns the expected daemon IDs. For the current schema it
validates exactly `app` and `gateway`, both lowercase SHA-256 image IDs, and
rejects duplicate IDs. For the legacy schema retain every existing
daemon/config comparison. Only the derived daemon IDs are used for Docker tag
and running-container inspection.

When `-NoBuild` is set, require only `compose.yaml`; retain Dockerfile and
Caddyfile requirements for build-mode smoke. This allows the generated runtime
kit to carry no build inputs.

- [ ] **Step 4: Verify GREEN and legacy compatibility**

Run the contract script. Expected: both legacy and current-manifest paths pass;
wrong tag, swapped identity, duplicate identity, malformed identity, and runtime
drift probes all fail closed inside the harness.

- [ ] **Step 5: Commit Task 2**

```powershell
git add -- scripts/container-smoke.ps1 scripts/test-container-contract.ps1
git commit -m "test: accept audited release identity in no-build smoke"
```

---

### Task 3: Maintainer packaging and CI retention

**Files:**
- Create: `scripts/prepare-offline-release.ps1`
- Create: `scripts/test-prepare-offline-release.ps1`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `-Version 0.1.0`, `-EvidenceDirectory tmp/image-security`, and both audited tar files plus `release-images.json`.
- Produces: `tmp/offline-release/museecho-offline-runtime-v0.1.0.zip` and `tmp/offline-release/SHA256SUMS.txt`.

- [ ] **Step 1: Write packaging RED test**

Use small valid Docker-save fixture tars already supported by
`tests/unit/test_release_identity.py`, or generate literal single-image tar
fixtures in task-temp. Invoke the real packaging script and assert:

```powershell
$zip = Join-Path $output 'museecho-offline-runtime-v0.1.0.zip'
if (-not (Test-Path -LiteralPath $zip -PathType Leaf)) { throw 'runtime zip missing' }
Expand-Archive -LiteralPath $zip -DestinationPath $expanded
$required = @('offline-runtime.ps1','compose.yaml','release-images.json','README.md','release-version.txt','scripts/container-smoke.ps1')
foreach ($path in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $expanded $path))) { throw "zip missing $path" }
}
```

Parse `SHA256SUMS.txt` and independently hash both input tars and the zip.
Mutate the identity manifest tar digest and assert packaging fails without an
output zip.

- [ ] **Step 2: Run packaging test and verify RED**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-prepare-offline-release.ps1
```

Expected: non-zero because the packaging script does not exist.

- [ ] **Step 3: Implement deterministic packaging**

The script validates `Version` against `^\d+\.\d+\.\d+$`, calls the existing
Python identity verifier against both tars, stages only the six specified kit
files, writes `v$Version` with UTF-8 no BOM, creates the zip, and emits sorted
lowercase checksums in this format:

```text
<64 lowercase hex>  museecho-app.tar
<64 lowercase hex>  museecho-gateway.tar
<64 lowercase hex>  museecho-offline-runtime-v0.1.0.zip
```

Task-temp staging is removed in `finally`; output files are replaced only
inside the explicitly resolved output directory.

- [ ] **Step 4: Add packaging gates to CI**

Run both synthetic PowerShell tests in `quality`. In `distribution`, after all
identity/license/vulnerability/VEX gates, run the packaging script and change
the existing retained artifact path to:

```yaml
path: |
  tmp/image-security/
  tmp/offline-release/
```

Keep `continue-on-error` only on evidence retention; packaging itself blocks
the job.

- [ ] **Step 5: Verify GREEN**

Run both PowerShell tests, YAML parse/contract tests, release identity unit
tests, and `git diff --check`. Expected: zero failures and no temp residue.

- [ ] **Step 6: Commit Task 3**

```powershell
git add -- scripts/prepare-offline-release.ps1 scripts/test-prepare-offline-release.ps1 .github/workflows/ci.yml
git commit -m "build: package audited offline runtime assets"
```

---

### Task 4: Pre-release documentation and delivery contracts

**Files:**
- Modify: `README.md`
- Create: `RELEASE_REPRODUCTION.md`
- Modify: `SPEC.md`
- Modify: `PLAN.md`
- Modify: `DECISIONS.md`
- Modify: `AGENT_LOG.md`
- Modify: `BLOCKERS.md`
- Modify: `COURSE_DELIVERY_CHECKLIST.md`
- Modify: `DELIVERY_REPORT.md`
- Modify: `REFLECTION.md`
- Modify: `REFLECTION_NOTES.md`
- Modify as required by existing validators: `docs/audits/FUNCTIONAL_AUDIT.md`
- Modify as required by existing validators: `docs/audits/ENGINEERING_AUDIT.md`
- Test: existing delivery, acceptance, engineering, and final-contract tests

**Interfaces:**
- Consumes: implemented receiver/package behavior and the known Release URL `https://github.com/Zzz148080/MuseEcho/releases/tag/v0.1.0`.
- Produces: consistent wording that distinguishes offline runtime PASS from offline source-build BLOCKED.

- [ ] **Step 1: Write or update failing delivery-contract tests**

Add behavioral document contract assertions only where an existing checker
consumes the documents. The required meaning is:

```text
offline-runtime=RELEASED
offline-source-build=BLOCKED:ENG-010
deployment=NOT_RUN
```

The checker must reject text that deletes `ENG-010`, calls the runtime kit an
offline source build, or claims cloud deployment.

- [ ] **Step 2: Verify documentation RED**

Run focused delivery/acceptance/engineering tests. Expected: failure because
the current documents still say no Release exists and the stale reflection
lines still call final GitHub evidence open.

- [ ] **Step 3: Update the full project timeline**

Document recipient prerequisites, four assets, three receiver commands,
localhost CA warning, retained data behavior, no provider key requirement, and
the exact release boundary. Update status blocks in chronological order. Keep
`MUSEECHO V1 PARTIALLY READY` while student/manual and `ENG-010` gates remain.

In `REFLECTION.md`, replace only the previously authorized stale sentence so
final GitHub evidence is closed by run `31973968704` at SHA `09a51b4...`, while
formal offline source build and student/manual gates remain open. In
`REFLECTION_NOTES.md`, retain run `31687703913` as historical, add final run
`31973968704`, and close only final GitHub evidence. Release evidence is added
as an objective dated note after publication, not as a subjective conclusion.

- [ ] **Step 4: Verify documentation GREEN**

Run the delivery validator, acceptance validator, engineering checker, focused
unit tests, secret scan, and `git diff --check`. Expected: all pass with the
same non-READY boundaries.

- [ ] **Step 5: Commit Task 4**

```powershell
git add -- README.md RELEASE_REPRODUCTION.md SPEC.md PLAN.md DECISIONS.md AGENT_LOG.md BLOCKERS.md COURSE_DELIVERY_CHECKLIST.md DELIVERY_REPORT.md REFLECTION.md REFLECTION_NOTES.md docs/audits
git commit -m "docs: prepare v0.1.0 offline runtime release"
```

---

### Task 5: Full verification, PR integration, and main evidence

**Files:**
- No intended source changes; fixes follow TDD if verification exposes defects.

**Interfaces:**
- Consumes: Tasks 1-4 commits.
- Produces: green feature PR and green merged `main` run whose distribution artifact supplies Release assets.

- [ ] **Step 1: Verify the full branch**

Run the repository's PowerShell verification gates, Python suite, frontend
tests/build, E2E typecheck, container contracts, secret scan, and a real Docker
distribution build. Run the no-build smoke against the produced current
`release-images.json`. Record exact counts, image IDs, tar hashes, and exit
codes.

- [ ] **Step 2: Review the final diff and push**

Confirm no generated tar, zip, key, cache, database, or temporary evidence is
tracked. Push `codex/expand-common-audio-formats` without force.

- [ ] **Step 3: Retarget and complete PR #3**

Retarget PR #3 from `codex/fix-mp3-cover-art` to `main`, inspect the expanded
compare, mark it ready, and wait for `quality`, `e2e`, and `distribution` to
reach successful conclusions on the exact head SHA. Fix any failure through
systematic debugging and TDD, then repeat.

- [ ] **Step 4: Merge and verify main**

Merge PR #3 using the repository's allowed merge method. Wait for the `main`
CI run on the resulting merge SHA to pass all three jobs. Download the
`image-vulnerability-evidence` artifact from this exact run and verify its
release identity and offline assets locally.

---

### Task 6: Publish v0.1.0 and reconcile final evidence

**Files:**
- Create locally for GitHub body: `tmp/release-v0.1.0-notes.md` (never tracked)
- Modify after publication: the Task 4 delivery/status documents that carry current Release evidence

**Interfaces:**
- Consumes: exact green `main` SHA and its downloaded distribution artifact.
- Produces: formal GitHub Release URL, tag, assets, checksums, and post-release documentation commit.

- [ ] **Step 1: Prepare and verify release assets**

Extract the final `main` artifact into task-temp. Verify both tars with
`verify_release_identity.py`, verify every `SHA256SUMS.txt` entry, expand the
runtime zip, and run `offline-runtime.ps1 -Action Smoke` using the downloaded
assets. Confirm the smoke reaches `complete` and cleans up.

- [ ] **Step 2: Create the tag and formal Release**

Create annotated tag `v0.1.0` at the verified `main` SHA. Publish a non-draft,
non-prerelease Release titled `MuseEcho v0.1.0` and upload exactly the four
assets. Release notes begin with recipient reproduction commands and state that
cloud deployment and offline source rebuilding are not included.

- [ ] **Step 3: Verify GitHub publication**

Read the Release back from GitHub. Confirm tag target, published state, asset
names, asset sizes, and downloadable bytes. Re-hash downloaded copies and
compare them to `SHA256SUMS.txt`.

- [ ] **Step 4: Reconcile post-release documents**

Append the exact Release URL, tag target SHA, main CI run ID, publication UTC
time, and asset hashes/sizes to the objective delivery timeline. Preserve
`ENG-010`, deployment, and student/manual boundaries. Commit and push this
documentation-only reconciliation through a PR to `main` if branch protection
requires it.

- [ ] **Step 5: Run final evidence verification**

Wait for the post-release documentation CI to pass. Confirm the GitHub Release
still targets the original audited main SHA, all four assets remain available,
the repository tree contains no generated assets/secrets, and every current
document names the same Release status and remaining blockers.
