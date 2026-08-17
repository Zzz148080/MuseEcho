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
    image_ids: dict[str, str],
    tar_digests: dict[str, str],
    manifest_digests: dict[str, str] | None = None,
) -> dict[str, object]:
    if set(image_ids) != IMAGE_NAMES or set(tar_digests) != IMAGE_NAMES:
        raise ValueError("release identity requires exactly app and gateway")
    if manifest_digests is not None and set(manifest_digests) != IMAGE_NAMES:
        raise ValueError("release manifest identity requires exactly app and gateway")
    for name, image_id in image_ids.items():
        if not IMAGE_ID_PATTERN.fullmatch(image_id):
            raise ValueError(f"{name} image id is not a sha256 digest")
    for name, digest in tar_digests.items():
        if not DIGEST_PATTERN.fullmatch(digest):
            raise ValueError(f"{name} tar sha256 is invalid")
    for name, digest in (manifest_digests or {}).items():
        if not IMAGE_ID_PATTERN.fullmatch(digest):
            raise ValueError(f"{name} manifest digest is not a sha256 digest")
    entries: dict[str, dict[str, str]] = {}
    for name in sorted(IMAGE_NAMES):
        entries[name] = {
            "image_id": image_ids[name],
            "tar_sha256": tar_digests[name],
        }
        if manifest_digests is not None:
            entries[name]["manifest_digest"] = manifest_digests[name]
    return {
        "schema_version": 1,
        "images": entries,
    }


