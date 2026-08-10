from __future__ import annotations

import argparse
import hashlib
import json
import re
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

    allowed_licenses_value = policy.get("allowed_licenses")
    if not isinstance(allowed_licenses_value, list) or not all(
        isinstance(item, str) and item for item in allowed_licenses_value
    ):
        return ["license policy error: allowed_licenses must be a string array"]
    allowed_licenses = set(allowed_licenses_value)

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
        elif license_name not in allowed_licenses:
            findings.append(
                "python policy license is not allowed: "
                f"{name}@{locked_python[name]} uses {license_name}"
            )

    allowed_npm = policy.get("npm_allowed_licenses")
    if not isinstance(allowed_npm, list) or not all(
        isinstance(item, str) and item for item in allowed_npm
    ):
        findings.append("license policy error: npm_allowed_licenses must be a string array")
        allowed_npm_set: set[str] = set()
    else:
        allowed_npm_set = set(allowed_npm)
        for license_name in sorted(allowed_npm_set - allowed_licenses):
            findings.append(f"npm allowed license is not in policy set: {license_name}")

    npm_lock_sha256 = policy.get("npm_lock_sha256")
    if not isinstance(npm_lock_sha256, dict):
        findings.append("license policy error: npm_lock_sha256 must be an object")
        npm_lock_sha256 = {}

    for relative_path in (Path("package-lock.json"), Path("frontend/package-lock.json")):
        try:
            lock_path = repository_root / relative_path
            lock_bytes = lock_path.read_bytes()
            lock = json.loads(lock_bytes)
            if not isinstance(lock, dict):
                raise ValueError(f"{lock_path} must contain a JSON object")
        except (OSError, ValueError) as error:
            findings.append(f"{relative_path.as_posix()}: cannot read lockfile: {error}")
            continue
        expected_digest = npm_lock_sha256.get(relative_path.as_posix())
        actual_digest = hashlib.sha256(lock_bytes).hexdigest()
        if expected_digest != actual_digest:
            findings.append(
                f"npm inventory mismatch: {relative_path.as_posix()} sha256 "
                f"{actual_digest}, policy {expected_digest or '?'}"
            )
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

    distribution_policy = policy.get("distribution")
    if not isinstance(distribution_policy, dict):
        findings.append("license policy error: distribution must be an object")
        return findings
    try:
        distribution_inventory = _distribution_inventory(repository_root)
    except OSError as error:
        findings.append(f"distribution inventory input error: {error}")
        return findings
    _audit_distribution(
        distribution_inventory,
        distribution_policy,
        allowed_licenses,
        findings,
    )
    return findings


def _distribution_inventory(repository_root: Path) -> dict[str, dict[str, str | None]]:
    dockerfile = (repository_root / "Dockerfile").read_text(encoding="utf-8")
    gitlab = (repository_root / ".gitlab-ci.yml").read_text(encoding="utf-8")
    github = (repository_root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    normalized_dockerfile = re.sub(r"\\\r?\n", " ", dockerfile)

    images = set(re.findall(r"(?m)^FROM\s+(\S+)", dockerfile))
    images.update(
        match.group(1).strip("\"'")
        for match in re.finditer(
            r"(?m)^\s+(?:-\s+)?(?:image:|name:)\s+([^\s#]+)\s*$",
            gitlab,
        )
        if ":" in match.group(1)
    )
    images.update(re.findall(r"\b(aquasec/trivy:[\w.-]+)\s+image\b", github))

    build_tools: set[str] = set()
    build_tools.update(
        f"uv@{version}" for version in re.findall(r"\buv==([\w.-]+)", normalized_dockerfile)
    )
    build_tools.update(
        f"xcaddy@{version}"
        for version in re.findall(r"xcaddy/cmd/xcaddy@([^\s;]+)", normalized_dockerfile)
    )
    build_tools.update(
        f"caddy@{version}"
        for version in re.findall(r"\bxcaddy\s+build\s+([^\s;]+)", normalized_dockerfile)
    )

    go_replacements = {
        f"{module}@{version}"
        for module, version in re.findall(
            r"--replace\s+([^=\s]+)=\1@([^\s;]+)", normalized_dockerfile
        )
    }

    debian_packages: set[str] = set()
    for match in re.finditer(
        r"apt-get\b.*?\binstall\s+--yes\s+--no-install-recommends\s+([^;]+);",
        normalized_dockerfile,
    ):
        debian_packages.update(
            token for token in match.group(1).split() if not token.startswith("-")
        )
    alpine_packages: set[str] = set()
    for match in re.finditer(
        r"\bapk\s+(?:add|upgrade)\s+--no-cache\s+([^;&\r\n]+)",
        normalized_dockerfile,
    ):
        alpine_packages.update(
            token for token in match.group(1).split() if not token.startswith("-")
        )

    return {
        "container_images": {item: None for item in sorted(images)},
        "build_tools": {item: None for item in sorted(build_tools)},
        "go_module_replacements": {item: None for item in sorted(go_replacements)},
        "system_packages.debian": {item: None for item in sorted(debian_packages)},
        "system_packages.alpine": {item: None for item in sorted(alpine_packages)},
    }


def _audit_distribution(
    actual: dict[str, dict[str, str | None]],
    policy: dict[str, Any],
    allowed_licenses: set[str],
    findings: list[str],
) -> None:
    system_packages = policy.get("system_packages")
    expected_sections: dict[str, Any] = {
        "container_images": policy.get("container_images"),
        "build_tools": policy.get("build_tools"),
        "go_module_replacements": policy.get("go_module_replacements"),
        "system_packages.debian": (
            system_packages.get("debian") if isinstance(system_packages, dict) else None
        ),
        "system_packages.alpine": (
            system_packages.get("alpine") if isinstance(system_packages, dict) else None
        ),
    }
    for section_name, expected_value in expected_sections.items():
        if not isinstance(expected_value, dict):
            findings.append(f"license policy error: distribution {section_name} must be an object")
            continue
        expected = set(expected_value)
        observed = set(actual[section_name])
        missing = sorted(expected - observed)
        unexpected = sorted(observed - expected)
        if missing or unexpected:
            findings.append(
                f"distribution {section_name} inventory mismatch: "
                f"missing [{', '.join(missing)}]; unexpected [{', '.join(unexpected)}]"
            )
        for identity, license_name in sorted(expected_value.items()):
            if not isinstance(license_name, str) or not license_name:
                findings.append(f"distribution {section_name} has no reviewed license: {identity}")
            elif license_name not in allowed_licenses:
                findings.append(
                    f"distribution {section_name} license is not allowed: "
                    f"{identity} uses {license_name}"
                )


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
    print(
        "License audit passed: Python, npm, container, build-tool, Go-module, "
        "and OS-package inventories match reviewed policy."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
