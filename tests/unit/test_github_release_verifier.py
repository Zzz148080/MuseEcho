from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

from scripts import verify_github_release as release_verifier

ROOT = Path(__file__).resolve().parents[2]
VERIFIER = ROOT / "scripts" / "verify_github_release.py"
TARGET_SHA = "d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1"
PUBLISHED_AT = "2026-08-17T05:54:50Z"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_fake_runtime_zip(path: Path) -> None:
    runtime = """[CmdletBinding()]
param(
    [ValidateSet('Verify', 'Smoke')][string]$Action,
    [string]$ArtifactDirectory
)
$ErrorActionPreference = 'Stop'
foreach ($name in @(
    'museecho-app.tar',
    'museecho-gateway.tar',
    'compose.yaml',
    'release-images.json'
)) {
    if (-not (Test-Path -LiteralPath (Join-Path $ArtifactDirectory $name) -PathType Leaf)) {
        throw "fixture runtime missing $name"
    }
}
Add-Content -LiteralPath $env:MUSEECHO_RECEIVER_LOG -Value $Action
Write-Output "fixture receiver $Action passed"
"""
    entries = {
        "offline-runtime.ps1": runtime,
        "compose.yaml": "services: {}\n",
        "release-images.json": '{"schema_version":1,"images":{}}\n',
        "README.md": "fixture\n",
        "release-version.txt": "v0.1.0\n",
        "scripts/container-smoke.ps1": "Write-Output fixture\n",
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


def _asset_record(path: Path) -> dict[str, object]:
    return {"name": path.name, "size": path.stat().st_size, "sha256": _sha256(path)}


def _fixture(tmp_path: Path) -> dict[str, Any]:
    source = tmp_path / "download-source"
    source.mkdir()
    (source / "museecho-app.tar").write_bytes(b"fixture-app-tar\0")
    (source / "museecho-gateway.tar").write_bytes(b"fixture-gateway-tar\0")
    _write_fake_runtime_zip(source / "museecho-offline-runtime-v0.1.0.zip")
    payload_names = (
        "museecho-app.tar",
        "museecho-gateway.tar",
        "museecho-offline-runtime-v0.1.0.zip",
    )
    checksums = "".join(f"{_sha256(source / name)}  {name}\n" for name in payload_names)
    (source / "SHA256SUMS.txt").write_text(checksums, encoding="ascii", newline="\n")

    assets = [_asset_record(source / name) for name in (*payload_names, "SHA256SUMS.txt")]
    manifest = {
        "schema_version": 1,
        "repository": "Zzz148080/MuseEcho",
        "tag": "v0.1.0",
        "target_commit": TARGET_SHA,
        "main_ci_run": 31997390847,
        "published_at": PUBLISHED_AT,
        "release_url": "https://github.com/Zzz148080/MuseEcho/releases/tag/v0.1.0",
        "assets": assets,
        "provenance": {
            "mode": "local-rebuild-from-exact-main-commit",
            "source_commit": TARGET_SHA,
            "main_ci_run": 31997390847,
            "ci_distribution_passed": True,
            "ci_artifact_retained": False,
            "retention_failure": "GitHub Actions artifact quota skipped the upload step",
            "authorization": (
                "user-directed automatic execution through successful formal Release publication"
            ),
            "published_bytes_identity_checksum_smoke_verified": True,
            "byte_equality_with_unretained_ci_output_claimed": False,
        },
    }
    manifest_path = tmp_path / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    release_assets = [
        {
            "name": item["name"],
            "size": item["size"],
            "digest": f"sha256:{item['sha256']}",
        }
        for item in assets
    ]
    state = {
        "download_source": str(source),
        "release": {
            "tagName": "v0.1.0",
            "targetCommitish": TARGET_SHA,
            "isDraft": False,
            "isPrerelease": False,
            "publishedAt": PUBLISHED_AT,
            "url": manifest["release_url"],
            "assets": release_assets,
        },
        "ref": {"object": {"type": "tag", "sha": "a" * 40}},
        "tag_object": {"object": {"type": "commit", "sha": TARGET_SHA}},
        "run": {
            "id": 31997390847,
            "head_sha": TARGET_SHA,
            "head_branch": "main",
            "status": "completed",
            "conclusion": "success",
            "event": "push",
        },
        "jobs": {
            "total_count": 3,
            "jobs": [
                {"name": "quality", "conclusion": "success"},
                {"name": "e2e", "conclusion": "success"},
                {"name": "distribution", "conclusion": "success"},
            ],
        },
        "artifacts": {"total_count": 0, "artifacts": []},
    }
    state_path = tmp_path / "github-state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    fake_gh_py = tmp_path / "fake_gh.py"
    fake_gh_py.write_text(
        """from __future__ import annotations
import json, os, shutil, sys
from pathlib import Path
state = json.loads(Path(os.environ['MUSEECHO_FAKE_GITHUB_STATE']).read_text(encoding='utf-8'))
args = sys.argv[1:]
if args[:2] == ['release', 'view']:
    print(json.dumps(state['release']))
elif args[:2] == ['release', 'download']:
    destination = Path(args[args.index('--dir') + 1])
    destination.mkdir(parents=True, exist_ok=True)
    for source in Path(state['download_source']).iterdir():
        shutil.copy2(source, destination / source.name)
elif args and args[0] == 'api' and '/git/ref/tags/' in args[1]:
    print(json.dumps(state['ref']))
elif args and args[0] == 'api' and '/git/tags/' in args[1]:
    print(json.dumps(state['tag_object']))
elif args and args[0] == 'api' and '/actions/runs/' in args[1] and args[1].endswith('/jobs'):
    print(json.dumps(state['jobs']))
elif args and args[0] == 'api' and '/actions/runs/' in args[1] and args[1].endswith('/artifacts'):
    print(json.dumps(state['artifacts']))
elif args and args[0] == 'api' and '/actions/runs/' in args[1]:
    print(json.dumps(state['run']))
else:
    raise SystemExit('unexpected fake gh invocation: ' + repr(args))
""",
        encoding="utf-8",
    )
    fake_gh_command = [sys.executable, str(fake_gh_py)]

    fake_powershell_py = tmp_path / "fake_powershell.py"
    fake_powershell_py.write_text(
        """from __future__ import annotations
import os, sys
from pathlib import Path
args = sys.argv[1:]
if os.environ.get('MUSEECHO_EXPECT_CLEAN_PSMODULEPATH') == '1':
    if any(name.lower() == 'psmodulepath' for name in os.environ):
        raise SystemExit('receiver inherited a contaminated PSModulePath')
receiver = Path(args[args.index('-File') + 1])
action = args[args.index('-Action') + 1]
artifact = Path(args[args.index('-ArtifactDirectory') + 1])
if not receiver.is_file():
    raise SystemExit('fixture receiver is missing')
for name in ('museecho-app.tar', 'museecho-gateway.tar', 'compose.yaml', 'release-images.json'):
    if not (artifact / name).is_file():
        raise SystemExit('fixture runtime missing ' + name)
with Path(os.environ['MUSEECHO_RECEIVER_LOG']).open('a', encoding='utf-8') as handle:
    handle.write(action + '\\n')
print('fixture receiver ' + action + ' passed')
""",
        encoding="utf-8",
    )
    fake_powershell_command = [sys.executable, str(fake_powershell_py)]

    assets_dir = tmp_path / "assets"
    shutil.copytree(source, assets_dir)
    receiver_log = tmp_path / "receiver.log"
    return {
        "assets": assets_dir,
        "empty_assets": tmp_path / "downloaded-assets",
        "manifest": manifest_path,
        "state": state_path,
        "gh": fake_gh_command,
        "powershell": fake_powershell_command,
        "receiver_log": receiver_log,
    }


def _run_verifier(
    fixture: dict[str, Any],
    *,
    action: str = "Verify",
    assets_key: str = "assets",
    download: bool = False,
    poison_psmodulepath: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["MUSEECHO_FAKE_GITHUB_STATE"] = str(fixture["state"])
    env["MUSEECHO_RECEIVER_LOG"] = str(fixture["receiver_log"])
    if poison_psmodulepath:
        env["PSModulePath"] = "incompatible-powershell-modules"
        env["MUSEECHO_EXPECT_CLEAN_PSMODULEPATH"] = "1"
    command = [
        sys.executable,
        str(VERIFIER),
        "--action",
        action,
        "--manifest",
        str(fixture["manifest"]),
        "--assets-directory",
        str(fixture[assets_key]),
        "--gh-command",
        *fixture["gh"],
        "--powershell-command",
        *fixture["powershell"],
    ]
    if download:
        command.append("--download")
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_release_verifier_entrypoint_exists() -> None:
    assert VERIFIER.is_file(), "real replayable GitHub Release verifier is missing"


def test_verify_and_smoke_run_from_checksum_bound_extracted_directory(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    verified = _run_verifier(fixture)
    assert verified.returncode == 0, verified.stdout + verified.stderr
    assert fixture["receiver_log"].read_text(encoding="utf-8").splitlines() == ["Verify"]

    fixture["receiver_log"].unlink()
    smoked = _run_verifier(fixture, action="Smoke")
    assert smoked.returncode == 0, smoked.stdout + smoked.stderr
    assert fixture["receiver_log"].read_text(encoding="utf-8").splitlines() == [
        "Verify",
        "Smoke",
    ]


def test_receiver_does_not_inherit_ambient_powershell_modules(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    completed = _run_verifier(fixture, poison_psmodulepath=True)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert fixture["receiver_log"].read_text(encoding="utf-8").splitlines() == ["Verify"]


def test_download_mode_fetches_and_verifies_all_four_assets(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    completed = _run_verifier(fixture, assets_key="empty_assets", download=True)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert sorted(path.name for path in fixture["empty_assets"].iterdir()) == [
        "SHA256SUMS.txt",
        "museecho-app.tar",
        "museecho-gateway.tar",
        "museecho-offline-runtime-v0.1.0.zip",
    ]


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        (lambda state: state["release"].__setitem__("tagName", "v0.1.1"), "release tag"),
        (
            lambda state: state["release"].__setitem__("targetCommitish", "b" * 40),
            "target commitish",
        ),
        (lambda state: state["release"].__setitem__("isDraft", True), "draft"),
        (lambda state: state["release"].__setitem__("isPrerelease", True), "prerelease"),
        (
            lambda state: state["release"].__setitem__("publishedAt", "2026-08-17T05:54:51Z"),
            "publication time",
        ),
        (
            lambda state: state["release"].__setitem__("url", "https://example.invalid/release"),
            "release URL",
        ),
        (
            lambda state: state["release"]["assets"][0].__setitem__("name", "wrong.tar"),
            "asset names",
        ),
        (
            lambda state: state["release"]["assets"][0].__setitem__("size", 999),
            "asset size",
        ),
        (
            lambda state: state["release"]["assets"][0].__setitem__("digest", "sha256:" + "0" * 64),
            "asset digest",
        ),
        (
            lambda state: state["tag_object"]["object"].__setitem__("sha", "c" * 40),
            "resolved tag commit",
        ),
    ),
)
def test_remote_release_metadata_mutations_fail_closed(
    tmp_path: Path, mutation, expected: str
) -> None:
    fixture = _fixture(tmp_path)
    state = json.loads(fixture["state"].read_text(encoding="utf-8"))
    mutation(state)
    fixture["state"].write_text(json.dumps(state), encoding="utf-8")

    completed = _run_verifier(fixture)

    assert completed.returncode != 0
    assert expected.lower() in (completed.stdout + completed.stderr).lower()
    assert not fixture["receiver_log"].exists()


@pytest.mark.parametrize(
    ("name", "expected"),
    (
        ("museecho-app.tar", "SHA-256"),
        ("museecho-gateway.tar", "SHA-256"),
        ("museecho-offline-runtime-v0.1.0.zip", "SHA-256"),
        ("SHA256SUMS.txt", "SHA-256"),
    ),
)
def test_each_local_release_asset_mutation_fails_before_receiver(
    tmp_path: Path, name: str, expected: str
) -> None:
    fixture = _fixture(tmp_path)
    with (fixture["assets"] / name).open("ab") as handle:
        handle.write(b"mutation")

    completed = _run_verifier(fixture)

    assert completed.returncode != 0
    assert expected.lower() in (completed.stdout + completed.stderr).lower()
    assert not fixture["receiver_log"].exists()


def test_checksum_manifest_must_bind_the_three_payloads_not_only_itself(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    checksum_path = fixture["assets"] / "SHA256SUMS.txt"
    checksum_path.write_text("0" * 64 + "  museecho-app.tar\n", encoding="ascii")
    manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    checksum_asset = next(item for item in manifest["assets"] if item["name"] == checksum_path.name)
    checksum_asset.update(_asset_record(checksum_path))
    fixture["manifest"].write_text(json.dumps(manifest), encoding="utf-8")
    state = json.loads(fixture["state"].read_text(encoding="utf-8"))
    remote = next(item for item in state["release"]["assets"] if item["name"] == checksum_path.name)
    remote["size"] = checksum_path.stat().st_size
    remote["digest"] = f"sha256:{_sha256(checksum_path)}"
    fixture["state"].write_text(json.dumps(state), encoding="utf-8")

    completed = _run_verifier(fixture)

    assert completed.returncode != 0
    assert "checksum entries" in (completed.stdout + completed.stderr).lower()
    assert not fixture["receiver_log"].exists()


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        (lambda manifest: manifest.__setitem__("main_ci_run", 0), "main_ci_run"),
        (lambda manifest: manifest.__setitem__("main_ci_run", "31997390847"), "main_ci_run"),
        (
            lambda manifest: manifest["provenance"].__setitem__("mode", "ci-artifact"),
            "mode",
        ),
        (
            lambda manifest: manifest["provenance"].__setitem__("source_commit", "b" * 40),
            "source_commit",
        ),
        (
            lambda manifest: manifest["provenance"].__setitem__("main_ci_run", 31997390848),
            "main_ci_run",
        ),
        (
            lambda manifest: manifest["provenance"].__setitem__("ci_distribution_passed", False),
            "ci_distribution_passed",
        ),
        (
            lambda manifest: manifest["provenance"].__setitem__("ci_artifact_retained", True),
            "artifact-retention",
        ),
        (
            lambda manifest: manifest["provenance"].__setitem__("retention_failure", ""),
            "retention_failure",
        ),
        (
            lambda manifest: manifest["provenance"].__setitem__("authorization", ""),
            "authorization",
        ),
        (
            lambda manifest: manifest["provenance"].__setitem__(
                "published_bytes_identity_checksum_smoke_verified", False
            ),
            "published-byte",
        ),
        (
            lambda manifest: manifest["provenance"].__setitem__(
                "byte_equality_with_unretained_ci_output_claimed", True
            ),
            "CI byte equality",
        ),
    ),
)
def test_core_provenance_mutations_fail_before_receiver(
    tmp_path: Path, mutation, expected: str
) -> None:
    fixture = _fixture(tmp_path)
    manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    mutation(manifest)
    fixture["manifest"].write_text(json.dumps(manifest), encoding="utf-8")

    completed = _run_verifier(fixture)

    assert completed.returncode != 0
    assert expected.lower() in (completed.stdout + completed.stderr).lower()
    assert not fixture["receiver_log"].exists()


def test_coordinated_main_ci_run_mutation_fails_against_github(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    manifest["main_ci_run"] = 31997390848
    manifest["provenance"]["main_ci_run"] = 31997390848
    fixture["manifest"].write_text(json.dumps(manifest), encoding="utf-8")

    completed = _run_verifier(fixture)

    assert completed.returncode != 0
    assert "CI run ID" in completed.stdout + completed.stderr
    assert not fixture["receiver_log"].exists()


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        (lambda state: state["run"].__setitem__("head_sha", "b" * 40), "CI head SHA"),
        (lambda state: state["run"].__setitem__("head_branch", "feat/forged"), "CI branch"),
        (lambda state: state["run"].__setitem__("status", "in_progress"), "CI run status"),
        (lambda state: state["run"].__setitem__("conclusion", "failure"), "CI conclusion"),
        (lambda state: state["run"].__setitem__("event", "workflow_dispatch"), "CI event"),
        (
            lambda state: state["jobs"]["jobs"][2].__setitem__("conclusion", "failure"),
            "CI job distribution",
        ),
        (
            lambda state: state["artifacts"].update(
                {"total_count": 1, "artifacts": [{"name": "forged"}]}
            ),
            "CI artifact state",
        ),
    ),
)
def test_remote_ci_provenance_mutations_fail_closed(
    tmp_path: Path, mutation, expected: str
) -> None:
    fixture = _fixture(tmp_path)
    state = json.loads(fixture["state"].read_text(encoding="utf-8"))
    mutation(state)
    fixture["state"].write_text(json.dumps(state), encoding="utf-8")

    completed = _run_verifier(fixture)

    assert completed.returncode != 0
    assert expected.lower() in (completed.stdout + completed.stderr).lower()
    assert not fixture["receiver_log"].exists()


def test_successful_receiver_reports_staging_cleanup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    original_rmtree = shutil.rmtree
    staging_paths: list[Path] = []

    def fail_cleanup(path: Path, *args, **kwargs) -> None:
        staging_paths.append(Path(path))
        raise PermissionError("fixture staging directory is locked")

    monkeypatch.setenv("MUSEECHO_RECEIVER_LOG", str(fixture["receiver_log"]))
    monkeypatch.setattr(release_verifier.shutil, "rmtree", fail_cleanup)
    try:
        with pytest.raises(
            release_verifier.ReleaseVerificationError, match="staging cleanup failed"
        ):
            release_verifier._run_receiver(
                manifest,
                fixture["assets"],
                "Verify",
                fixture["powershell"],
            )
    finally:
        for staging in staging_paths:
            original_rmtree(staging, ignore_errors=True)

    assert fixture["receiver_log"].read_text(encoding="utf-8").splitlines() == ["Verify"]


def test_cleanup_failure_preserves_primary_receiver_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    failing_receiver = tmp_path / "failing_receiver.py"
    failing_receiver.write_text("raise SystemExit(7)\n", encoding="utf-8")
    original_rmtree = shutil.rmtree
    staging_paths: list[Path] = []

    def fail_cleanup(path: Path, *args, **kwargs) -> None:
        staging_paths.append(Path(path))
        raise PermissionError("fixture staging directory is locked")

    monkeypatch.setattr(release_verifier.shutil, "rmtree", fail_cleanup)
    try:
        with pytest.raises(release_verifier.ReleaseVerificationError) as raised:
            release_verifier._run_receiver(
                manifest,
                fixture["assets"],
                "Verify",
                [sys.executable, str(failing_receiver)],
            )
    finally:
        for staging in staging_paths:
            original_rmtree(staging, ignore_errors=True)

    assert "command failed (7)" in str(raised.value)
    assert any("staging cleanup failed" in note for note in getattr(raised.value, "__notes__", ()))
