from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, cast
from urllib.parse import quote

PAYLOAD_NAMES = (
    "museecho-app.tar",
    "museecho-gateway.tar",
    "museecho-offline-runtime-v0.1.0.zip",
)
CHECKSUM_NAME = "SHA256SUMS.txt"
EXPECTED_ASSET_NAMES = (*PAYLOAD_NAMES, CHECKSUM_NAME)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_PROVENANCE_MODE = "local-rebuild-from-exact-main-commit"
EXPECTED_AUTHORIZATION = (
    "user-directed automatic execution through successful formal Release publication"
)
EXPECTED_CI_BRANCH = "main"
EXPECTED_CI_EVENT = "push"
EXPECTED_CI_JOBS = ("quality", "e2e", "distribution")


class ReleaseVerificationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(
    command: list[str], *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
    except OSError as exc:
        raise ReleaseVerificationError(f"command could not start: {command[0]}: {exc}") from exc
    if completed.returncode != 0:
        output = (completed.stdout + completed.stderr).strip()
        raise ReleaseVerificationError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n{output}"
        )
    return completed


def _run_json(command: list[str], label: str) -> dict[str, Any]:
    output = _run(command).stdout
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ReleaseVerificationError(f"{label} did not return valid JSON") from exc
    if not isinstance(value, dict):
        raise ReleaseVerificationError(f"{label} must return a JSON object")
    return value


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseVerificationError(f"release manifest is unreadable: {path}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ReleaseVerificationError("release manifest schema mismatch")
    for key in ("repository", "tag", "target_commit", "published_at", "release_url"):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise ReleaseVerificationError(f"release manifest has invalid {key}")
    if not re.fullmatch(r"[0-9a-f]{40}", manifest["target_commit"]):
        raise ReleaseVerificationError("release manifest target_commit is invalid")
    main_ci_run = manifest.get("main_ci_run")
    if type(main_ci_run) is not int or main_ci_run <= 0:
        raise ReleaseVerificationError("release manifest main_ci_run is invalid")
    assets = manifest.get("assets")
    if not isinstance(assets, list):
        raise ReleaseVerificationError("release manifest assets are invalid")
    asset_records: list[dict[str, Any]] = []
    names: list[str] = []
    for item in assets:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ReleaseVerificationError("release manifest asset names are invalid")
        asset_records.append(item)
        names.append(item["name"])
    if len(assets) != 4 or sorted(names) != sorted(EXPECTED_ASSET_NAMES):
        raise ReleaseVerificationError("release manifest asset names are invalid")
    for item in asset_records:
        if not isinstance(item.get("size"), int) or item["size"] < 0:
            raise ReleaseVerificationError(
                f"release manifest asset size is invalid: {item.get('name')}"
            )
        if not isinstance(item.get("sha256"), str) or not SHA256_RE.fullmatch(item["sha256"]):
            raise ReleaseVerificationError(
                f"release manifest asset SHA-256 is invalid: {item.get('name')}"
            )
    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict):
        raise ReleaseVerificationError("release manifest provenance is missing")
    if provenance.get("mode") != EXPECTED_PROVENANCE_MODE:
        raise ReleaseVerificationError("release manifest provenance mode is invalid")
    if provenance.get("source_commit") != manifest["target_commit"]:
        raise ReleaseVerificationError(
            "release manifest provenance source_commit must equal target_commit"
        )
    if (
        type(provenance.get("main_ci_run")) is not int
        or provenance["main_ci_run"] <= 0
        or provenance["main_ci_run"] != main_ci_run
    ):
        raise ReleaseVerificationError(
            "release manifest provenance main_ci_run must equal top-level main_ci_run"
        )
    if provenance.get("ci_distribution_passed") is not True:
        raise ReleaseVerificationError(
            "release manifest provenance ci_distribution_passed must be true"
        )
    if provenance.get("ci_artifact_retained") is not False:
        raise ReleaseVerificationError("release manifest must preserve the artifact-retention fact")
    if (
        not isinstance(provenance.get("retention_failure"), str)
        or not provenance["retention_failure"].strip()
    ):
        raise ReleaseVerificationError("release manifest provenance retention_failure is invalid")
    if provenance.get("authorization") != EXPECTED_AUTHORIZATION:
        raise ReleaseVerificationError("release manifest provenance authorization is invalid")
    if provenance.get("published_bytes_identity_checksum_smoke_verified") is not True:
        raise ReleaseVerificationError(
            "release manifest must bind the published-byte identity/checksum/smoke verification"
        )
    if provenance.get("byte_equality_with_unretained_ci_output_claimed") is not False:
        raise ReleaseVerificationError(
            "release manifest must not claim unavailable CI byte equality"
        )
    return manifest


