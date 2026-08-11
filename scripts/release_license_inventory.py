from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

COMPONENT_KINDS = ("debian", "python", "alpine", "go")


def _canonical_json_digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def parse_apk_installed(contents: str) -> dict[str, dict[str, str]]:
    components: dict[str, dict[str, str]] = {}
    contents = contents.lstrip("\ufeff")
    for raw_record in re.split(r"\r?\n\r?\n", contents.strip()):
        fields: dict[str, str] = {}
        for line in raw_record.splitlines():
            key, separator, value = line.partition(":")
            if separator and key in {"A", "C", "L", "P", "V", "o"}:
                fields[key] = value
        required = {"A", "L", "P", "V"}
        if not required <= set(fields):
            raise ValueError(
                "APK installed record is missing " + ", ".join(sorted(required - set(fields)))
            )
        identity = f"{fields['P']}@{fields['V']}?arch={fields['A']}"
        if identity in components:
            raise ValueError(f"duplicate APK component: {identity}")
        canonical_metadata = "".join(f"{key}:{fields[key]}\n" for key in sorted(fields)).encode()
        components[identity] = {
            "name": fields["P"],
            "version": fields["V"],
            "architecture": fields["A"],
            "source_package": fields.get("o", fields["P"]),
            "upstream_license": fields["L"],
            "metadata_sha256": hashlib.sha256(canonical_metadata).hexdigest(),
        }
    return dict(sorted(components.items()))


def parse_go_version_m(contents: str) -> dict[str, dict[str, str | None]]:
    first_line = contents.lstrip("\ufeff").splitlines()[0] if contents.strip() else ""
    match = re.search(r":\s+(go[0-9][^\s]*)$", first_line)
    if match is None:
        raise ValueError("Go build information has no toolchain version")
    components: dict[str, dict[str, str | None]] = {
        f"stdlib@{match.group(1)}": {
            "module": "stdlib",
            "version": match.group(1),
            "go_sum": None,
        }
    }
    pending: tuple[str, str, str | None] | None = None

    def add(module: str, version: str, go_sum: str | None, replaces: str | None = None) -> None:
        identity = f"{module}@{version}"
        if identity in components:
            raise ValueError(f"duplicate Go component: {identity}")
        entry: dict[str, str | None] = {
            "module": module,
            "version": version,
            "go_sum": go_sum,
        }
        if replaces is not None:
            entry["replaces"] = replaces
        components[identity] = entry

    for raw_line in contents.lstrip("\ufeff").splitlines()[1:]:
        fields = raw_line.strip().split("\t")
        kind = fields[0] if fields else ""
        if kind == "=>" and len(fields) >= 3:
            if pending is None:
                raise ValueError("Go replacement has no preceding dependency")
            original_module, original_version, _ = pending
            add(
                fields[1],
                fields[2],
                fields[3] if len(fields) > 3 and fields[3] else None,
                f"{original_module}@{original_version}",
            )
            pending = None
            continue
        if pending is not None:
            add(*pending)
            pending = None
        if kind == "dep" and len(fields) >= 3:
            pending = (fields[1], fields[2], fields[3] if len(fields) > 3 else None)
    if pending is not None:
        add(*pending)
    return dict(sorted(components.items()))


