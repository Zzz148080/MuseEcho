from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import time
import tomllib
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from scripts.check_acceptance_matrix import load_audit

ROOT = Path(__file__).resolve().parents[2]
CURRENT_STATUS_START = "<!-- TASK24-CURRENT-STATUS:START -->"
CURRENT_STATUS_END = "<!-- TASK24-CURRENT-STATUS:END -->"


def _require_powershell() -> str:
    shell = shutil.which("pwsh") or shutil.which("powershell.exe")
    if shell is None:
        pytest.skip("PowerShell synthetic harness requires a PowerShell host")
    return shell


def _current_status_block(document: str, *, name: str) -> str:
    assert document.count(CURRENT_STATUS_START) == 1, f"{name} lacks one current-status start"
    assert document.count(CURRENT_STATUS_END) == 1, f"{name} lacks one current-status end"
    before_end, separator, after_end = document.partition(CURRENT_STATUS_END)
    assert separator and CURRENT_STATUS_START in before_end, f"{name} has invalid status markers"
    assert CURRENT_STATUS_START not in after_end, f"{name} has nested status markers"
    return before_end.rsplit(CURRENT_STATUS_START, maxsplit=1)[1]


def test_isolated_project_build_backend_is_exactly_constrained_by_the_lock():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    locked = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))

    assert project["build-system"]["requires"] == ["setuptools==80.9.0"]
    assert project["tool"]["uv"]["build-constraint-dependencies"] == ["setuptools==80.9.0"]
    assert locked["manifest"]["build-constraints"] == [
        {"name": "setuptools", "specifier": "==80.9.0"}
    ]


def _needs_artifact(job: dict[str, Any], dependency: str) -> bool:
    return any(
        isinstance(item, dict) and item.get("job") == dependency and item.get("artifacts") is True
        for item in job.get("needs", [])
    )


def test_docker_context_excludes_generated_python_package_metadata():
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "**/*.egg-info" in dockerignore
    assert "COPY src/ /app/src/" in dockerfile
    assert "COPY --chown=10001:10001 src/ /app/src/" not in dockerfile
    assert "PYTHONPATH=/app/src" not in dockerfile
    assert Path("src/museecho.egg-info").match("**/*.egg-info")


