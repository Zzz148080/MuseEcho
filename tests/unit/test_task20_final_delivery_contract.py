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
    quality_checkout = next(
        step
        for step in github_jobs["quality"]["steps"]
        if step.get("uses") == "actions/checkout@v7"
    )
    assert quality_checkout["with"]["fetch-depth"] == 0
    quality_commands = "\n".join(
        str(step.get("run", "")) for step in github_jobs["quality"]["steps"]
    )
    assert "uv run python -m pytest -q --basetemp .pytest-ci" in quality_commands
    assert "npm --prefix frontend test" in quality_commands

    unit_test = gitlab["unit-test"]
    assert unit_test["stage"] == "test"
    assert unit_test["script"] == ["uv run python -m pytest -q --basetemp .pytest-ci"]
    assert {"lint", "unit-test", "frontend", "e2e", "secret-scan"}.issubset(gitlab)


def test_github_actions_use_node24_capable_majors_without_an_insecure_node_fallback():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    github = yaml.safe_load(workflow)
    uses = [
        step["uses"] for job in github["jobs"].values() for step in job["steps"] if "uses" in step
    ]

    assert uses.count("actions/checkout@v7") == 3
    assert uses.count("actions/setup-python@v6") == 2
    assert uses.count("actions/setup-node@v6") == 2
    assert not any(
        item.startswith("actions/checkout@") and item != "actions/checkout@v7" for item in uses
    )
    assert not any(
        item.startswith("actions/setup-python@") and item != "actions/setup-python@v6"
        for item in uses
    )
    assert not any(
        item.startswith("actions/setup-node@") and item != "actions/setup-node@v6" for item in uses
    )
    assert "ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION" not in workflow
    assert workflow.count("python-version: 3.12.13") == 2
    assert workflow.count("node-version: 22.23.0") == 2


def test_distribution_uses_buildx_and_node24_artifact_without_weakening_evidence():
    github = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = github["jobs"]["distribution"]["steps"]
    uses = [step["uses"] for step in steps if "uses" in step]
    checkout_index = next(
        index for index, step in enumerate(steps) if step.get("uses") == "actions/checkout@v7"
    )
    buildx_indexes = [
        index
        for index, step in enumerate(steps)
        if step.get("uses") == "docker/setup-buildx-action@v4"
    ]
    build_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Validate and build both non-root images"
    )
    artifact_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Retain image vulnerability evidence"
    )
    buildx = steps[buildx_indexes[0]]
    build_commands = str(steps[build_index]["run"])

    assert uses.count("docker/setup-buildx-action@v4") == 1
    assert uses.count("actions/upload-artifact@v7") == 1
    assert not any(
        item.startswith("docker/setup-buildx-action@") and item != "docker/setup-buildx-action@v4"
        for item in uses
    )
    assert not any(
        item.startswith("actions/upload-artifact@") and item != "actions/upload-artifact@v7"
        for item in uses
    )
    assert checkout_index < buildx_indexes[0] < build_index < artifact_index
    assert buildx["with"]["driver"] == "docker-container"
    assert buildx["with"]["use"] is True
    assert (
        "type=docker,name=museecho-app:ci,dest=tmp/image-security/museecho-app.tar"
        in build_commands
    )
    assert (
        "type=docker,name=museecho-gateway:ci,dest=tmp/image-security/museecho-gateway.tar"
        in build_commands
    )
    assert "verify_release_identity.py record" in build_commands
    assert steps[artifact_index]["with"]["path"] == "tmp/image-security/"


def test_github_quality_always_removes_its_exact_pytest_temp_root_before_secret_scan():
    github = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = github["jobs"]["quality"]["steps"]
    test_step_indexes = [
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Unit and integration tests"
    ]
    cleanup_indexes = [
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Clean CI pytest temporary root"
    ]
    secret_scan_indexes = [
        index for index, step in enumerate(steps) if step.get("name") == "Repository secret scan"
    ]

    assert len(test_step_indexes) == len(cleanup_indexes) == len(secret_scan_indexes) == 1
    test_step_index = test_step_indexes[0]
    cleanup_index = cleanup_indexes[0]
    secret_scan_index = secret_scan_indexes[0]
    cleanup = steps[cleanup_index]

    assert "uv run python -m pytest -q --basetemp .pytest-ci" in steps[test_step_index]["run"]
    assert test_step_index < cleanup_index < secret_scan_index
    assert cleanup["if"] == "always()"
    assert cleanup["run"] == "rm -rf -- .pytest-ci"


def test_container_pytest_synthetic_harness_exits_zero_after_expected_failure_mutation():
    shell = shutil.which("pwsh") or shutil.which("powershell.exe")
    assert shell is not None
    script = ROOT / "scripts" / "test-container-pytest.ps1"
    command = f"& '{str(script).replace("'", "''")}'; exit $LASTEXITCODE"

    completed = subprocess.run(
        [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Container pytest synthetic cleanup tests passed." in completed.stdout


def test_container_contract_synthetic_harness_exits_zero_after_expected_failure_mutation():
    shell = shutil.which("pwsh") or shutil.which("powershell.exe")
    assert shell is not None
    script = ROOT / "scripts" / "test-container-contract.ps1"
    command = f"& '{str(script).replace("'", "''")}'; exit $LASTEXITCODE"

    completed = subprocess.run(
        [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Container contract synthetic tests passed." in completed.stdout


def test_container_contract_synthetic_harness_uses_an_executable_platform_fake_docker():
    script = (ROOT / "scripts" / "test-container-contract.ps1").read_text(encoding="utf-8")

    assert "$isWindowsPlatform = $env:OS -eq 'Windows_NT'" in script
    assert "if ($isWindowsPlatform) { 'docker.cmd' } else { 'docker' }" in script
    assert "if ($isWindowsPlatform) { 'curl.cmd' } else { 'curl' }" in script
    assert "[Text.UTF8Encoding]::new($false)" in script
    assert "& chmod 700 $fakeDocker" in script
    assert "& chmod 700 $fakeCurl" in script
    assert '$env:PATH = "$fakeBin$([IO.Path]::PathSeparator)$savedPath"' in script


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