def _command_output(arguments: list[str]) -> str:
    return subprocess.run(
        arguments,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def read_distribution_metadata(distribution: Any) -> tuple[str, str]:
    for filename in ("METADATA", "PKG-INFO"):
        contents = distribution.read_text(filename)
        if contents is not None:
            return filename, contents
    raise ValueError("installed Python distribution has no METADATA or PKG-INFO")


def build_app_inventory(
    command_output: Callable[[list[str]], str] = _command_output,
) -> dict[str, object]:
    dpkg_output = command_output(
        [
            "dpkg-query",
            "-W",
            "-f=${binary:Package}\t${Version}\t${source:Package}\t${Architecture}\n",
        ]
    )
    debian: dict[str, dict[str, str]] = {}
    for line in dpkg_output.splitlines():
        name, version, source, architecture = line.split("\t")
        canonical_name = name.split(":", 1)[0]
        copyright_path = Path("/usr/share/doc") / canonical_name / "copyright"
        copyright_bytes = copyright_path.read_bytes()
        copyright_text = copyright_bytes.decode("utf-8", errors="replace")
        upstream_license_labels = sorted(
            {
                match.group(1).strip()
                for match in re.finditer(r"(?m)^License:\s*([^\r\n]+)", copyright_text)
                if match.group(1).strip()
            }
        )
        identity = f"{canonical_name}@{version}?arch={architecture}"
        if identity in debian:
            raise ValueError(f"duplicate Debian component: {identity}")
        debian[identity] = {
            "name": canonical_name,
            "version": version,
            "architecture": architecture,
            "source_package": source.split(" ", 1)[0] or canonical_name,
            "license_metadata_path": copyright_path.as_posix(),
            "metadata_sha256": hashlib.sha256(copyright_bytes).hexdigest(),
            "upstream_license_labels": upstream_license_labels,
        }

    python: dict[str, dict[str, object]] = {}
    for distribution in importlib.metadata.distributions():
        display_name = distribution.metadata.get("Name")
        if not display_name:
            raise ValueError("installed Python distribution has no Name metadata")
        name = re.sub(r"[-_.]+", "-", display_name).lower()
        version = distribution.version
        identity = f"{name}@{version}"
        if identity in python:
            raise ValueError(f"duplicate Python component: {identity}")
        metadata_filename, metadata_text = read_distribution_metadata(distribution)
        license_files: dict[str, str] = {}
        for relative_file in distribution.files or []:
            basename = Path(str(relative_file)).name.upper()
            if not basename.startswith(("LICENSE", "COPYING", "NOTICE")):
                continue
            resolved = Path(distribution.locate_file(relative_file))
            if resolved.is_file():
                license_files[str(relative_file).replace("\\", "/")] = hashlib.sha256(
                    resolved.read_bytes()
                ).hexdigest()
        metadata = {
            "metadata_filename": metadata_filename,
            "metadata_sha256": hashlib.sha256(metadata_text.encode()).hexdigest(),
            "license_files": dict(sorted(license_files.items())),
        }
        python[identity] = {
            "name": name,
            "version": version,
            "declared_license": distribution.metadata.get("License-Expression")
            or distribution.metadata.get("License")
            or "",
            "metadata_sha256": _canonical_json_digest(metadata),
        }
    return {
        "schema_version": 1,
        "components": {
            "debian": dict(sorted(debian.items())),
            "python": dict(sorted(python.items())),
        },
    }


def audit_release_inventory(inventory: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    if inventory.get("schema_version") != 1:
        findings.append("release license inventory schema version mismatch")
    if policy.get("schema_version") != 1:
        findings.append("release license policy schema version mismatch")
    allowed_value = policy.get("allowed_licenses")
    if not isinstance(allowed_value, list) or not all(
        isinstance(item, str) and item for item in allowed_value
    ):
        return findings + ["release license policy allowed_licenses must be a string array"]
    allowed = set(allowed_value)
    actual_components = inventory.get("components")
    expected_components = policy.get("components")
    if not isinstance(actual_components, dict) or not isinstance(expected_components, dict):
        return findings + ["release license components must be objects"]
    for kind in COMPONENT_KINDS:
        actual = actual_components.get(kind)
        expected = expected_components.get(kind)
        if not isinstance(actual, dict) or not isinstance(expected, dict):
            findings.append(f"{kind} component inventory must be an object")
            continue
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        if missing or unexpected:
            findings.append(
                f"{kind} component inventory mismatch: missing [{', '.join(missing)}]; "
                f"unexpected [{', '.join(unexpected)}]"
            )
        for identity in sorted(set(actual) & set(expected)):
            actual_entry = actual[identity]
            policy_entry = expected[identity]
            if not isinstance(actual_entry, dict) or not isinstance(policy_entry, dict):
                findings.append(f"{kind} component entry must be an object: {identity}")
                continue
            approved = policy_entry.get("approved_license")
            if not isinstance(approved, str) or approved not in allowed:
                findings.append(
                    f"{kind} component has unapproved license: {identity} uses {approved or '?'}"
                )
            if kind in {"debian", "python", "alpine"} and actual_entry.get(
                "metadata_sha256"
            ) != policy_entry.get("metadata_sha256"):
                findings.append(f"{kind} component metadata mismatch: {identity}")
            if kind == "alpine" and actual_entry.get("upstream_license") != policy_entry.get(
                "upstream_license"
            ):
                findings.append(f"alpine component upstream license mismatch: {identity}")
            if kind == "debian" and actual_entry.get("upstream_license_labels") != policy_entry.get(
                "upstream_license_labels"
            ):
                findings.append(f"debian component upstream license mismatch: {identity}")
            if kind == "python" and actual_entry.get("declared_license") != policy_entry.get(
                "declared_license"
            ):
                findings.append(f"python component upstream license mismatch: {identity}")
            if kind == "go":
                if actual_entry.get("go_sum") != policy_entry.get("go_sum"):
                    findings.append(f"go component sum mismatch: {identity}")
                license_hashes = policy_entry.get("license_files_sha256")
                if (
                    not isinstance(license_hashes, list)
                    or not license_hashes
                    or not all(
                        isinstance(item, str) and re.fullmatch(r"[0-9a-f]{64}", item)
                        for item in license_hashes
                    )
                ):
                    findings.append(
                        f"go component has no reviewed license metadata hash: {identity}"
                    )

    actual_binaries = inventory.get("binaries")
    expected_binaries = policy.get("binaries")
    if not isinstance(actual_binaries, dict) or not isinstance(expected_binaries, dict):
        findings.append("release binary inventory must be objects")
    else:
        missing = sorted(set(expected_binaries) - set(actual_binaries))
        unexpected = sorted(set(actual_binaries) - set(expected_binaries))
        if missing or unexpected:
            findings.append(
                f"release binary inventory mismatch: missing [{', '.join(missing)}]; "
                f"unexpected [{', '.join(unexpected)}]"
            )
        for identity in sorted(set(actual_binaries) & set(expected_binaries)):
            actual_entry = actual_binaries[identity]
            policy_entry = expected_binaries[identity]
            if actual_entry.get("sha256") != policy_entry.get("sha256"):
                findings.append(f"release binary digest mismatch: {identity}")
            approved = policy_entry.get("approved_license")
            if not isinstance(approved, str) or approved not in allowed:
                findings.append(
                    f"release binary has unapproved license: {identity} uses {approved or '?'}"
                )
    return findings


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_json(path: Path, value: object) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if str(path) == "-":
        sys.stdout.write(payload)
    else:
        path.write_text(payload, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit licenses in exact built release images")
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate-app")
    generate.add_argument("--output", type=Path, required=True)
    assemble = subparsers.add_parser("assemble")
    assemble.add_argument("--app", type=Path, required=True)
    assemble.add_argument("--gateway-apk", type=Path, required=True)
    assemble.add_argument("--gateway-go", type=Path, required=True)
    assemble.add_argument("--caddy-sha256", required=True)
    assemble.add_argument("--release-identity", type=Path, required=True)
    assemble.add_argument("--policy", type=Path, required=True)
    assemble.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "generate-app":
            _write_json(args.output, build_app_inventory())
            print("Built app license inventory recorded.", file=sys.stderr)
            return 0
        app = _read_object(args.app)
        release_identity = _read_object(args.release_identity)
        images = release_identity.get("images")
        if not isinstance(images, dict) or set(images) != {"app", "gateway"}:
            raise ValueError("release identity must contain exactly app and gateway")
        app_components = app.get("components")
        if not isinstance(app_components, dict):
            raise ValueError("app inventory components must be an object")
        inventory = {
            "schema_version": 1,
            "release_images": {name: images[name]["image_id"] for name in sorted(images)},
            "components": {
                "debian": app_components.get("debian"),
                "python": app_components.get("python"),
                "alpine": parse_apk_installed(args.gateway_apk.read_text(encoding="utf-8")),
                "go": parse_go_version_m(args.gateway_go.read_text(encoding="utf-8-sig")),
            },
            "binaries": {"caddy": {"sha256": args.caddy_sha256}},
        }
        policy = _read_object(args.policy)
        findings = audit_release_inventory(inventory, policy)
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"ERROR: release license inventory input error: {error}", file=sys.stderr)
        return 1
    if findings:
        for finding in findings:
            print(f"ERROR: {finding}", file=sys.stderr)
        return 1
    _write_json(args.output, inventory)
    counts = {kind: len(inventory["components"][kind]) for kind in COMPONENT_KINDS}
    print(
        "Release license audit passed: "
        + ", ".join(f"{kind}={counts[kind]}" for kind in COMPONENT_KINDS)
        + "."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
