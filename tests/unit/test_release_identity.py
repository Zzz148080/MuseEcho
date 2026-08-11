from __future__ import annotations

import copy
import io
import json
import tarfile
from pathlib import Path

import pytest

from scripts.verify_release_identity import (
    audit_release_identity,
    build_release_identity,
    image_id_from_tar,
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
