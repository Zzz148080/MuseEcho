from __future__ import annotations

import copy
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

from scripts import verify_release_identity
from scripts.verify_release_identity import (
    audit_release_identity,
    build_release_identity,
    image_id_from_tar,
    main,
)

APP_ID = "sha256:" + "a" * 64
GATEWAY_ID = "sha256:" + "b" * 64
APP_TAR = "c" * 64
GATEWAY_TAR = "d" * 64


def _manifest() -> dict[str, object]:
    return build_release_identity(
        {"app": APP_ID, "gateway": GATEWAY_ID},
        {"app": APP_TAR, "gateway": GATEWAY_TAR},
    )


def test_release_identity_accepts_the_same_images_tars_and_raw_scans():
    scans = {
        "app": {"Metadata": {"ImageID": APP_ID}},
        "gateway": {"Metadata": {"ImageID": GATEWAY_ID}},
    }

    assert (
        audit_release_identity(
            _manifest(),
            image_ids={"app": APP_ID, "gateway": GATEWAY_ID},
            tar_digests={"app": APP_TAR, "gateway": GATEWAY_TAR},
            scans=scans,
        )
        == []
    )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        (lambda manifest: manifest["images"].pop("gateway"), "image inventory mismatch"),
        (
            lambda manifest: manifest["images"]["app"].update(image_id=GATEWAY_ID),
            "app image id mismatch",
        ),
        (
            lambda manifest: manifest["images"]["app"].update(tar_sha256=GATEWAY_TAR),
            "app tar sha256 mismatch",
        ),
    ),
)
def test_release_identity_fails_closed_for_missing_or_drifted_artifacts(mutation, expected):
    manifest = copy.deepcopy(_manifest())
    mutation(manifest)

    findings = audit_release_identity(
        manifest,
        image_ids={"app": APP_ID, "gateway": GATEWAY_ID},
        tar_digests={"app": APP_TAR, "gateway": GATEWAY_TAR},
    )

    assert any(expected in finding for finding in findings)


def test_release_identity_rejects_a_raw_scan_of_another_image():
    findings = audit_release_identity(
        _manifest(),
        scans={
            "app": {"Metadata": {"ImageID": GATEWAY_ID}},
            "gateway": {"Metadata": {"ImageID": GATEWAY_ID}},
        },
    )

    assert findings == [f"app raw scan image id mismatch: {GATEWAY_ID}, expected {APP_ID}"]


@pytest.mark.parametrize(
    ("comparison", "expected"),
    (
        ({"image_ids": {"app": APP_ID}}, "release image id input inventory mismatch"),
        ({"tar_digests": {"app": APP_TAR}}, "release tar input inventory mismatch"),
        (
            {"scans": {"app": {"Metadata": {"ImageID": APP_ID}}}},
            "release scan input inventory mismatch",
        ),
    ),
)
def test_release_identity_rejects_incomplete_comparison_inputs(comparison, expected):
    findings = audit_release_identity(_manifest(), **comparison)

    assert findings == [f"{expected}: missing [gateway]; unexpected []"]


def test_verify_cli_rejects_manifest_only_empty_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    manifest_path = tmp_path / "release-images.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_release_identity.py",
            "verify",
            "--manifest",
            str(manifest_path),
        ],
    )

    assert main() == 1
    assert "at least one complete comparison inventory" in capsys.readouterr().err


def test_release_identity_is_derived_from_the_exact_config_inside_saved_tar(tmp_path: Path):
    config = b'{"architecture":"amd64","os":"linux"}'
    config_digest = __import__("hashlib").sha256(config).hexdigest()
    manifest = json.dumps([{"Config": f"blobs/sha256/{config_digest}", "RepoTags": []}]).encode()
    tar_path = tmp_path / "image.tar"
    with tarfile.open(tar_path, "w") as archive:
        for name, payload in (
            ("manifest.json", manifest),
            (f"blobs/sha256/{config_digest}", config),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))

    assert image_id_from_tar(tar_path) == f"sha256:{config_digest}"