def _resolve_tag_commit(gh_command: list[str], repository: str, tag: str) -> str:
    encoded_tag = quote(tag, safe="")
    reference = _run_json(
        [*gh_command, "api", f"repos/{repository}/git/ref/tags/{encoded_tag}"],
        "tag reference",
    )
    obj = reference.get("object")
    if not isinstance(obj, dict):
        raise ReleaseVerificationError("tag reference object is missing")
    for _ in range(8):
        object_type = obj.get("type")
        object_sha = obj.get("sha")
        if not isinstance(object_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", object_sha):
            raise ReleaseVerificationError("tag reference SHA is invalid")
        if object_type == "commit":
            return object_sha
        if object_type != "tag":
            raise ReleaseVerificationError(
                f"tag resolves to unsupported object type: {object_type}"
            )
        tag_object = _run_json(
            [*gh_command, "api", f"repos/{repository}/git/tags/{object_sha}"],
            "annotated tag object",
        )
        obj = tag_object.get("object")
        if not isinstance(obj, dict):
            raise ReleaseVerificationError("annotated tag object target is missing")
    raise ReleaseVerificationError("annotated tag chain is too deep")


def _verify_remote_release(manifest: dict[str, Any], gh_command: list[str]) -> None:
    repository = manifest["repository"]
    tag = manifest["tag"]
    release = _run_json(
        [
            *gh_command,
            "release",
            "view",
            tag,
            "--repo",
            repository,
            "--json",
            "tagName,targetCommitish,isDraft,isPrerelease,publishedAt,url,assets",
        ],
        "GitHub Release",
    )
    comparisons = (
        (release.get("tagName"), tag, "release tag"),
        (release.get("targetCommitish"), manifest["target_commit"], "target commitish"),
        (release.get("publishedAt"), manifest["published_at"], "publication time"),
        (release.get("url"), manifest["release_url"], "release URL"),
    )
    for actual, expected, label in comparisons:
        if actual != expected:
            raise ReleaseVerificationError(f"{label} mismatch: {actual!r} != {expected!r}")
    if release.get("isDraft") is not False:
        raise ReleaseVerificationError("release must not be a draft")
    if release.get("isPrerelease") is not False:
        raise ReleaseVerificationError("release must not be a prerelease")

    remote_assets = release.get("assets")
    if not isinstance(remote_assets, list):
        raise ReleaseVerificationError("remote release asset list is invalid")
    expected_assets = cast(list[dict[str, Any]], manifest["assets"])
    expected_by_name = {item["name"]: item for item in expected_assets}
    remote_by_name: dict[str, dict[str, Any]] = {}
    for item in remote_assets:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ReleaseVerificationError("remote release asset names mismatch")
        name = item["name"]
        if name in remote_by_name:
            raise ReleaseVerificationError("remote release asset names mismatch")
        remote_by_name[name] = item
    if len(remote_assets) != 4 or sorted(remote_by_name) != sorted(expected_by_name):
        raise ReleaseVerificationError("remote release asset names mismatch")
    for name, expected in expected_by_name.items():
        actual = remote_by_name[name]
        if actual.get("size") != expected["size"]:
            raise ReleaseVerificationError(f"remote asset size mismatch: {name}")
        if actual.get("digest") != f"sha256:{expected['sha256']}":
            raise ReleaseVerificationError(f"remote asset digest mismatch: {name}")

    resolved = _resolve_tag_commit(gh_command, repository, tag)
    if resolved != manifest["target_commit"]:
        raise ReleaseVerificationError(
            f"resolved tag commit mismatch: {resolved} != {manifest['target_commit']}"
        )


def _verify_remote_ci_run(manifest: dict[str, Any], gh_command: list[str]) -> None:
    repository = manifest["repository"]
    run_id = manifest["main_ci_run"]
    endpoint = f"repos/{repository}/actions/runs/{run_id}"
    run = _run_json([*gh_command, "api", endpoint], "GitHub Actions run")
    comparisons = (
        (run.get("id"), run_id, "CI run ID"),
        (run.get("head_sha"), manifest["target_commit"], "CI head SHA"),
        (run.get("head_branch"), EXPECTED_CI_BRANCH, "CI branch"),
        (run.get("status"), "completed", "CI run status"),
        (run.get("conclusion"), "success", "CI conclusion"),
        (run.get("event"), EXPECTED_CI_EVENT, "CI event"),
    )
    for actual, expected, label in comparisons:
        if actual != expected:
            raise ReleaseVerificationError(f"{label} mismatch: {actual!r} != {expected!r}")

    jobs_response = _run_json([*gh_command, "api", f"{endpoint}/jobs"], "GitHub Actions jobs")
    jobs = jobs_response.get("jobs")
    if not isinstance(jobs, list):
        raise ReleaseVerificationError("CI jobs response is invalid")
    jobs_by_name: dict[str, dict[str, Any]] = {}
    for job in jobs:
        if not isinstance(job, dict) or not isinstance(job.get("name"), str):
            raise ReleaseVerificationError("CI jobs response is invalid")
        name = job["name"]
        if name in jobs_by_name:
            raise ReleaseVerificationError(f"CI job is duplicated: {name}")
        jobs_by_name[name] = job
    for name in EXPECTED_CI_JOBS:
        job = jobs_by_name.get(name)
        if job is None or job.get("conclusion") != "success":
            conclusion = None if job is None else job.get("conclusion")
            raise ReleaseVerificationError(f"CI job {name} did not succeed: {conclusion!r}")

    artifacts_response = _run_json(
        [*gh_command, "api", f"{endpoint}/artifacts"], "GitHub Actions artifacts"
    )
    artifacts = artifacts_response.get("artifacts")
    total_count = artifacts_response.get("total_count")
    if not isinstance(artifacts, list) or type(total_count) is not int:
        raise ReleaseVerificationError("CI artifact response is invalid")
    if total_count != 0 or artifacts:
        raise ReleaseVerificationError(
            f"CI artifact state contradicts the manifest: total_count={total_count}"
        )


def _download_assets(manifest: dict[str, Any], assets_root: Path, gh_command: list[str]) -> None:
    assets_root.mkdir(parents=True, exist_ok=True)
    existing = [name for name in EXPECTED_ASSET_NAMES if (assets_root / name).exists()]
    if existing:
        raise ReleaseVerificationError(
            "download destination already contains release assets: " + ", ".join(existing)
        )
    _run(
        [
            *gh_command,
            "release",
            "download",
            manifest["tag"],
            "--repo",
            manifest["repository"],
            "--dir",
            str(assets_root),
        ]
    )


def _verify_local_assets(manifest: dict[str, Any], assets_root: Path) -> None:
    expected_by_name = {item["name"]: item for item in manifest["assets"]}
    for name in EXPECTED_ASSET_NAMES:
        path = assets_root / name
        if not path.is_file():
            raise ReleaseVerificationError(f"required release asset is missing: {name}")
        expected = expected_by_name[name]
        actual_size = path.stat().st_size
        actual_hash = _sha256(path)
        if actual_size != expected["size"] or actual_hash != expected["sha256"]:
            raise ReleaseVerificationError(
                f"local asset size/SHA-256 mismatch: {name}; "
                f"size={actual_size}; sha256={actual_hash}"
            )

    checksum_lines = (assets_root / CHECKSUM_NAME).read_text(encoding="ascii").splitlines()
    entries: dict[str, str] = {}
    for line in checksum_lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line)
        if match is None or match.group(2) in entries:
            raise ReleaseVerificationError("SHA256SUMS checksum entries are malformed")
        entries[match.group(2)] = match.group(1)
    if sorted(entries) != sorted(PAYLOAD_NAMES):
        raise ReleaseVerificationError("SHA256SUMS checksum entries do not name three payloads")
    for name in PAYLOAD_NAMES:
        if entries[name] != _sha256(assets_root / name):
            raise ReleaseVerificationError(f"SHA256SUMS payload checksum mismatch: {name}")


