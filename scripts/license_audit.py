from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import Any


def audit_repository(repository_root: Path, policy_path: Path) -> list[str]:
    findings: list[str] = []
    try:
        policy = _read_json(policy_path)
        with (repository_root / "uv.lock").open("rb") as stream:
            uv_lock = tomllib.load(stream)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
        return [f"license audit input error: {error}"]

    locked_python = {
        package["name"]: package["version"]
        for package in uv_lock.get("package", [])
        if "name" in package and "version" in package
    }
    python_policy = policy.get("python")
    if not isinstance(python_policy, dict):
        return ["license policy error: python must be an object"]

    for name in sorted(locked_python.keys() - python_policy.keys()):
        findings.append(f"python policy missing: {name}@{locked_python[name]}")
    for name in sorted(python_policy.keys() - locked_python.keys()):
        findings.append(f"python policy stale: {name}@{python_policy[name].get('version', '?')}")
    for name in sorted(locked_python.keys() & python_policy.keys()):
        entry = python_policy[name]
        if not isinstance(entry, dict):
            findings.append(f"python policy invalid: {name} entry must be an object")
            continue
        expected_version = str(entry.get("version", ""))
        if locked_python[name] != expected_version:
            findings.append(
                f"python policy mismatch: {name} locked {locked_python[name]}, "
                f"policy {expected_version or '?'}"
            )
        license_name = str(entry.get("license", "")).strip()
        if not license_name or "UNKNOWN" in license_name.upper():
            findings.append(f"python policy has no reviewed license: {name}@{locked_python[name]}")

    allowed_npm = policy.get("npm_allowed_licenses")
    if not isinstance(allowed_npm, list) or not all(
        isinstance(item, str) and item for item in allowed_npm
    ):
        findings.append("license policy error: npm_allowed_licenses must be a string array")
        allowed_npm_set: set[str] = set()
    else:
        allowed_npm_set = set(allowed_npm)

    for relative_path in (Path("package-lock.json"), Path("frontend/package-lock.json")):
        try:
            lock = _read_json(repository_root / relative_path)
        except (OSError, ValueError) as error:
            findings.append(f"{relative_path.as_posix()}: cannot read lockfile: {error}")
            continue
        packages = lock.get("packages")
        if not isinstance(packages, dict):
            findings.append(f"{relative_path.as_posix()}: packages must be an object")
            continue
        for package_path, package in sorted(packages.items()):
            if not package_path:
                continue
            version = str(package.get("version", "?"))
            license_name = package.get("license")
            if not isinstance(license_name, str) or not license_name.strip():
                findings.append(
                    f"{relative_path.as_posix()}: {package_path}@{version} has no license"
                )
            elif license_name not in allowed_npm_set:
                findings.append(
                    f"{relative_path.as_posix()}: {package_path}@{version} "
                    f"uses unapproved license {license_name}"
                )
    return findings


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit locked dependency licenses")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path(__file__).with_name("license-policy.json"),
    )
    args = parser.parse_args()
    root = args.root.resolve()
    findings = audit_repository(root, args.policy.resolve())
    if findings:
        for finding in findings:
            print(f"ERROR: {finding}", file=sys.stderr)
        return 1
    print("License audit passed: uv.lock and both npm lockfiles match reviewed policy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