def _write_oci_image_tar(
    tmp_path: Path,
    *,
    oci_config: bytes | None = None,
    docker_layer: bytes | None = None,
    oci_layer: bytes | None = None,
) -> tuple[Path, str, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    config = b'{"architecture":"amd64","os":"linux"}'
    config_digest = __import__("hashlib").sha256(config).hexdigest()
    oci_config = oci_config or config
    oci_config_digest = __import__("hashlib").sha256(oci_config).hexdigest()
    oci_layer = docker_layer if oci_layer is None else oci_layer
    oci_layers = []
    if oci_layer is not None:
        oci_layer_digest = __import__("hashlib").sha256(oci_layer).hexdigest()
        oci_layers.append(
            {
                "mediaType": "application/vnd.oci.image.layer.v1.tar",
                "digest": f"sha256:{oci_layer_digest}",
                "size": len(oci_layer),
            }
        )
    oci_manifest = json.dumps(
        {
            "schemaVersion": 2,
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": f"sha256:{oci_config_digest}",
                "size": len(oci_config),
            },
            "layers": oci_layers,
        },
        separators=(",", ":"),
    ).encode()
    manifest_digest = __import__("hashlib").sha256(oci_manifest).hexdigest()
    index = json.dumps(
        {
            "schemaVersion": 2,
            "manifests": [
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": f"sha256:{manifest_digest}",
                    "size": len(oci_manifest),
                }
            ],
        }
    ).encode()
    docker_layers = []
    if docker_layer is not None:
        docker_layer_digest = __import__("hashlib").sha256(docker_layer).hexdigest()
        docker_layers.append(f"blobs/sha256/{docker_layer_digest}")
    docker_manifest = json.dumps(
        [
            {
                "Config": f"blobs/sha256/{config_digest}",
                "RepoTags": [],
                "Layers": docker_layers,
            }
        ]
    ).encode()
    tar_path = tmp_path / "image.tar"
    members = {
        "index.json": index,
        "manifest.json": docker_manifest,
        f"blobs/sha256/{manifest_digest}": oci_manifest,
        f"blobs/sha256/{config_digest}": config,
        f"blobs/sha256/{oci_config_digest}": oci_config,
    }
    if docker_layer is not None:
        members[f"blobs/sha256/{docker_layer_digest}"] = docker_layer
    if oci_layer is not None:
        members[f"blobs/sha256/{oci_layer_digest}"] = oci_layer
    with tarfile.open(tar_path, "w") as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))

    return tar_path, config_digest, manifest_digest


def test_release_manifest_digest_is_derived_from_the_exact_oci_descriptor(tmp_path: Path):
    tar_path, _, manifest_digest = _write_oci_image_tar(
        tmp_path,
        docker_layer=b"matching non-empty image layer",
    )

    assert verify_release_identity.manifest_digest_from_tar(tar_path) == f"sha256:{manifest_digest}"


def test_record_cli_writes_config_and_manifest_digests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    app_tar, app_config, app_manifest = _write_oci_image_tar(tmp_path / "app")
    gateway_tar, gateway_config, gateway_manifest = _write_oci_image_tar(tmp_path / "gateway")
    output = tmp_path / "release-images.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_release_identity.py",
            "record",
            "--output",
            str(output),
            "--tar",
            f"app={app_tar}",
            "--tar",
            f"gateway={gateway_tar}",
        ],
    )

    assert main() == 0
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["images"]["app"]["image_id"] == f"sha256:{app_config}"
    assert manifest["images"]["app"]["manifest_digest"] == f"sha256:{app_manifest}"
    assert manifest["images"]["gateway"]["image_id"] == f"sha256:{gateway_config}"
    assert manifest["images"]["gateway"]["manifest_digest"] == f"sha256:{gateway_manifest}"


def test_release_manifest_digest_rejects_a_missing_descriptor_blob(tmp_path: Path):
    missing_digest = "e" * 64
    index = json.dumps(
        {
            "schemaVersion": 2,
            "manifests": [
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": f"sha256:{missing_digest}",
                    "size": 123,
                }
            ],
        }
    ).encode()
    tar_path = tmp_path / "image.tar"
    with tarfile.open(tar_path, "w") as archive:
        info = tarfile.TarInfo("index.json")
        info.size = len(index)
        archive.addfile(info, io.BytesIO(index))

    with pytest.raises(ValueError, match="has no recorded OCI manifest blob"):
        verify_release_identity.manifest_digest_from_tar(tar_path)


def test_record_cli_rejects_oci_manifest_bound_to_another_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    app_tar, _, _ = _write_oci_image_tar(
        tmp_path / "app",
        oci_config=b'{"architecture":"arm64","os":"linux"}',
    )
    gateway_tar, _, _ = _write_oci_image_tar(tmp_path / "gateway")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_release_identity.py",
            "record",
            "--output",
            str(tmp_path / "release-images.json"),
            "--tar",
            f"app={app_tar}",
            "--tar",
            f"gateway={gateway_tar}",
        ],
    )

    assert main() == 1
    assert "OCI manifest config digest mismatch" in capsys.readouterr().err


def test_record_cli_rejects_oci_manifest_bound_to_other_layers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    app_tar, _, _ = _write_oci_image_tar(
        tmp_path / "app",
        docker_layer=b"benign scanned layer",
        oci_layer=b"different runtime layer",
    )
    gateway_tar, _, _ = _write_oci_image_tar(tmp_path / "gateway")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_release_identity.py",
            "record",
            "--output",
            str(tmp_path / "release-images.json"),
            "--tar",
            f"app={app_tar}",
            "--tar",
            f"gateway={gateway_tar}",
        ],
    )

    assert main() == 1
    assert "OCI manifest layers mismatch" in capsys.readouterr().err


def test_release_identity_rejects_claimed_manifest_digest_missing_from_saved_tars():
    manifest = _manifest()
    for name, digest in (("app", "e" * 64), ("gateway", "f" * 64)):
        manifest["images"][name]["manifest_digest"] = f"sha256:{digest}"

    findings = audit_release_identity(manifest, manifest_digests={})

    assert findings == [
        "app manifest digest is missing from saved tar",
        "gateway manifest digest is missing from saved tar",
    ]