def audit_release_identity(
    manifest: dict[str, Any],
    *,
    image_ids: dict[str, str] | None = None,
    manifest_digests: dict[str, str] | None = None,
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
        expected_manifest_digest = entry.get("manifest_digest")
        expected_tar = entry.get("tar_sha256")
        if not isinstance(expected_image_id, str) or not IMAGE_ID_PATTERN.fullmatch(
            expected_image_id
        ):
            findings.append(f"{name} recorded image id is invalid")
        if not isinstance(expected_tar, str) or not DIGEST_PATTERN.fullmatch(expected_tar):
            findings.append(f"{name} recorded tar sha256 is invalid")
        if expected_manifest_digest is not None and (
            not isinstance(expected_manifest_digest, str)
            or not IMAGE_ID_PATTERN.fullmatch(expected_manifest_digest)
        ):
            findings.append(f"{name} recorded manifest digest is invalid")
        if image_ids is not None and name in image_ids and image_ids[name] != expected_image_id:
            findings.append(
                f"{name} image id mismatch: {image_ids[name]}, expected {expected_image_id}"
            )
        if tar_digests is not None and name in tar_digests and tar_digests[name] != expected_tar:
            findings.append(
                f"{name} tar sha256 mismatch: {tar_digests[name]}, expected {expected_tar}"
            )
        if manifest_digests is not None and expected_manifest_digest is not None:
            if name not in manifest_digests:
                findings.append(f"{name} manifest digest is missing from saved tar")
            elif manifest_digests[name] != expected_manifest_digest:
                findings.append(
                    f"{name} manifest digest mismatch: {manifest_digests[name]}, "
                    f"expected {expected_manifest_digest}"
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
        if recorded_digest.endswith(".json"):
            recorded_digest = recorded_digest.removesuffix(".json")
        if not DIGEST_PATTERN.fullmatch(recorded_digest):
            raise ValueError(f"{path} config blob name is not a sha256 digest")
        if recorded_digest != actual_digest:
            raise ValueError(f"{path} config blob digest mismatch")
        return f"sha256:{actual_digest}"


def manifest_digest_from_tar(path: Path, *, expected_image_id: str | None = None) -> str | None:
    with tarfile.open(path, "r") as archive:
        try:
            index_stream = archive.extractfile("index.json")
        except KeyError:
            return None
        if index_stream is None:
            return None
        index = json.load(index_stream)
        descriptors = index.get("manifests") if isinstance(index, dict) else None
        if not isinstance(descriptors, list) or len(descriptors) != 1:
            raise ValueError(f"{path} must contain exactly one OCI manifest descriptor")
        descriptor = descriptors[0]
        if not isinstance(descriptor, dict):
            raise ValueError(f"{path} OCI manifest descriptor must be an object")
        digest = descriptor.get("digest")
        size = descriptor.get("size")
        if descriptor.get("mediaType") not in {
            "application/vnd.oci.image.manifest.v1+json",
            "application/vnd.docker.distribution.manifest.v2+json",
        }:
            raise ValueError(f"{path} OCI manifest descriptor media type is invalid")
        if not isinstance(digest, str) or not IMAGE_ID_PATTERN.fullmatch(digest):
            raise ValueError(f"{path} OCI manifest descriptor digest is invalid")
        if not isinstance(size, int) or size < 0:
            raise ValueError(f"{path} OCI manifest descriptor size is invalid")
        blob_path = f"blobs/sha256/{digest.removeprefix('sha256:')}"
        try:
            blob_stream = archive.extractfile(blob_path)
        except KeyError:
            blob_stream = None
        if blob_stream is None:
            raise ValueError(f"{path} has no recorded OCI manifest blob")
        payload = blob_stream.read()
        if len(payload) != size:
            raise ValueError(f"{path} OCI manifest blob size mismatch")
        actual_digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        if actual_digest != digest:
            raise ValueError(f"{path} OCI manifest blob digest mismatch")
        try:
            oci_manifest = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path} OCI manifest blob is not valid JSON") from error
        if not isinstance(oci_manifest, dict) or oci_manifest.get("schemaVersion") != 2:
            raise ValueError(f"{path} OCI manifest schema is invalid")
        config = oci_manifest.get("config")
        if not isinstance(config, dict):
            raise ValueError(f"{path} OCI manifest config descriptor is invalid")
        config_digest = config.get("digest")
        config_size = config.get("size")
        if not isinstance(config_digest, str) or not IMAGE_ID_PATTERN.fullmatch(config_digest):
            raise ValueError(f"{path} OCI manifest config digest is invalid")
        if not isinstance(config_size, int) or config_size < 0:
            raise ValueError(f"{path} OCI manifest config size is invalid")
        config_path = f"blobs/sha256/{config_digest.removeprefix('sha256:')}"
        try:
            config_stream = archive.extractfile(config_path)
        except KeyError:
            config_stream = None
        if config_stream is None:
            raise ValueError(f"{path} has no OCI manifest config blob")
        config_payload = config_stream.read()
        if len(config_payload) != config_size:
            raise ValueError(f"{path} OCI manifest config blob size mismatch")
        actual_config_digest = f"sha256:{hashlib.sha256(config_payload).hexdigest()}"
        if actual_config_digest != config_digest:
            raise ValueError(f"{path} OCI manifest config blob digest mismatch")
        if expected_image_id is not None and config_digest != expected_image_id:
            raise ValueError(f"{path} OCI manifest config digest mismatch")
        try:
            docker_manifest_stream = archive.extractfile("manifest.json")
        except KeyError:
            docker_manifest_stream = None
        if docker_manifest_stream is None:
            raise ValueError(f"{path} has no Docker image manifest")
        docker_manifest = json.load(docker_manifest_stream)
        if (
            not isinstance(docker_manifest, list)
            or len(docker_manifest) != 1
            or not isinstance(docker_manifest[0], dict)
        ):
            raise ValueError(f"{path} must contain exactly one Docker image manifest")
        docker_layers = docker_manifest[0].get("Layers")
        oci_layers = oci_manifest.get("layers")
        if not isinstance(docker_layers, list) or not all(
            isinstance(layer, str) for layer in docker_layers
        ):
            raise ValueError(f"{path} Docker manifest layers are invalid")
        if not isinstance(oci_layers, list) or not all(
            isinstance(layer, dict) for layer in oci_layers
        ):
            raise ValueError(f"{path} OCI manifest layers are invalid")
        if len(docker_layers) != len(oci_layers):
            raise ValueError(f"{path} OCI manifest layers mismatch")
        for docker_layer, oci_layer in zip(docker_layers, oci_layers, strict=True):
            layer_digest = oci_layer.get("digest")
            layer_size = oci_layer.get("size")
            if not isinstance(layer_digest, str) or not IMAGE_ID_PATTERN.fullmatch(layer_digest):
                raise ValueError(f"{path} OCI manifest layer digest is invalid")
            if not isinstance(layer_size, int) or layer_size < 0:
                raise ValueError(f"{path} OCI manifest layer size is invalid")
            layer_path = f"blobs/sha256/{layer_digest.removeprefix('sha256:')}"
            if docker_layer != layer_path:
                raise ValueError(f"{path} OCI manifest layers mismatch")
            try:
                layer_stream = archive.extractfile(layer_path)
            except KeyError:
                layer_stream = None
            if layer_stream is None:
                raise ValueError(f"{path} has no OCI manifest layer blob")
            layer_payload = layer_stream.read()
            if len(layer_payload) != layer_size:
                raise ValueError(f"{path} OCI manifest layer blob size mismatch")
            actual_layer_digest = f"sha256:{hashlib.sha256(layer_payload).hexdigest()}"
            if actual_layer_digest != layer_digest:
                raise ValueError(f"{path} OCI manifest layer blob digest mismatch")
        return actual_digest


def _tar_paths(values: list[str]) -> dict[str, Path]:
    return {name: Path(path) for name, path in _assignments(values, "tar").items()}


def _tar_digests(paths: dict[str, Path]) -> dict[str, str]:
    return {name: _sha256_file(path) for name, path in paths.items()}


def _manifest_digests(
    paths: dict[str, Path], image_ids: dict[str, str] | None = None
) -> dict[str, str]:
    values = {
        name: manifest_digest_from_tar(
            path,
            expected_image_id=(image_ids or {}).get(name),
        )
        for name, path in paths.items()
    }
    present = {name: digest for name, digest in values.items() if digest is not None}
    if present and set(present) != set(paths):
        raise ValueError(
            "saved tars must either both include or both omit OCI manifest descriptors"
        )
    return present


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
            derived_manifest_digests = _manifest_digests(tar_paths, derived_image_ids)
            provided_image_ids = _assignments(args.image_id, "image id")
            if provided_image_ids and provided_image_ids != derived_image_ids:
                raise ValueError(
                    "provided image ids do not match the config digests in the saved tars"
                )
            manifest = build_release_identity(
                derived_image_ids,
                _tar_digests(tar_paths),
                derived_manifest_digests or None,
            )
            payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
            if str(args.output) == "-":
                sys.stdout.write(payload)
            else:
                args.output.write_text(payload, encoding="utf-8")
            return 0
        if not (args.image_id or args.tar or args.scan):
            raise ValueError("verify requires at least one complete comparison inventory")
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("release manifest must contain a JSON object")
        tar_paths = _tar_paths(args.tar)
        provided_image_ids = _assignments(args.image_id, "image id")
        derived_image_ids = {name: image_id_from_tar(path) for name, path in tar_paths.items()}
        if provided_image_ids and derived_image_ids and provided_image_ids != derived_image_ids:
            raise ValueError("provided image ids do not match the config digests in the saved tars")
        findings = audit_release_identity(
            manifest,
            image_ids=provided_image_ids or derived_image_ids or None,
            manifest_digests=_manifest_digests(tar_paths, derived_image_ids) if tar_paths else None,
            tar_digests=_tar_digests(tar_paths) or None,
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
