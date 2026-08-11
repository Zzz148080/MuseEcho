from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from scripts.check_acceptance_matrix import load_audit

ROOT = Path(__file__).resolve().parents[2]


def _needs_artifact(job: dict[str, Any], dependency: str) -> bool:
    return any(
        isinstance(item, dict) and item.get("job") == dependency and item.get("artifacts") is True
        for item in job.get("needs", [])
    )


def test_docker_context_excludes_generated_python_package_metadata():
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "**/*.egg-info" in dockerignore
    assert "COPY --chown=10001:10001 src/ /app/src/" in dockerfile
    assert Path("src/museecho.egg-info").match("**/*.egg-info")


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


def test_dual_ci_definitions_include_executable_tests_and_gitlab_unit_test_job():
    github = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    gitlab = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))

    github_jobs = github["jobs"]
    assert {"quality", "e2e", "distribution"}.issubset(github_jobs)
    quality_commands = "\n".join(
        str(step.get("run", "")) for step in github_jobs["quality"]["steps"]
    )
    assert "uv run pytest -q --basetemp tmp/pytest-ci" in quality_commands
    assert "npm --prefix frontend test" in quality_commands

    unit_test = gitlab["unit-test"]
    assert unit_test["stage"] == "test"
    assert unit_test["script"] == ["uv run pytest -q --basetemp tmp/pytest-ci"]
    assert {"lint", "unit-test", "frontend", "e2e", "secret-scan"}.issubset(gitlab)


def test_readme_cold_start_contract_covers_locked_setup_https_health_and_cleanup():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for required in (
        "uv sync --frozen --extra dev",
        "npm.cmd ci",
        "npm.cmd --prefix frontend ci",
        "docker compose --profile production config --quiet",
        "docker compose --profile production up -d --wait --no-build",
        "curl --fail --silent --show-error --insecure https://localhost:8443/api/health",
        "docker compose --profile production down --volumes",
        "docker compose --profile development up --build --detach --wait app-dev gateway-dev",
        "curl.exe --fail --silent --show-error --insecure https://localhost:4173/api/health",
        "scripts\\development-smoke.ps1",
        "scripts\\container-smoke.ps1",
    ):
        assert required in readme


def test_process_documents_anchor_evidence_and_share_current_audit_status():
    plan = (ROOT / "PLAN.md").read_text(encoding="utf-8")
    agent_log = (ROOT / "AGENT_LOG.md").read_text(encoding="utf-8")
    blockers = (ROOT / "BLOCKERS.md").read_text(encoding="utf-8")
    reflection_notes = (ROOT / "REFLECTION_NOTES.md").read_text(encoding="utf-8")
    task22_report = (ROOT / ".superpowers/sdd/PLAN/task-22-report.md").read_text(encoding="utf-8")
    task20 = (ROOT / "TASK20_HANDOFF.md").read_text(encoding="utf-8")
    deployment = (ROOT / "DEPLOYMENT_EVIDENCE.md").read_text(encoding="utf-8")
    audit = load_audit(ROOT / "SPEC.md", ROOT / "docs/audits/FUNCTIONAL_AUDIT.md")
    counts = Counter(item.verdict for item in audit.items)
    assert (counts["PASS"], counts["PARTIAL"], counts["FAIL"]) == (28, 12, 0)
    current_status = f"{counts['PASS']} PASS / {counts['PARTIAL']} PARTIAL / {counts['FAIL']} FAIL"

    assert "1047ce242884b6ba83a525524e88dcc44ab76a69" in plan
    assert "4 个真实 HTTPS 浏览器 E2E" in agent_log
    assert "11.201268" in agent_log
    assert "远端 GitHub Actions/GitLab CI 仍未运行" in task20
    assert "No public URL is claimed." in deployment
    assert "## Pending real-server evidence" in deployment

    for name, document in (
        ("REFLECTION_NOTES.md", reflection_notes),
        ("AGENT_LOG.md", agent_log),
        ("BLOCKERS.md", blockers),
        ("PLAN.md", plan),
        ("task-22-report.md", task22_report),
    ):
        assert current_status in document, f"{name} lacks current audit status {current_status}"

    assert "保持 6 个 PARTIAL" not in reflection_notes
    pre_review_report = task22_report.split("## Review fix round 1/5", maxsplit=1)[0]
    assert "The final verification" not in pre_review_report
    assert "pristine final run" not in pre_review_report
    legacy_statuses = ("PASS=34 PARTIAL=6 FAIL=0", "34 PASS / 6 PARTIAL / 0 FAIL")
    assert any(status in task22_report for status in legacy_statuses)
    for legacy_status in legacy_statuses:
        for match in re.finditer(re.escape(legacy_status), task22_report):
            context = task22_report[max(0, match.start() - 240) : match.end() + 240].lower()
            assert "pre-review" in context
            assert "superseded" in context