def _safe_extract(zip_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            relative = PurePosixPath(info.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise ReleaseVerificationError(f"runtime zip contains unsafe path: {info.filename}")
        archive.extractall(destination)


def _run_receiver(
    manifest: dict[str, Any],
    assets_root: Path,
    action: str,
    powershell_command: list[str],
) -> None:
    receiver_env = os.environ.copy()
    for name in tuple(receiver_env):
        if name.lower() == "psmodulepath":
            del receiver_env[name]
    staging = Path(tempfile.mkdtemp(prefix=f".museecho-{manifest['tag']}-", dir=assets_root.parent))
    try:
        _safe_extract(assets_root / "museecho-offline-runtime-v0.1.0.zip", staging)
        for name in ("museecho-app.tar", "museecho-gateway.tar", CHECKSUM_NAME):
            source = assets_root / name
            destination = staging / name
            try:
                os.link(source, destination)
            except OSError:
                shutil.copy2(source, destination)
        receiver = staging / "offline-runtime.ps1"
        if not receiver.is_file():
            raise ReleaseVerificationError("runtime zip is missing offline-runtime.ps1")
        actions = ["Verify"] if action == "Verify" else ["Verify", "Smoke"]
        for receiver_action in actions:
            _run(
                [
                    *powershell_command,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(receiver),
                    "-Action",
                    receiver_action,
                    "-ArtifactDirectory",
                    str(staging),
                ],
                env=receiver_env,
            )
    except Exception as primary_error:
        try:
            shutil.rmtree(staging)
        except OSError as cleanup_error:
            primary_error.add_note(f"receiver staging cleanup failed: {staging}: {cleanup_error}")
        raise
    try:
        shutil.rmtree(staging)
    except OSError as exc:
        raise ReleaseVerificationError(
            f"receiver staging cleanup failed: {staging}: {exc}"
        ) from exc


def verify_release(args: argparse.Namespace) -> None:
    manifest = _load_manifest(args.manifest.resolve())
    assets_root = args.assets_directory.resolve()
    _verify_remote_release(manifest, args.gh_command)
    _verify_remote_ci_run(manifest, args.gh_command)
    if args.download:
        _download_assets(manifest, assets_root, args.gh_command)
    if not assets_root.is_dir():
        raise ReleaseVerificationError(f"assets directory does not exist: {assets_root}")
    _verify_local_assets(manifest, assets_root)
    _run_receiver(manifest, assets_root, args.action, args.powershell_command)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail-closed verification for the formal MuseEcho GitHub Release."
    )
    parser.add_argument("--action", choices=("Verify", "Smoke"), default="Verify")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "release" / "v0.1.0-manifest.json",
    )
    parser.add_argument("--assets-directory", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--gh-command", nargs="+", default=["gh"])
    parser.add_argument("--powershell-command", nargs="+", default=["powershell.exe"])
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        verify_release(_parser().parse_args(argv))
    except ReleaseVerificationError as exc:
        print(f"Release verification failed: {exc}", file=sys.stderr)
        return 1
    print(
        "GitHub Release metadata, CI provenance, tag, assets, checksums, "
        "and receiver actions verified."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
