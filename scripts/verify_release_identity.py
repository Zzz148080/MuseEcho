from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
from pathlib import Path
from typing import Any

IMAGE_NAMES = {"app", "gateway"}
IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def build_release_identity(
    image_ids: dict[str, str], tar_digests: dict[str, str]
) -> dict[str, object]:
    if set(image_ids) != IMAGE_NAMES or set(tar_digests) != IMAGE_NAMES:
        raise ValueError("release identity requires exactly app and gateway")
    for name, image_id in image_ids.items():
        if not IMAGE_ID_PATTERN.fullmatch(image_id):
            raise ValueError(f"{name} image id is not a sha256 digest")
    for name, digest in tar_digests.items():
        if not DIGEST_PATTERN.fullmatch(digest):
            raise ValueError(f"{name} tar sha256 is invalid")
    return {
        "schema_version": 1,
        "images": {
            name: {
                "image_id": image_ids[name],
                "tar_sha256": tar_digests[name],
            }
            for name in sorted(IMAGE_NAMES)
        },
    }


def audit_release_identity(
    manifest: dict[str, Any],
    *,
    image_ids: dict[str, str] | None = None,
    tar_digests: dict[str, str] | None = None,
    scans: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    findings: list[str] = []
    if manifest.get("schema_version") != 1:
        findings.append("release identity schema version mismatch")
    images = manifest.get("images")
    if not isinstance(images, dict):
        return findings + ["release image inventory mismatch: images must be an object"]
    missing = sorted(IMAGE_NAMES - set(images))
    unexpected = sorted(set(images) - IMAGE_NAMES)
    if missing or unexpected:
        findings.append(
            "release image inventory mismatch: "
            f"missing [{', '.join(missing)}]; unexpected [{', '.join(unexpected)}]"
        )
    for label, values in (
        ("release image id input inventory mismatch", image_ids),
        ("release tar input inventory mismatch", tar_digests),
        ("release scan input inventory mismatch", scans),
    ):
        if values is None:
            continue
        missing = sorted(IMAGE_NAMES - set(values))
        unexpected = sorted(set(values) - IMAGE_NAMES)
        if missing or unexpected:
            findings.append(
                f"{label}: missing [{', '.join(missing)}]; unexpected [{', '.join(unexpected)}]"
            )
    for name in sorted(IMAGE_NAMES & set(images)):
        entry = images[name]
        if not isinstance(entry, dict):
            findings.append(f"{name} release identity entry must be an object")
            continue
        expected_image_id = entry.get("image_id")
        expected_tar = entry.get("tar_sha256")
        if not isinstance(expected_image_id, str) or not IMAGE_ID_PATTERN.fullmatch(
            expected_image_id
        ):
            findings.append(f"{name} recorded image id is invalid")
        if not isinstance(expected_tar, str) or not DIGEST_PATTERN.fullmatch(expected_tar):
            findings.append(f"{name} recorded tar sha256 is invalid")
        if image_ids is not None and name in image_ids and image_ids[name] != expected_image_id:
            findings.append(
                f"{name} image id mismatch: {image_ids[name]}, expected {expected_image_id}"
            )
        if tar_digests is not None and name in tar_digests and tar_digests[name] != expected_tar:
            findings.append(
                f"{name} tar sha256 mismatch: {tar_digests[name]}, expected {expected_tar}"
            )
        if scans is not None and name in scans:
            metadata = scans[name].get("Metadata")
            scan_image_id = metadata.get("ImageID") if isinstance(metadata, dict) else None
            if scan_image_id != expected_image_id:
                findings.append(
                    f"{name} raw scan image id mismatch: {scan_image_id or '?'}, "
                    f"expected {expected_image_id}"
                )
    return findings


def _assignments(values: list[str], label: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        name, separator, assigned = value.partition("=")
        if not separator or name in parsed:
            raise ValueError(f"invalid or duplicate {label}: {value}")
        parsed[name] = assigned
    return parsed


def _read_scan_assignments(values: list[str]) -> dict[str, dict[str, Any]]:
    scans: dict[str, dict[str, Any]] = {}
    for name, path in _assignments(values, "scan").items():
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"{path} must contain a JSON object")
        scans[name] = value
    return scans


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_id_from_tar(path: Path) -> str:
    with tarfile.open(path, "r") as archive:
        manifest_stream = archive.extractfile("manifest.json")
        if manifest_stream is None:
            raise ValueError(f"{path} has no manifest.json")
        manifest = json.load(manifest_stream)
        if (
            not isinstance(manifest, list)
            or len(manifest) != 1
            or not isinstance(manifest[0], dict)
        ):
            raise ValueError(f"{path} must contain exactly one image manifest")
        config_name = manifest[0].get("Config")
        if not isinstance(config_name, str):
            raise ValueError(f"{path} manifest has no config path")
        config_stream = archive.extractfile(config_name)
        if config_stream is None:
            raise ValueError(f"{path} has no recorded config blob")
        actual_digest = hashlib.sha256(config_stream.read()).hexdigest()
        recorded_digest = Path(config_name).name
        if recorded_digest != actual_digest:
            raise ValueError(f"{path} config blob digest mismatch")
        return f"sha256:{actual_digest}"


def _tar_paths(values: list[str]) -> dict[str, Path]:
    return {name: Path(path) for name, path in _assignments(values, "tar").items()}


def _tar_digests(paths: dict[str, Path]) -> dict[str, str]:
    return {name: _sha256_file(path) for name, path in paths.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Record and verify exact release image identity")
    subparsers = parser.add_subparsers(dest="command", required=True)
    record = subparsers.add_parser("record")
    record.add_argument("--output", type=Path, required=True)
    record.add_argument("--image-id", action="append", default=[])
    record.add_argument("--tar", action="append", default=[])
    verify = subparsers.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--image-id", action="append", default=[])
    verify.add_argument("--tar", action="append", default=[])
    verify.add_argument("--scan", action="append", default=[])
    args = parser.parse_args()
    try:
        if args.command == "record":
            tar_paths = _tar_paths(args.tar)
            derived_image_ids = {name: image_id_from_tar(path) for name, path in tar_paths.items()}
            provided_image_ids = _assignments(args.image_id, "image id")
            if provided_image_ids and provided_image_ids != derived_image_ids:
                raise ValueError(
                    "provided image ids do not match the config digests in the saved tars"
                )
            manifest = build_release_identity(derived_image_ids, _tar_digests(tar_paths))
            payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
            if str(args.output) == "-":
                sys.stdout.write(payload)
            else:
                args.output.write_text(payload, encoding="utf-8")
            return 0
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("release manifest must contain a JSON object")
        findings = audit_release_identity(
            manifest,
            image_ids=_assignments(args.image_id, "image id") or None,
            tar_digests=_tar_digests(_tar_paths(args.tar)) or None,
            scans=_read_scan_assignments(args.scan) or None,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: release identity input error: {error}", file=sys.stderr)
        return 1
    if findings:
        for finding in findings:
            print(f"ERROR: {finding}", file=sys.stderr)
        return 1
    print("Release image identity verified: app and gateway artifacts are unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
