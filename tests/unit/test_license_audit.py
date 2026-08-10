from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from scripts.license_audit import audit_repository


def _write_repository(root: Path, *, npm_license: str | None = "MIT") -> Path:
    (root / "uv.lock").write_text(
        'version = 1\n\n[[package]]\nname = "demo"\nversion = "1.2.3"\n',
        encoding="utf-8",
    )
    package = {"version": "4.5.6"}
    if npm_license is not None:
        package["license"] = npm_license
    lock = {"lockfileVersion": 3, "packages": {"": {}, "node_modules/demo": package}}
    root_lock_text = json.dumps(lock)
    (root / "package-lock.json").write_text(root_lock_text, encoding="utf-8")
    (root / "frontend").mkdir(exist_ok=True)
    frontend_lock_text = json.dumps({"lockfileVersion": 3, "packages": {"": {}}})
    (root / "frontend" / "package-lock.json").write_text(frontend_lock_text, encoding="utf-8")
    (root / "Dockerfile").write_text(
        "FROM python:3.12.13-slim-bookworm AS app\n"
        "RUN python -m pip install --no-cache-dir uv==0.11.29\n"
        "RUN apt-get install --yes --no-install-recommends ca-certificates ffmpeg;\n",
        encoding="utf-8",
    )
    (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (root / ".github" / "workflows" / "ci.yml").write_text("", encoding="utf-8")
    (root / ".gitlab-ci.yml").write_text("services:\n  - name: docker:29-dind\n", encoding="utf-8")
    policy_path = root / "license-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "allowed_licenses": [
                    "GPL-2.0-or-later",
                    "MIT",
                    "MPL-2.0",
                    "UPSTREAM-NOTICES",
                ],
                "python": {"demo": {"version": "1.2.3", "license": "MIT"}},
                "npm_allowed_licenses": ["MIT"],
                "npm_lock_sha256": {
                    "package-lock.json": sha256(root_lock_text.encode()).hexdigest(),
                    "frontend/package-lock.json": sha256(frontend_lock_text.encode()).hexdigest(),
                },
                "distribution": {
                    "container_images": {
                        "docker:29-dind": "UPSTREAM-NOTICES",
                        "python:3.12.13-slim-bookworm": "UPSTREAM-NOTICES",
                    },
                    "build_tools": {"uv@0.11.29": "MIT"},
                    "go_module_replacements": {},
                    "system_packages": {
                        "debian": {
                            "ca-certificates": "MPL-2.0",
                            "ffmpeg": "GPL-2.0-or-later",
                        },
                        "alpine": {},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return policy_path


def test_license_audit_accepts_exact_lock_versions_and_approved_npm_licenses(tmp_path: Path):
    policy_path = _write_repository(tmp_path)

    assert audit_repository(tmp_path, policy_path) == []


def test_license_audit_rejects_python_policy_version_drift(tmp_path: Path):
    policy_path = _write_repository(tmp_path)
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["python"]["demo"]["version"] = "1.2.2"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    assert audit_repository(tmp_path, policy_path) == [
        "python policy mismatch: demo locked 1.2.3, policy 1.2.2"
    ]


def test_license_audit_rejects_missing_or_unapproved_npm_license(tmp_path: Path):
    missing_policy = _write_repository(tmp_path, npm_license=None)
    assert audit_repository(tmp_path, missing_policy) == [
        "package-lock.json: node_modules/demo@4.5.6 has no license"
    ]

    (tmp_path / "package-lock.json").unlink()
    rejected_policy = _write_repository(tmp_path, npm_license="AGPL-3.0-only")
    assert audit_repository(tmp_path, rejected_policy) == [
        "package-lock.json: node_modules/demo@4.5.6 uses unapproved license AGPL-3.0-only"
    ]


def test_license_audit_rejects_policy_license_outside_explicit_allowed_set(
    tmp_path: Path,
):
    policy_path = _write_repository(tmp_path)
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["python"]["demo"]["license"] = "MADE-UP-PERMISSIVE"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    assert audit_repository(tmp_path, policy_path) == [
        "python policy license is not allowed: demo@1.2.3 uses MADE-UP-PERMISSIVE"
    ]


def test_license_audit_rejects_exact_npm_inventory_drift(tmp_path: Path):
    policy_path = _write_repository(tmp_path)
    lock_path = tmp_path / "package-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["packages"]["node_modules/demo"]["version"] = "4.5.7"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")

    findings = audit_repository(tmp_path, policy_path)

    assert len(findings) == 1
    assert findings[0].startswith("npm inventory mismatch: package-lock.json sha256 ")


def test_license_audit_rejects_distribution_inventory_drift(tmp_path: Path):
    policy_path = _write_repository(tmp_path)
    dockerfile_path = tmp_path / "Dockerfile"
    dockerfile_path.write_text(
        dockerfile_path.read_text(encoding="utf-8").replace(
            "python:3.12.13-slim-bookworm", "python:3.12.12-slim-bookworm"
        ),
        encoding="utf-8",
    )

    assert audit_repository(tmp_path, policy_path) == [
        "distribution container_images inventory mismatch: "
        "missing [python:3.12.13-slim-bookworm]; "
        "unexpected [python:3.12.12-slim-bookworm]"
    ]
