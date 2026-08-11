from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _needs_artifact(job: dict[str, Any], dependency: str) -> bool:
    return any(
        isinstance(item, dict) and item.get("job") == dependency and item.get("artifacts") is True
        for item in job.get("needs", [])
    )


def test_gitlab_secret_scanner_receives_and_requires_the_built_frontend_bundle():
    pipeline = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    frontend = pipeline["frontend"]
    secret_scan = pipeline["secret-scan"]

    assert "frontend/dist/" in frontend["artifacts"]["paths"]
    assert _needs_artifact(secret_scan, "frontend")
    commands = "\n".join(secret_scan["script"])
    assert "-RequireFrontendDist" in commands


def test_delivery_images_repositories_packages_and_release_identity_are_immutable():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    gitlab = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    github = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    from_images = re.findall(r"(?m)^FROM\s+(\S+)", dockerfile)
    assert from_images and all(re.search(r"@sha256:[0-9a-f]{64}$", item) for item in from_images)
    assert "snapshot.debian.org/archive/debian/" in dockerfile
    assert "snapshot.debian.org/archive/debian-security/" in dockerfile
    assert "ca-certificates=20230311+deb12u1" in dockerfile
    assert "ffmpeg=7:5.1.9-0+deb12u1" in dockerfile
    assert "apk upgrade" not in dockerfile
    assert "apk add --no-cache" not in dockerfile
    assert "ARG SOURCE_DATE_EPOCH=1785888000" in dockerfile
    assert "SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH" in dockerfile
    assert "PYTHONHASHSEED=0" in dockerfile
    assert "-name '*.pyc' -delete" in dockerfile
    assert "-name __pycache__ -empty -delete" in dockerfile
    assert "/var/cache/fontconfig/*" in dockerfile
    assert "/var/cache/ldconfig/aux-cache" in dockerfile
    assert "/var/log/apt/*" in dockerfile
    assert "/var/log/apk.log" in dockerfile
    for service_name in ("app", "gateway", "app-dev", "gateway-dev"):
        assert (
            compose["services"][service_name]["build"]["args"]["SOURCE_DATE_EPOCH"]
            == "${MUSEECHO_SOURCE_DATE_EPOCH:-1785888000}"
        )

    image_values: list[str] = []
    for job in gitlab.values():
        if not isinstance(job, dict):
            continue
        image = job.get("image")
        if isinstance(image, str):
            image_values.append(image)
        elif isinstance(image, dict):
            image_values.append(str(image.get("name", "")))
        for service in job.get("services", []):
            image_values.append(service if isinstance(service, str) else str(service["name"]))
    assert image_values and all(re.search(r"@sha256:[0-9a-f]{64}$", item) for item in image_values)
    assert re.search(r"aquasec/trivy:0\.70\.0@sha256:[0-9a-f]{64}", github)

    for contents in (github, (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")):
        assert "release-images.json" in contents
        assert "verify_release_identity.py" in contents
        assert "SOURCE_DATE_EPOCH: 1785888000" in contents
        assert "--build-arg SOURCE_DATE_EPOCH" in contents
        assert contents.count("rewrite-timestamp=true") >= 2


def test_development_profile_renders_an_https_same_origin_gateway():
    if shutil.which("docker") is None:
        # The authoritative pytest image deliberately has no Docker socket or
        # client. Keep its contract fail-closed while the host smoke below runs
        # the exact documented Compose command against the real daemon.
        config = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
        gateway = config["services"]["gateway-dev"]
        app = config["services"]["app-dev"]
        assert gateway["ports"] == ["127.0.0.1:4173:8443"]
        assert gateway["environment"]["MUSEECHO_API_UPSTREAM"] == "app-dev"
        assert (
            app["environment"]["MUSEECHO_TRUSTED_ORIGINS"]
            == "https://localhost:4173,https://127.0.0.1:4173"
        )
        assert gateway["read_only"] is True
        assert gateway["cap_drop"] == ["ALL"]
        return

    completed = subprocess.run(
        ["docker", "compose", "--profile", "development", "config", "--format", "json"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    config = json.loads(completed.stdout)
    gateway = config["services"]["gateway-dev"]
    app = config["services"]["app-dev"]

    assert gateway["ports"][0]["published"] == "4173"
    assert gateway["environment"]["MUSEECHO_API_UPSTREAM"] == "app-dev"
    assert (
        app["environment"]["MUSEECHO_TRUSTED_ORIGINS"]
        == "https://localhost:4173,https://127.0.0.1:4173"
    )
    assert gateway["read_only"] is True
    assert gateway["cap_drop"] == ["ALL"]


def test_linux_secret_modes_and_documented_development_path_have_real_ci_smokes():
    github = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert (ROOT / "scripts" / "test-linux-secret-contract.ps1").is_file()
    assert (ROOT / "scripts" / "development-smoke.ps1").is_file()
    assert "test-linux-secret-contract.ps1 -AppImage museecho-app:ci" in github
    assert "development-smoke.ps1" in github
    assert "SOURCE_DATE_EPOCH=1785888000" in readme
    assert "rewrite-timestamp=true" in readme
    assert "verify_release_identity.py record" in readme
    assert "docker compose --profile production build" not in readme
    assert "docker compose --profile production up -d --wait --no-build" in readme
