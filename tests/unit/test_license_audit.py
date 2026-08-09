from __future__ import annotations

import json
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
    (root / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    (root / "frontend").mkdir(exist_ok=True)
    (root / "frontend" / "package-lock.json").write_text(
        json.dumps({"lockfileVersion": 3, "packages": {"": {}}}),
        encoding="utf-8",
    )
    policy_path = root / "license-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "python": {"demo": {"version": "1.2.3", "license": "MIT"}},
                "npm_allowed_licenses": ["MIT"],
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