def test_app_image_runs_the_installed_first_party_release_distribution():
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker is unavailable for the production packaging boundary")
    daemon = subprocess.run(
        [docker, "version", "--format", "{{.Server.Version}}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )
    assert daemon.returncode == 0, daemon.stdout + daemon.stderr

    image = f"museecho-app:packaging-contract-{os.getpid()}"
    try:
        built = subprocess.run(
            [docker, "build", "--target", "app", "--tag", image, "."],
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=600,
        )
        assert built.returncode == 0, built.stdout + built.stderr

        probe = subprocess.run(
            [
                docker,
                "run",
                "--rm",
                "--network",
                "none",
                image,
                "/app/.venv/bin/python",
                "-c",
                (
                    "import importlib.metadata as m, museecho, os; "
                    "d=m.distribution('museecho'); "
                    "assert d.version == '0.1.0'; "
                    "assert d.files; "
                    "assert any(str(p).endswith('museecho/cli.py') for p in d.files); "
                    "assert 'site-packages' in museecho.__file__; "
                    "assert os.geteuid() == 10001; "
                    "assert not {'pytest', 'ruff', 'mypy'} & "
                    "{d.metadata['Name'].lower() for d in m.distributions()}"
                ),
            ],
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        assert probe.returncode == 0, probe.stdout + probe.stderr
    finally:
        subprocess.run(
            [docker, "image", "rm", "--force", image],
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )


def test_packaging_boundary_fails_closed_when_a_present_docker_client_is_broken(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(shutil, "which", lambda command: "docker" if command == "docker" else None)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0], returncode=41, stdout="", stderr="synthetic Docker failure"
        ),
    )

    with pytest.raises(AssertionError, match="synthetic Docker failure"):
        test_app_image_runs_the_installed_first_party_release_distribution()


def _read_app_dev_health(compose_command: list[str]) -> dict[str, object] | None:
    completed = subprocess.run(
        [
            *compose_command,
            "exec",
            "-T",
            "app-dev",
            "python",
            "-c",
            (
                "import urllib.request; "
                "print(urllib.request.urlopen("
                "'http://127.0.0.1:8000/api/health', timeout=2).read().decode())"
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        return None
    try:
        response = json.loads(completed.stdout.strip())
    except json.JSONDecodeError:
        return None
    return response if isinstance(response, dict) else None


def _wait_for_app_dev_health(
    compose_command: list[str],
    predicate: Callable[[dict[str, object]], bool],
    *,
    timeout: float,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_response: dict[str, object] | None = None
    while time.monotonic() < deadline:
        last_response = _read_app_dev_health(compose_command)
        if last_response is not None and predicate(last_response):
            return last_response
        time.sleep(0.5)
    pytest.fail(f"app-dev health did not reach expected state; last response: {last_response!r}")


def test_app_dev_reloads_mounted_source_changes_across_the_compose_process_boundary(
    tmp_path: Path,
):
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker is unavailable for the development source boundary")

    source = tmp_path / "src"
    shutil.copytree(ROOT / "src", source)
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "audio-kek").write_text(
        "a2tra2tra2tra2tra2tra2tra2tra2tra2tra2tra2s=",
        encoding="ascii",
    )
    (secrets / "audio-kek").chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    project = f"museecho-reload-{os.getpid()}-{uuid.uuid4().hex[:12]}"
    image = f"museecho-app:{project}"
    override = tmp_path / "compose.override.yaml"
    override.write_text(
        yaml.safe_dump(
            {
                "services": {
                    "app-dev": {
                        "image": image,
                        "volumes": [
                            {
                                "type": "bind",
                                "source": str(source),
                                "target": "/app/src",
                                "read_only": True,
                            },
                            {
                                "type": "bind",
                                "source": str(secrets),
                                "target": "/run/secrets",
                                "read_only": True,
                            },
                        ],
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    compose_command = [
        docker,
        "compose",
        "--project-name",
        project,
        "-f",
        str(ROOT / "compose.yaml"),
        "-f",
        str(override),
        "--profile",
        "development",
    ]
    down: subprocess.CompletedProcess[str] | None = None
    try:
        built = subprocess.run(
            [*compose_command, "build", "app-dev"],
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=600,
        )
        assert built.returncode == 0, built.stdout + built.stderr
        started = subprocess.run(
            [*compose_command, "up", "--detach", "--wait", "app-dev"],
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=120,
        )
        if started.returncode != 0:
            logs = subprocess.run(
                [*compose_command, "logs", "--no-color", "app-dev"],
                cwd=ROOT,
                capture_output=True,
                check=False,
                text=True,
                timeout=30,
            )
            pytest.fail(started.stdout + started.stderr + logs.stdout + logs.stderr)
        baseline = _wait_for_app_dev_health(
            compose_command,
            lambda response: response.get("status") == "ready",
            timeout=30,
        )
        assert "reload_probe" not in baseline

        marker = "round15-reloaded-source-marker"
        app_module = source / "museecho" / "app.py"
        app_text = app_module.read_text(encoding="utf-8")
        needle = '        content: dict[str, object] = {\n            "status": status_value,'
        replacement = (
            "        content: dict[str, object] = {\n"
            f'            "reload_probe": {marker!r},\n'
            '            "status": status_value,'
        )
        assert needle in app_text
        app_module.write_text(app_text.replace(needle, replacement, 1), encoding="utf-8")

        reloaded = _wait_for_app_dev_health(
            compose_command,
            lambda response: response.get("reload_probe") == marker,
            timeout=45,
        )
        assert reloaded["reload_probe"] == marker
    finally:
        down = subprocess.run(
            [*compose_command, "down", "--volumes", "--remove-orphans"],
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=120,
        )
        subprocess.run(
            [docker, "image", "rm", "--force", image],
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
    assert down is not None
    assert down.returncode == 0, down.stdout + down.stderr


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


def test_github_course_ci_is_executable_and_retained_gitlab_has_unit_test_job():
    github = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    gitlab = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    course_update = (ROOT / "COURSE_REQUIREMENT_UPDATE.md").read_text(encoding="utf-8")

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
    assert "本次课程提交只要求 GitHub 仓库与 GitHub CI" in course_update
    assert "不再要求 NJU GitLab 仓库或 GitLab Pipeline" in course_update


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
    assert steps[artifact_index]["if"] == "always()"
    assert steps[artifact_index]["continue-on-error"] is True

    blocking_steps = {
        "Validate and build both non-root images",
        "Capture unsuppressed full-image vulnerability JSON",
        "Record exact app package ownership and runtime probes",
        "Audit exact built-image component licenses",
        "Audit exact app findings and emit OpenVEX",
        "Enforce audited app VEX and unsuppressed gateway gate",
    }
    for step in steps[:artifact_index]:
        if step.get("name") in blocking_steps:
            assert step.get("continue-on-error") is not True


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
    shell = _require_powershell()
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
    shell = _require_powershell()
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


def test_development_smoke_synthetic_harness_exercises_the_platform_default_curl_command():
    shell = _require_powershell()
    script = ROOT / "scripts" / "test-development-smoke.ps1"
    command = f"& '{str(script).replace("'", "''")}'; if ($?) {{ exit 0 }} else {{ exit 1 }}"

    completed = subprocess.run(
        [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Development smoke synthetic lifecycle tests passed." in completed.stdout


def test_development_smoke_synthetic_harness_exits_zero_after_expected_failures():
    shell = _require_powershell()
    script = ROOT / "scripts" / "test-development-smoke.ps1"
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
    assert "Development smoke synthetic lifecycle tests passed." in completed.stdout


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
    delivery_report = (ROOT / "DELIVERY_REPORT.md").read_text(encoding="utf-8")
    course_checklist = (ROOT / "COURSE_DELIVERY_CHECKLIST.md").read_text(encoding="utf-8")
    deployment = (ROOT / "DEPLOYMENT_EVIDENCE.md").read_text(encoding="utf-8")
    audit = load_audit(ROOT / "SPEC.md", ROOT / "docs/audits/FUNCTIONAL_AUDIT.md")
    counts = Counter(item.verdict for item in audit.items)
    assert (counts["PASS"], counts["PARTIAL"], counts["FAIL"]) == (36, 4, 0)
    current_status = f"{counts['PASS']} PASS / {counts['PARTIAL']} PARTIAL / {counts['FAIL']} FAIL"

    assert "1047ce242884b6ba83a525524e88dcc44ab76a69" in plan
    assert "4 个真实 HTTPS 浏览器 E2E" in agent_log
    assert "11.201268" in agent_log
    assert "Historical Task 24 implementation evidence only" in delivery_report
    assert "recorded separately by DEL-012" in delivery_report
    assert "0674f74f4097e46cee98c4715a62ad5aa55101cf" in course_checklist
    assert "No public URL is claimed." in deployment
    assert "## Pending real-server evidence" in deployment

    current_blocks = {
        name: _current_status_block(document, name=name)
        for name, document in (
            ("REFLECTION_NOTES.md", reflection_notes),
            ("AGENT_LOG.md", agent_log),
            ("BLOCKERS.md", blockers),
            ("PLAN.md", plan),
        )
    }
    for name, current_block in current_blocks.items():
        if name == "REFLECTION_NOTES.md":
            continue
        assert current_status in current_block, (
            f"{name} lacks current audit status {current_status}"
        )
        assert "28 PASS / 12 PARTIAL / 0 FAIL" not in current_block
        assert "CURRENT-BROWSER-E2E" not in current_block
        assert not re.search(r"GitHub.{0,80}(?:pending|待推送|待.*结果)", current_block, re.I)

    blockers_current = current_blocks["BLOCKERS.md"]
    for required in (
        "GitLab",
        "BLK-STUDENT-MANUAL",
        "BLK-CONTROLLER-BROWSER",
        "BLK-FORMAL-OFFLINE-BUILD",
    ):
        assert required in blockers_current
    assert "31966788273" in blockers_current
    assert "0674f74f4097e46cee98c4715a62ad5aa55101cf" in blockers_current

    assert "保持 6 个 PARTIAL" not in reflection_notes
    pre_review_report = task22_report.split("## Review fix round 1/5", maxsplit=1)[0]
    assert "The final verification" not in pre_review_report
    assert "pristine final run" not in pre_review_report
    legacy_statuses = ("PASS=34 PARTIAL=6 FAIL=0", "34 PASS / 6 PARTIAL / 0 FAIL")
    assert any(status in task22_report for status in legacy_statuses)
    historical_report = re.sub(
        rf"{re.escape(CURRENT_STATUS_START)}.*?{re.escape(CURRENT_STATUS_END)}",
        "",
        task22_report,
        flags=re.DOTALL,
    )
    for legacy_status in legacy_statuses:
        for match in re.finditer(re.escape(legacy_status), historical_report):
            context = historical_report[max(0, match.start() - 240) : match.end() + 240].lower()
            assert "pre-review" in context
            assert "superseded" in context
