from __future__ import annotations

import copy
from hashlib import sha256

import pytest

from scripts.release_license_inventory import (
    audit_release_inventory,
    parse_apk_installed,
    parse_go_version_m,
    read_distribution_metadata,
)


def test_apk_inventory_records_every_exact_package_and_upstream_license():
    installed = (
        "C:Q1abc\nP:demo-lib\nV:1.2.3-r0\nA:x86_64\nL:MIT\no:demo\n\n"
        "C:Q1def\nP:demo-tool\nV:4.5.6-r1\nA:x86_64\nL:Apache-2.0\no:demo\n"
    )

    inventory = parse_apk_installed(installed)

    assert inventory == {
        "demo-lib@1.2.3-r0?arch=x86_64": {
            "name": "demo-lib",
            "version": "1.2.3-r0",
            "architecture": "x86_64",
            "source_package": "demo",
            "upstream_license": "MIT",
            "metadata_sha256": sha256(
                b"A:x86_64\nC:Q1abc\nL:MIT\nP:demo-lib\nV:1.2.3-r0\no:demo\n"
            ).hexdigest(),
        },
        "demo-tool@4.5.6-r1?arch=x86_64": {
            "name": "demo-tool",
            "version": "4.5.6-r1",
            "architecture": "x86_64",
            "source_package": "demo",
            "upstream_license": "Apache-2.0",
            "metadata_sha256": sha256(
                b"A:x86_64\nC:Q1def\nL:Apache-2.0\nP:demo-tool\nV:4.5.6-r1\no:demo\n"
            ).hexdigest(),
        },
    }
    assert parse_apk_installed("\ufeff" + installed) == inventory


def test_go_inventory_records_effective_replacements_and_toolchain():
    build_info = (
        "/usr/bin/caddy: go1.26.5\n"
        "\tpath\tcaddy\n"
        "\tdep\texample.test/direct\tv1.2.3\th1:direct\n"
        "\tdep\texample.test/original\tv1.0.0\n"
        "\t=>\texample.test/replacement\tv1.0.1\th1:replacement\n"
    )

    inventory = parse_go_version_m(build_info)

    assert inventory == {
        "example.test/direct@v1.2.3": {
            "module": "example.test/direct",
            "version": "v1.2.3",
            "go_sum": "h1:direct",
        },
        "example.test/replacement@v1.0.1": {
            "module": "example.test/replacement",
            "version": "v1.0.1",
            "go_sum": "h1:replacement",
            "replaces": "example.test/original@v1.0.0",
        },
        "stdlib@go1.26.5": {
            "module": "stdlib",
            "version": "go1.26.5",
            "go_sum": None,
        },
    }


def test_python_inventory_accepts_egg_info_pkg_info_for_the_first_party_project():
    class EggInfoDistribution:
        def read_text(self, filename: str):
            return None if filename == "METADATA" else "Name: museecho\nVersion: 0.1.0\n"

    assert read_distribution_metadata(EggInfoDistribution()) == (
        "PKG-INFO",
        "Name: museecho\nVersion: 0.1.0\n",
    )


def _inventory_and_policy():
    inventory = {
        "schema_version": 1,
        "release_images": {
            "app": "sha256:" + "a" * 64,
            "gateway": "sha256:" + "b" * 64,
        },
        "components": {
            "debian": {
                "demo@1.0?arch=amd64": {
                    "metadata_sha256": "1" * 64,
                    "version": "1.0",
                    "upstream_license_labels": ["BSD-3-clause"],
                }
            },
            "python": {"py-demo@2.0": {"metadata_sha256": "2" * 64, "version": "2.0"}},
            "alpine": {
                "apk-demo@3.0-r0?arch=x86_64": {
                    "metadata_sha256": "3" * 64,
                    "version": "3.0-r0",
                    "upstream_license": "MIT",
                }
            },
            "go": {
                "go.example/demo@v4.0.0": {
                    "module": "go.example/demo",
                    "version": "v4.0.0",
                    "go_sum": "h1:demo",
                }
            },
        },
        "binaries": {"caddy": {"sha256": "4" * 64}},
    }
    policy = {
        "schema_version": 1,
        "allowed_licenses": ["Apache-2.0", "BSD-3-Clause", "MIT"],
        "components": {
            "debian": {
                "demo@1.0?arch=amd64": {
                    "metadata_sha256": "1" * 64,
                    "upstream_license_labels": ["BSD-3-clause"],
                    "approved_license": "BSD-3-Clause",
                }
            },
            "python": {
                "py-demo@2.0": {
                    "metadata_sha256": "2" * 64,
                    "approved_license": "MIT",
                }
            },
            "alpine": {
                "apk-demo@3.0-r0?arch=x86_64": {
                    "metadata_sha256": "3" * 64,
                    "upstream_license": "MIT",
                    "approved_license": "MIT",
                }
            },
            "go": {
                "go.example/demo@v4.0.0": {
                    "go_sum": "h1:demo",
                    "license_files_sha256": ["5" * 64],
                    "approved_license": "Apache-2.0",
                }
            },
        },
        "binaries": {"caddy": {"sha256": "4" * 64, "approved_license": "Apache-2.0"}},
    }
    return inventory, policy


def test_release_license_audit_accepts_complete_exact_built_inventory():
    inventory, policy = _inventory_and_policy()

    assert audit_release_inventory(inventory, policy) == []


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        (
            lambda inventory, _policy: inventory["components"]["go"].clear(),
            "go component inventory mismatch",
        ),
        (
            lambda inventory, _policy: inventory["components"]["go"].update(
                {"go.example/new@v1.0.0": {"go_sum": "h1:new"}}
            ),
            "go component inventory mismatch",
        ),
        (
            lambda inventory, _policy: inventory["components"]["debian"][
                "demo@1.0?arch=amd64"
            ].update(metadata_sha256="9" * 64),
            "debian component metadata mismatch",
        ),
        (
            lambda inventory, _policy: inventory["components"]["debian"][
                "demo@1.0?arch=amd64"
            ].update(upstream_license_labels=["GPL-3+"]),
            "debian component upstream license mismatch",
        ),
        (
            lambda _inventory, policy: policy["components"]["alpine"][
                "apk-demo@3.0-r0?arch=x86_64"
            ].update(approved_license="GPL-3.0-only"),
            "unapproved license",
        ),
        (
            lambda _inventory, policy: policy["components"]["go"]["go.example/demo@v4.0.0"].update(
                go_sum="h1:drift"
            ),
            "go component sum mismatch",
        ),
        (
            lambda _inventory, policy: policy["components"]["go"]["go.example/demo@v4.0.0"].update(
                license_files_sha256=[]
            ),
            "has no reviewed license metadata hash",
        ),
    ),
)
def test_release_license_audit_fails_closed_for_inventory_or_license_drift(mutation, expected):
    inventory, policy = _inventory_and_policy()
    mutation(inventory, policy)

    findings = audit_release_inventory(copy.deepcopy(inventory), copy.deepcopy(policy))

    assert any(expected in finding for finding in findings)
