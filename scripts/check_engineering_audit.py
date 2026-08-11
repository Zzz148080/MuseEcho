#!/usr/bin/env python3
"""Fail-closed validation for the tracked Task 23 engineering audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from contextlib import chdir
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

if __package__:
    from scripts.image_vulnerability_audit import audit_image, build_runtime_boundary_manifest
    from scripts.verify_release_identity import audit_release_identity, image_id_from_tar
else:
    from image_vulnerability_audit import audit_image, build_runtime_boundary_manifest
    from verify_release_identity import audit_release_identity, image_id_from_tar

EXPECTED_DOMAINS = (
    "architecture-boundaries",
    "types-static",
    "dependencies-licenses",
    "runtime-image-vulnerabilities",
    "performance-resources",
    "concurrency-async-subprocesses",
    "access-control-csrf-cors",
    "upload-parsing",
    "secrets-logging-errors",
    "data-lifecycle-backup",
    "observability",
    "test-isolation",
    "accessibility",
    "reproducible-build-ci-release-identity",
    "operations-recovery",
)

SEVERITIES = frozenset({"Critical", "High", "Medium", "Low"})
STATUSES = frozenset({"OPEN", "FIXED", "ACCEPTED", "BLOCKED"})
EXECUTED_KINDS = frozenset({"RED_COMMAND", "CURRENT_COMMAND"})
EVIDENCE_KINDS = EXECUTED_KINDS | {"EXTERNAL_NOT_RUN", "FILE_EXISTENCE"}

# These are the real findings discovered during Task 23. Keeping this inventory in
# executable code prevents an audit edit from deleting or silently downgrading one.
FINDING_CONTRACTS = {
    "ENG-001": ("reproducible-build-ci-release-identity", "High", "FIXED"),
    "ENG-002": ("reproducible-build-ci-release-identity", "High", "FIXED"),
    "ENG-003": ("operations-recovery", "High", "FIXED"),
    "ENG-004": ("reproducible-build-ci-release-identity", "Medium", "FIXED"),
    "ENG-005": ("observability", "Medium", "FIXED"),
    "ENG-006": ("accessibility", "Medium", "BLOCKED"),
    "ENG-007": ("reproducible-build-ci-release-identity", "Medium", "BLOCKED"),
    "ENG-008": ("operations-recovery", "Medium", "BLOCKED"),
    "ENG-009": ("reproducible-build-ci-release-identity", "High", "FIXED"),
    "ENG-010": ("reproducible-build-ci-release-identity", "Medium", "BLOCKED"),
}

SECURITY_MANIFEST_PATH = "docs/audits/evidence/task23-security-manifest.json"
SECURITY_MANIFEST_SHA256 = "ac75e92cf00bb04d13bcd8097b166ec7558088960afda9f0aa239d2c0ebfc0b6"

SECURITY_MATERIAL_FILENAMES = (
    "app-raw-review1.json",
    "app-package-files-review1.json",
    "app-inventory-review1.json",
    "app-openvex-review1.json",
    "museecho-app-task23-review1.tar",
    "gateway-raw-review1.json",
    "museecho-gateway-task20.tar",
    "release-images-review1.json",
)

SECURITY_MATERIAL_DIGEST_PATHS = {
    "app-raw-review1.json": ("app", "raw_sha256"),
    "app-package-files-review1.json": ("app", "package_files_sha256"),
    "app-inventory-review1.json": ("app", "inventory_sha256"),
    "app-openvex-review1.json": ("app", "vex_sha256"),
    "museecho-app-task23-review1.tar": ("app", "tar_sha256"),
    "gateway-raw-review1.json": ("gateway", "raw_sha256"),
    "museecho-gateway-task20.tar": ("gateway", "tar_sha256"),
    "release-images-review1.json": ("release_identity_sha256",),
}

FIXED_FINDING_EVIDENCE_IDS = {
    "ENG-001": ("E002", "E003"),
    "ENG-002": ("E004", "E005"),
    "ENG-003": ("E006", "E007"),
    "ENG-004": ("E008", "E009", "E019"),
    "ENG-005": ("E010", "E011"),
    "ENG-009": ("E033", "E034", "E022"),
    "ENG-010": ("E035", "E036"),
}

SECURITY_DOMAIN_EVIDENCE_IDS = ("E020", "E021", "E022", "E023", "E024", "E025")

_TRIVY_PREFIX = (
    "docker run --rm --network none "
    "--tmpfs /root/.cache/trivy:rw,nosuid,nodev,size=512m "
    "--mount type=bind,source=TASK20_TRIVY_DB,target=/root/.cache/trivy/db,readonly "
    "--mount type=bind,source=TASK23_EVIDENCE,target=/evidence aquasec/trivy:0.70.0 image "
)

# This complete independent inventory prevents an audit author from replacing a
# real RED/GREEN or security gate with another command while keeping exit codes.
FIXED_EVIDENCE_CONTRACTS = {
    "E002": (
        "RED_COMMAND",
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -File "
        "tests/deploy/test_shell_line_endings.ps1 with invalid syntax in the last "
        "fresh-checkout file",
        "tests/deploy/test_shell_line_endings.ps1",
        "Old multi-file bash -n invocation accepted the invalid final file",
    ),
    "E003": (
        "CURRENT_COMMAND",
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -File "
        "tests/deploy/test_shell_line_endings.ps1",
        "tests/deploy/test_shell_line_endings.ps1",
        "LF checks passed and bash -n independently parsed 8 fresh-checkout files",
    ),
    "E004": (
        "RED_COMMAND",
        "python scripts/verify_release_identity.py verify --manifest manifest-only.json",
        "tests/unit/test_release_identity.py",
        "Manifest-only verify returned success without any comparison class",
    ),
    "E005": (
        "CURRENT_COMMAND",
        ".venv/Scripts/python.exe -m pytest tests/unit/test_release_identity.py -q",
        "tests/unit/test_release_identity.py",
        "10 passed; verify rejects an empty comparison inventory while tar plus scan and "
        "optional image-id remain valid",
    ),
    "E006": (
        "RED_COMMAND",
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -File "
        "scripts/test-development-smoke.ps1 against the old smoke",
        "scripts/test-development-smoke.ps1",
        "Partial compose startup skipped down and cleanup failure could replace or hide "
        "the primary failure",
    ),
    "E007": (
        "CURRENT_COMMAND",
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -File "
        "scripts/test-development-smoke.ps1",
        "scripts/test-development-smoke.ps1",
        "Synthetic partial-start, primary-only, cleanup-only, and combined failure "
        "reporting passed",
    ),
    "E008": (
        "RED_COMMAND",
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -File "
        "scripts/test-container-contract.ps1 against the old smoke",
        "scripts/test-container-contract.ps1",
        "No explicit no-build path, trusted image identity validation, runtime identity "
        "check, or repeated up --no-build",
    ),
    "E009": (
        "CURRENT_COMMAND",
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -File "
        "scripts/test-container-contract.ps1",
        "scripts/test-container-contract.ps1",
        "Synthetic contract rejected wrong, duplicate, swapped, and runtime-drifted image "
        "identities and required --no-build on both starts",
    ),
    "E010": (
        "RED_COMMAND",
        ".venv/Scripts/python.exe -m pytest tests/unit/test_observability.py -q",
        "tests/unit/test_observability.py",
        "ModuleNotFoundError: museecho.observability",
    ),
    "E011": (
        "CURRENT_COMMAND",
        ".venv/Scripts/python.exe -m pytest tests/unit/test_observability.py "
        "tests/api/test_health.py tests/integration/test_runtime_app.py -q",
        "tests/unit/test_observability.py",
        "Safe request and background failure logs, stable 500 responses, metrics, "
        "liveness/readiness, cleanup degradation and recovery passed",
    ),
    "E019": (
        "CURRENT_COMMAND",
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -File "
        "scripts/container-smoke.ps1 -NoBuild -ReleaseManifest "
        "docs/audits/evidence/task23-security-manifest.json "
        "-ExpectedAppDaemonImageId "
        "sha256:56995ceef3cbe55fc422ce95587198a225a8c04e20e45d4fb844c6c4c3d56a04 "
        "-ExpectedAppConfigImageId "
        "sha256:7884992579acdf4bbd8a01071bf6d86cda499ac7ae4d15b0db4be56f7dd5d62d "
        "-ExpectedGatewayDaemonImageId "
        "sha256:2235e208dd7d8568c735ba19f1969644384626296eaff5cabb41acfaed86c547 "
        "-ExpectedGatewayConfigImageId "
        "sha256:8cc0429e45fd48c911a92fd8504c1f3c14daccb0fee8a24529d72af51b0b4053",
        "scripts/container-smoke.ps1",
        "Trusted app and gateway daemon/config identities, both runtime container "
        "identities, real WAV, restart, ciphertext, history, and cleanup passed without build",
    ),
    "E020": (
        "CURRENT_COMMAND",
        _TRIVY_PREFIX + "--input /evidence/museecho-app-task23-review1.tar --scanners vuln "
        "--severity HIGH,CRITICAL --format json --output /evidence/app-raw-review1.json "
        "--skip-db-update --skip-java-db-update --skip-version-check --offline-scan",
        SECURITY_MANIFEST_PATH,
        "Trivy 0.70.0 and fixed DB found app occurrences=181 distinct-cves=67 "
        "critical=12 high=169; raw SHA and tuple SHA fixed",
    ),
    "E021": (
        "CURRENT_COMMAND",
        _TRIVY_PREFIX + "--input /evidence/museecho-gateway-task20.tar --scanners vuln "
        "--severity HIGH,CRITICAL --format json --output /evidence/gateway-raw-review1.json "
        "--skip-db-update --skip-java-db-update --skip-version-check --offline-scan",
        SECURITY_MANIFEST_PATH,
        "Gateway raw occurrences=0 and distinct-cves=0; exact config and raw SHA fixed",
    ),
    "E022": (
        "CURRENT_COMMAND",
        "docker run --rm --network none --read-only --cap-drop ALL "
        "--security-opt no-new-privileges --workdir /workspace "
        "--mount type=bind,source=REPOSITORY,target=/workspace,readonly "
        "--mount type=bind,source=TASK23_EVIDENCE,target=/evidence "
        "--entrypoint /app/.venv/bin/python museecho-app:task23-review1 "
        "/workspace/scripts/image_vulnerability_audit.py "
        "--scan /evidence/app-raw-review1.json "
        "--package-files /evidence/app-package-files-review1.json "
        "--policy /workspace/scripts/image-vulnerability-policy.json "
        "--release-identity /evidence/release-images-review1.json --image-name app "
        "--vex-output /evidence/app-openvex-review1.json "
        "--inventory-output /evidence/app-inventory-review1.json",
        SECURITY_MANIFEST_PATH,
        "Exact raw tuple, package ownership, current clean runtime boundary, 67 reviewed "
        "statements, and release identity passed",
    ),
    "E023": (
        "CURRENT_COMMAND",
        _TRIVY_PREFIX + "--input /evidence/museecho-app-task23-review1.tar --scanners vuln "
        "--severity HIGH,CRITICAL --exit-code 1 --vex /evidence/app-openvex-review1.json "
        "--skip-db-update --skip-java-db-update --skip-version-check --offline-scan",
        SECURITY_MANIFEST_PATH,
        "App VEX gate residual High/Critical=0",
    ),
    "E024": (
        "CURRENT_COMMAND",
        _TRIVY_PREFIX + "--input /evidence/museecho-gateway-task20.tar --scanners vuln "
        "--severity HIGH,CRITICAL --exit-code 1 --skip-db-update --skip-java-db-update "
        "--skip-version-check --offline-scan",
        SECURITY_MANIFEST_PATH,
        "Unsuppressed gateway gate High/Critical=0",
    ),
    "E025": (
        "CURRENT_COMMAND",
        "python scripts/verify_release_identity.py verify "
        "--manifest tmp/task23-engineering/release-images-review1.json "
        "--tar app=tmp/task23-engineering/museecho-app-task23-review1.tar "
        "--tar gateway=tmp/task23-engineering/museecho-gateway-task20.tar "
        "--scan app=tmp/task23-engineering/app-raw-review1.json "
        "--scan gateway=tmp/task23-engineering/gateway-raw-review1.json",
        SECURITY_MANIFEST_PATH,
        "App and gateway config IDs, tar SHA256 values, and raw scan ImageIDs agree",
    ),
    "E033": (
        "RED_COMMAND",
        ".venv/Scripts/python.exe -m pytest "
        "tests/unit/test_task20_final_delivery_contract.py::"
        "test_docker_context_excludes_generated_python_package_metadata -q",
        "tests/unit/test_task20_final_delivery_contract.py",
        "1 failed because .dockerignore did not exclude gitignored egg-info metadata",
    ),
    "E034": (
        "CURRENT_COMMAND",
        ".venv/Scripts/python.exe -m pytest "
        "tests/unit/test_task20_final_delivery_contract.py::"
        "test_docker_context_excludes_generated_python_package_metadata "
        "tests/unit/test_image_vulnerability_audit.py::"
        "test_committed_policy_matches_clean_runtime_boundary_without_generated_metadata "
        "tests/unit/test_image_vulnerability_audit.py::"
        "test_audit_rejects_schema_probe_or_complete_runtime_boundary_drift -q",
        "tests/unit/test_image_vulnerability_audit.py",
        "Clean Docker context contract passed and 6 policy/runtime drift mutations passed; "
        "derived image contains no egg-info",
    ),
    "E035": (
        "RED_COMMAND",
        "docker build --pull=false --network none --tag museecho-app:task23-formal-offline .",
        "Dockerfile",
        "Formal current-source Dockerfile build exited 1 because locked pip and apt "
        "BuildKit layers were unavailable with network disabled",
    ),
    "E036": (
        "EXTERNAL_NOT_RUN",
        "NOT RUN: formal current-source Dockerfile build requires the complete locked "
        "BuildKit pip and apt cache under network none",
        "Dockerfile",
        "Controlled current-source derivative is audit-only and is not a release artifact",
    ),
}

SECURITY_MANIFEST_CONTRACT = {
    "app": {
        "audit_exit": 0,
        "config_image_id": (
            "sha256:7884992579acdf4bbd8a01071bf6d86cda499ac7ae4d15b0db4be56f7dd5d62d"
        ),
        "critical_occurrences": 12,
        "daemon_image_id": (
            "sha256:56995ceef3cbe55fc422ce95587198a225a8c04e20e45d4fb844c6c4c3d56a04"
        ),
        "distinct_cves": 67,
        "high_occurrences": 169,
        "inventory_sha256": ("a4efb700178df3003575a8ca520189207f3d12b815815dd6e034d8cc3ca12b7d"),
        "occurrences": 181,
        "package_files_sha256": (
            "0568117b227db2891f82aab0022e5b4bc65c1eabfa5e3f5e282aa6bc746ce470"
        ),
        "raw_sha256": "0be1e5851afeb8e28ab625e8668b1ca838bb01601ca25104c2668e044ae64595",
        "tar_sha256": "c50ce705594810b21852ff2358c75d221e6ebc97de3396ff4f3408017792a147",
        "tuple_sha256": "4ab629f0f3b74d2357fcf19d195831c37adbee645d881e9a3fb4605224de35ba",
        "vex_gate_exit": 0,
        "vex_sha256": "76b539cb0b71dbb6339150f322eaf049207d862d66a209fdb97bf64245c7afaa",
    },
    "boundary": {
        "build_kind": "controlled_current_source_derivation_from_task20_final",
        "formal_dockerfile_build_exit": 1,
        "formal_dockerfile_build_reason": (
            "locked pip and apt BuildKit layers unavailable under network none"
        ),
        "policy_sha256": "1e42cb86c1d7aed4ea21142654d0ebcfde41b3e7544238ed7c90b4c231502d1c",
        "runtime_boundary_sha256": (
            "26828f41334ab92e09d597e708676b29af1e1792b740bb302af5c9075dffd7dc"
        ),
        "task20_base_daemon_image_id": (
            "sha256:96cd900d6c17c360b01665362330aca8ef032b0d4d1f140659a52265ce47f39c"
        ),
    },
    "gateway": {
        "config_image_id": (
            "sha256:8cc0429e45fd48c911a92fd8504c1f3c14daccb0fee8a24529d72af51b0b4053"
        ),
        "daemon_image_id": (
            "sha256:2235e208dd7d8568c735ba19f1969644384626296eaff5cabb41acfaed86c547"
        ),
        "distinct_cves": 0,
        "gate_exit": 0,
        "occurrences": 0,
        "raw_sha256": "64513e95a8ac9e5b9bcdf9a274a5e3108f08dbb6dbdb2ad97601c8eed7bbfd7d",
        "tar_sha256": "dd5dba88b52d3765c43ca1570d30307deb7a8c274f873cfd6258c4efa4fc820b",
    },
    "observed_at_utc": {
        "app_audit": "2026-08-11T13:13:30Z",
        "app_raw": "2026-08-11T13:10:12Z",
        "app_vex_gate": "2026-08-11T13:14:07Z",
        "gateway_gate": "2026-08-11T13:16:41Z",
        "gateway_raw": "2026-08-11T13:12:55Z",
        "release_verify": "2026-08-11T13:17:16Z",
    },
    "release_identity_sha256": ("2f87b61de7d79301b5a6870d4c870383ae04f1ec5aec5bf4086259708a681705"),
    "release_verify_exit": 0,
    "schema_version": 1,
    "trivy": {
        "db_sha256": "fbd7a1751c20449fc014ce29514c745d16d196d2c67ad6fb88315ac7357d62bf",
        "db_updated_at": "2026-08-09T12:54:52.355618652Z",
        "image_digest": ("sha256:be1190afcb28352bfddc4ddeb71470835d16462af68d310f9f4bca710961a41e"),
        "version": "0.70.0",
    },
}


class AuditValidationError(ValueError):
    """Raised when the tracked audit violates its fail-closed contract."""


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    kind: str
    command: str
    path: str
    result: str
    observed_at: datetime | None
    exit_code: int | str | None


@dataclass(frozen=True)
class Finding:
    finding_id: str
    domain: str
    severity: str
    status: str
    description: str
    evidence_ids: tuple[str, ...]
    owner: str
    disposition: str
    review_condition: str


@dataclass(frozen=True)
class DomainCoverage:
    domain: str
    evidence_ids: tuple[str, ...]
    conclusion: str


@dataclass(frozen=True)
class EngineeringAudit:
    path: Path
    generated_at: datetime
    domains: tuple[DomainCoverage, ...]
    evidence: tuple[Evidence, ...]
    findings: tuple[Finding, ...]

    @property
    def open_findings(self) -> tuple[Finding, ...]:
        return tuple(finding for finding in self.findings if finding.status == "OPEN")


def _parse_utc(value: str) -> datetime | None:
    if value == "-":
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _split_ids(value: str) -> tuple[str, ...]:
    if value == "-":
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _table(text: str, heading: str) -> list[dict[str, str]]:
    lines = text.splitlines()
    try:
        heading_index = lines.index(heading)
    except ValueError as exc:
        raise AuditValidationError(f"missing section: {heading}") from exc
    try:
        header_index = next(
            index for index in range(heading_index + 1, len(lines)) if lines[index].startswith("|")
        )
    except StopIteration as exc:
        raise AuditValidationError(f"missing table: {heading}") from exc

    headers = [cell.strip() for cell in lines[header_index].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[header_index + 2 :]:
        if not line.startswith("|"):
            break
        values = [cell.strip() for cell in line.strip("|").split("|")]
        if len(values) != len(headers):
            raise AuditValidationError(f"malformed table row in {heading}")
        rows.append(dict(zip(headers, values, strict=True)))
    return rows


def _required(row: dict[str, str], columns: set[str], heading: str) -> None:
    missing = sorted(columns - row.keys())
    if missing:
        raise AuditValidationError(f"missing columns in {heading}: {', '.join(missing)}")


def load_audit(path: Path) -> EngineeringAudit:
    text = path.read_text(encoding="utf-8")
    generated_matches = re.findall(
        r"^- \*\*Generated at UTC:\*\* `([^`]+)`$", text, flags=re.MULTILINE
    )
    if len(generated_matches) != 1:
        raise AuditValidationError("audit must contain exactly one generated UTC time")
    generated_at = _parse_utc(generated_matches[0])
    if generated_at is None:
        raise AuditValidationError("audit generated UTC time is invalid")

    domain_rows = _table(text, "## Domain coverage")
    domains: list[DomainCoverage] = []
    for row in domain_rows:
        _required(row, {"Domain", "Evidence IDs", "Conclusion"}, "Domain coverage")
        domains.append(
            DomainCoverage(row["Domain"], _split_ids(row["Evidence IDs"]), row["Conclusion"])
        )

    evidence_rows = _table(text, "## Evidence index")
    evidence: list[Evidence] = []
    for row in evidence_rows:
        _required(
            row,
            {
                "ID",
                "Kind",
                "Command",
                "Path",
                "Result",
                "Observed at UTC",
                "Exit code",
            },
            "Evidence index",
        )
        if row["Exit code"] == "NOT_RUN":
            exit_code: int | str | None = "NOT_RUN"
        else:
            try:
                exit_code = None if row["Exit code"] == "-" else int(row["Exit code"])
            except ValueError:
                exit_code = None
        evidence.append(
            Evidence(
                row["ID"],
                row["Kind"],
                row["Command"],
                row["Path"],
                row["Result"],
                _parse_utc(row["Observed at UTC"]),
                exit_code,
            )
        )

    finding_rows = _table(text, "## Findings")
    findings: list[Finding] = []
    for row in finding_rows:
        _required(
            row,
            {
                "ID",
                "Domain",
                "Severity",
                "Status",
                "Description",
                "Evidence IDs",
                "Owner",
                "Disposition",
                "Review condition",
            },
            "Findings",
        )
        findings.append(
            Finding(
                row["ID"],
                row["Domain"],
                row["Severity"],
                row["Status"],
                row["Description"],
                _split_ids(row["Evidence IDs"]),
                row["Owner"],
                row["Disposition"],
                row["Review condition"],
            )
        )
    return EngineeringAudit(path, generated_at, tuple(domains), tuple(evidence), tuple(findings))


def _duplicates(values: list[str]) -> list[str]:
    return sorted({value for value in values if values.count(value) > 1})


def validate_audit(
    audit: EngineeringAudit, *, repo_root: Path, now: datetime | None = None
) -> None:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    errors: list[str] = []
    if audit.generated_at > now:
        errors.append("audit generated time is future-dated")

    domain_names = [item.domain for item in audit.domains]
    duplicate_domains = _duplicates(domain_names)
    if duplicate_domains:
        errors.append(f"duplicate audit domains: {', '.join(duplicate_domains)}")
    missing_domains = sorted(set(EXPECTED_DOMAINS) - set(domain_names))
    extra_domains = sorted(set(domain_names) - set(EXPECTED_DOMAINS))
    if missing_domains:
        errors.append(f"missing audit domains: {', '.join(missing_domains)}")
    if extra_domains:
        errors.append(f"unexpected audit domains: {', '.join(extra_domains)}")

    finding_ids = [finding.finding_id for finding in audit.findings]
    duplicate_findings = _duplicates(finding_ids)
    if duplicate_findings:
        errors.append(f"duplicate finding ids: {', '.join(duplicate_findings)}")
    missing_findings = sorted(set(FINDING_CONTRACTS) - set(finding_ids))
    extra_findings = sorted(set(finding_ids) - set(FINDING_CONTRACTS))
    if missing_findings:
        errors.append(f"missing findings: {', '.join(missing_findings)}")
    if extra_findings:
        errors.append(
            f"unrecognized findings require a checker contract: {', '.join(extra_findings)}"
        )

    evidence_ids = [item.evidence_id for item in audit.evidence]
    duplicate_evidence = _duplicates(evidence_ids)
    if duplicate_evidence:
        errors.append(f"duplicate evidence ids: {', '.join(duplicate_evidence)}")

    expected_evidence_ids = {f"E{index:03d}" for index in range(1, 37)}
    missing_evidence = sorted(expected_evidence_ids - set(evidence_ids))
    extra_evidence = sorted(set(evidence_ids) - expected_evidence_ids)
    if missing_evidence:
        errors.append(f"missing evidence ids: {', '.join(missing_evidence)}")
    if extra_evidence:
        errors.append(f"unrecognized evidence ids: {', '.join(extra_evidence)}")

    evidence_by_id = {item.evidence_id: item for item in audit.evidence}
    fingerprints: dict[tuple[object, ...], str] = {}
    for item in audit.evidence:
        fingerprint = (
            item.kind,
            item.command,
            item.path,
            item.result,
            item.observed_at,
            item.exit_code,
        )
        if fingerprint in fingerprints:
            errors.append(
                f"duplicate evidence records: {fingerprints[fingerprint]} and {item.evidence_id}"
            )
        else:
            fingerprints[fingerprint] = item.evidence_id

        if item.kind not in EVIDENCE_KINDS:
            errors.append(f"{item.evidence_id} has invalid evidence kind")
        if item.command in {"", "-"}:
            errors.append(f"{item.evidence_id} requires command")
        if item.path in {"", "-"}:
            errors.append(f"{item.evidence_id} requires path")
        if item.result in {"", "-"}:
            errors.append(f"{item.evidence_id} requires result")
        if item.observed_at is None:
            errors.append(f"{item.evidence_id} has invalid observed UTC")
        elif item.observed_at > now:
            errors.append(f"{item.evidence_id} is future-dated")
        elif item.observed_at > audit.generated_at:
            errors.append(f"{item.evidence_id} is later than the generated audit")
        if item.exit_code is None:
            errors.append(f"{item.evidence_id} has invalid exit code")
        elif item.kind == "EXTERNAL_NOT_RUN" and item.exit_code != "NOT_RUN":
            errors.append(f"{item.evidence_id} EXTERNAL_NOT_RUN must use NOT_RUN exit")
        elif item.kind in EXECUTED_KINDS and not isinstance(item.exit_code, int):
            errors.append(f"{item.evidence_id} executed evidence requires an integer exit")
        if item.path not in {"", "-"}:
            candidate = (repo_root / item.path).resolve()
            try:
                candidate.relative_to(repo_root.resolve())
            except ValueError:
                errors.append(f"{item.evidence_id} path leaves repository")
            else:
                if not candidate.exists():
                    errors.append(f"{item.evidence_id} evidence path does not exist")
        if item.kind == "FILE_EXISTENCE" and item.evidence_id == "E003":
            errors.append("E003 cannot use file existence as executed verification")

    for evidence_id, expected_contract in FIXED_EVIDENCE_CONTRACTS.items():
        item = evidence_by_id.get(evidence_id)
        if (
            item is not None
            and (
                item.kind,
                item.command,
                item.path,
                item.result,
            )
            != expected_contract
        ):
            errors.append(f"{evidence_id} does not match its fixed evidence contract")
            owners = [
                finding_id
                for finding_id, fixed_ids in FIXED_FINDING_EVIDENCE_IDS.items()
                if evidence_id in fixed_ids
            ]
            if owners:
                errors.extend(
                    f"{finding_id} evidence {evidence_id} does not match its fixed evidence "
                    "contract"
                    for finding_id in owners
                )

    _validate_security_manifest(repo_root, errors)

    for coverage in audit.domains:
        if not coverage.evidence_ids:
            errors.append(f"{coverage.domain} has no evidence")
        if coverage.conclusion in {"", "-"}:
            errors.append(f"{coverage.domain} has no conclusion")
        for evidence_id in coverage.evidence_ids:
            item = evidence_by_id.get(evidence_id)
            if item is None:
                errors.append(f"{coverage.domain} references missing evidence {evidence_id}")
            elif item.kind != "CURRENT_COMMAND" or item.exit_code != 0:
                errors.append(f"{coverage.domain} requires successful current command evidence")
        if (
            coverage.domain == "runtime-image-vulnerabilities"
            and coverage.evidence_ids != SECURITY_DOMAIN_EVIDENCE_IDS
        ):
            errors.append(
                "runtime-image-vulnerabilities evidence coverage does not match its fixed contract"
            )

    for finding in audit.findings:
        if finding.severity not in SEVERITIES:
            errors.append(f"{finding.finding_id} has invalid severity")
        if finding.status not in STATUSES:
            errors.append(f"{finding.finding_id} has invalid status")
        contract = FINDING_CONTRACTS.get(finding.finding_id)
        if (
            contract is not None
            and (
                finding.domain,
                finding.severity,
                finding.status,
            )
            != contract
        ):
            errors.append(f"{finding.finding_id} does not match its fixed finding contract")
        fixed_evidence_ids = FIXED_FINDING_EVIDENCE_IDS.get(finding.finding_id)
        if fixed_evidence_ids is not None and finding.evidence_ids != fixed_evidence_ids:
            errors.append(
                f"{finding.finding_id} evidence coverage does not match its fixed contract"
            )
        if finding.domain not in EXPECTED_DOMAINS:
            errors.append(f"{finding.finding_id} has invalid domain")
        if finding.description in {"", "-"}:
            errors.append(f"{finding.finding_id} requires description")
        referenced = [evidence_by_id.get(item) for item in finding.evidence_ids]
        if any(item is None for item in referenced):
            errors.append(f"{finding.finding_id} references missing evidence")
        if finding.status == "FIXED":
            has_red = any(
                item is not None
                and item.kind == "RED_COMMAND"
                and item.exit_code is not None
                and item.exit_code != 0
                for item in referenced
            )
            has_green = any(
                item is not None and item.kind == "CURRENT_COMMAND" and item.exit_code == 0
                for item in referenced
            )
            if not has_red or not has_green:
                errors.append(f"{finding.finding_id} FIXED requires RED and GREEN evidence")
        if finding.status == "ACCEPTED":
            if (
                not finding.disposition.startswith("RISK ACCEPTED:")
                or len(finding.disposition) < 40
            ):
                errors.append(f"{finding.finding_id} ACCEPTED requires a specific risk rationale")
            if finding.owner in {"", "-"}:
                errors.append(f"{finding.finding_id} ACCEPTED requires an owner")
            if finding.review_condition in {"", "-"}:
                errors.append(f"{finding.finding_id} ACCEPTED requires a review condition")
        if finding.status == "BLOCKED":
            has_external = any(
                item is not None and item.kind == "EXTERNAL_NOT_RUN" for item in referenced
            )
            if not finding.disposition.startswith("EXTERNAL:") or not has_external:
                errors.append(f"{finding.finding_id} BLOCKED requires a real external condition")
            if finding.owner in {"", "-"}:
                errors.append(f"{finding.finding_id} BLOCKED requires an owner")
            if finding.review_condition in {"", "-"}:
                errors.append(f"{finding.finding_id} BLOCKED requires a review condition")

    open_high = sorted(
        finding.finding_id
        for finding in audit.findings
        if finding.status == "OPEN" and finding.severity in {"Critical", "High"}
    )
    if open_high:
        errors.append(f"OPEN Critical/High findings: {', '.join(open_high)}")

    if errors:
        raise AuditValidationError("\n".join(dict.fromkeys(errors)))


def _validate_security_manifest(repo_root: Path, errors: list[str]) -> None:
    path = repo_root / SECURITY_MANIFEST_PATH
    try:
        contents = path.read_bytes()
        manifest = json.loads(contents)
    except (OSError, json.JSONDecodeError):
        errors.append("security evidence manifest is missing or invalid")
        return
    normalized_contents = contents.replace(b"\r\n", b"\n")
    if hashlib.sha256(normalized_contents).hexdigest() != SECURITY_MANIFEST_SHA256:
        errors.append("security evidence manifest does not match its fixed digest")
    if manifest != SECURITY_MANIFEST_CONTRACT:
        errors.append("security evidence manifest field contract changed")
    try:
        app = manifest["app"]
        gateway = manifest["gateway"]
        trivy = manifest["trivy"]
        boundary = manifest["boundary"]
        release_exit = manifest["release_verify_exit"]
    except (KeyError, TypeError):
        errors.append("security evidence manifest is incomplete")
        return
    if (
        manifest.get("schema_version") != 1
        or app.get("occurrences") != 181
        or app.get("distinct_cves") != 67
        or app.get("critical_occurrences") != 12
        or app.get("high_occurrences") != 169
        or app.get("audit_exit") != 0
        or app.get("vex_gate_exit") != 0
        or gateway.get("occurrences") != 0
        or gateway.get("distinct_cves") != 0
        or gateway.get("gate_exit") != 0
        or release_exit != 0
        or trivy.get("version") != "0.70.0"
        or boundary.get("build_kind") != "controlled_current_source_derivation_from_task20_final"
        or boundary.get("formal_dockerfile_build_exit") != 1
    ):
        errors.append("security evidence manifest facts do not match the fixed audit boundary")

    policy_path = repo_root / "scripts/image-vulnerability-policy.json"
    try:
        policy_bytes = policy_path.read_bytes()
        policy = json.loads(policy_bytes)
        runtime_payload = json.dumps(
            policy["runtime_boundary"], sort_keys=True, separators=(",", ":")
        ).encode()
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        errors.append("vulnerability policy is missing or invalid")
        return
    normalized_policy = policy_bytes.replace(b"\r\n", b"\n")
    if hashlib.sha256(normalized_policy).hexdigest() != boundary.get("policy_sha256"):
        errors.append("security manifest policy digest does not match current policy")
    if hashlib.sha256(runtime_payload).hexdigest() != boundary.get("runtime_boundary_sha256"):
        errors.append("security manifest runtime boundary does not match current policy")
    try:
        current_runtime_boundary = build_runtime_boundary_manifest(repo_root)
    except (OSError, ValueError) as exc:
        errors.append(f"current runtime boundary cannot be built: {exc}")
        return
    if current_runtime_boundary != policy["runtime_boundary"]:
        errors.append("security manifest runtime boundary does not match current source")
    current_runtime_payload = json.dumps(
        current_runtime_boundary, sort_keys=True, separators=(",", ":")
    ).encode()
    if hashlib.sha256(current_runtime_payload).hexdigest() != boundary.get(
        "runtime_boundary_sha256"
    ):
        errors.append("security manifest runtime boundary does not match current source")


def _default_trivy_db_dir(repo_root: Path) -> Path:
    return repo_root.parent / "feat-20-production-delivery" / "tmp" / "trivy-cache" / "db"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditValidationError(f"retained security JSON is invalid: {path}") from error
    if not isinstance(value, dict):
        raise AuditValidationError(f"retained security JSON must be an object: {path}")
    return value


def _scan_summary(scan: dict[str, Any]) -> dict[str, int]:
    results = scan.get("Results")
    if not isinstance(results, list):
        raise AuditValidationError("raw scan Results must be an array")
    occurrences = 0
    severities = {"HIGH": 0, "CRITICAL": 0}
    cves: set[str] = set()
    for result in results:
        if not isinstance(result, dict):
            raise AuditValidationError("raw scan result must be an object")
        vulnerabilities = result.get("Vulnerabilities")
        if vulnerabilities is None:
            continue
        if not isinstance(vulnerabilities, list):
            raise AuditValidationError("raw scan Vulnerabilities must be an array or null")
        for vulnerability in vulnerabilities:
            if not isinstance(vulnerability, dict):
                raise AuditValidationError("raw scan vulnerability must be an object")
            cve = vulnerability.get("VulnerabilityID")
            severity = vulnerability.get("Severity")
            if not isinstance(cve, str) or not cve:
                raise AuditValidationError("raw scan vulnerability has no CVE id")
            if severity not in severities:
                raise AuditValidationError(
                    f"raw scan vulnerability has unexpected severity: {severity!r}"
                )
            occurrences += 1
            severities[severity] += 1
            cves.add(cve)
    return {
        "occurrences": occurrences,
        "high_occurrences": severities["HIGH"],
        "critical_occurrences": severities["CRITICAL"],
        "distinct_cves": len(cves),
    }


def _canonical_finding_digest(findings: list[dict[str, Any]]) -> str:
    normalized = sorted(
        findings,
        key=lambda item: json.dumps(
            item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
    )
    payload = json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_trivy_metadata(metadata: dict[str, Any], contract: dict[str, Any]) -> None:
    if metadata.get("UpdatedAt") != contract["trivy"]["db_updated_at"]:
        raise AuditValidationError("Trivy DB metadata UpdatedAt mismatch")


def _docker_image_id(tag: str) -> str:
    try:
        completed = subprocess.run(
            ["docker", "image", "inspect", "--format={{.Id}}", tag],
            capture_output=True,
            check=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise AuditValidationError(f"local image identity unavailable: {tag}") from error
    image_id = completed.stdout.strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise AuditValidationError(f"local image identity is invalid: {tag}")
    return image_id


def _validate_local_image_identities(
    image_id_reader: Callable[[str], str], contract: dict[str, Any]
) -> None:
    expected = {
        "museecho-app:task23-review1": contract["app"]["daemon_image_id"],
        "museecho-gateway:local": contract["gateway"]["daemon_image_id"],
        "museecho-app:task20-final": contract["boundary"]["task20_base_daemon_image_id"],
        "aquasec/trivy:0.70.0": contract["trivy"]["image_digest"],
    }
    mismatches = [
        tag for tag, expected_id in expected.items() if image_id_reader(tag) != expected_id
    ]
    if mismatches:
        raise AuditValidationError("local image identity mismatch: " + ", ".join(mismatches))


def _json_output_digest(value: dict[str, Any]) -> str:
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    return hashlib.sha256(payload).hexdigest()


def validate_security_materials(
    *,
    materials_dir: Path,
    trivy_db_dir: Path,
    repo_root: Path | None = None,
    image_id_reader: Callable[[str], str] = _docker_image_id,
) -> None:
    selected_repo_root = repo_root or Path(__file__).resolve().parents[1]
    required = [materials_dir / name for name in SECURITY_MATERIAL_FILENAMES]
    required.extend((trivy_db_dir / "trivy.db", trivy_db_dir / "metadata.json"))
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise AuditValidationError("retained security material is missing: " + ", ".join(missing))
    mismatches: list[str] = []
    for filename, field_path in SECURITY_MATERIAL_DIGEST_PATHS.items():
        expected: object = SECURITY_MANIFEST_CONTRACT
        for field in field_path:
            assert isinstance(expected, dict)
            expected = expected[field]
        observed = _sha256_file(materials_dir / filename)
        if observed != expected:
            mismatches.append(filename)
    if _sha256_file(trivy_db_dir / "trivy.db") != SECURITY_MANIFEST_CONTRACT["trivy"]["db_sha256"]:
        mismatches.append("trivy.db")
    if mismatches:
        raise AuditValidationError(
            "retained security material digest mismatch: " + ", ".join(mismatches)
        )

    metadata = _read_json_object(trivy_db_dir / "metadata.json")
    _validate_trivy_metadata(metadata, SECURITY_MANIFEST_CONTRACT)

    app_scan = _read_json_object(materials_dir / "app-raw-review1.json")
    gateway_scan = _read_json_object(materials_dir / "gateway-raw-review1.json")
    app_package_files = _read_json_object(materials_dir / "app-package-files-review1.json")
    retained_inventory = _read_json_object(materials_dir / "app-inventory-review1.json")
    retained_vex = _read_json_object(materials_dir / "app-openvex-review1.json")
    release_identity = _read_json_object(materials_dir / "release-images-review1.json")
    policy = _read_json_object(selected_repo_root / "scripts/image-vulnerability-policy.json")

    app_summary = _scan_summary(app_scan)
    expected_app_summary = {
        key: SECURITY_MANIFEST_CONTRACT["app"][key]
        for key in (
            "occurrences",
            "high_occurrences",
            "critical_occurrences",
            "distinct_cves",
        )
    }
    if app_summary != expected_app_summary:
        raise AuditValidationError(f"retained app raw scan summary mismatch: {app_summary!r}")
    gateway_summary = _scan_summary(gateway_scan)
    if gateway_summary["occurrences"] != 0 or gateway_summary["distinct_cves"] != 0:
        raise AuditValidationError(
            f"retained gateway raw scan summary mismatch: {gateway_summary!r}"
        )

    with chdir(selected_repo_root):
        audit_errors, recomputed_vex, recomputed_inventory = audit_image(
            app_scan,
            app_package_files,
            policy,
            expected_image_id=SECURITY_MANIFEST_CONTRACT["app"]["config_image_id"],
        )
    if audit_errors or recomputed_vex is None or recomputed_inventory is None:
        raise AuditValidationError(
            "retained app audit recomputation failed: " + "; ".join(audit_errors)
        )
    if recomputed_vex != retained_vex or recomputed_inventory != retained_inventory:
        raise AuditValidationError("retained VEX or audit inventory differs from recomputation")
    if _json_output_digest(recomputed_vex) != SECURITY_MANIFEST_CONTRACT["app"]["vex_sha256"]:
        raise AuditValidationError("recomputed VEX digest mismatch")
    if (
        _json_output_digest(recomputed_inventory)
        != SECURITY_MANIFEST_CONTRACT["app"]["inventory_sha256"]
    ):
        raise AuditValidationError("recomputed audit inventory digest mismatch")
    findings = recomputed_inventory.get("findings")
    if not isinstance(findings, list) or not all(isinstance(item, dict) for item in findings):
        raise AuditValidationError("recomputed audit inventory findings are invalid")
    if _canonical_finding_digest(findings) != SECURITY_MANIFEST_CONTRACT["app"]["tuple_sha256"]:
        raise AuditValidationError("recomputed finding tuple digest mismatch")

    tar_paths = {
        "app": materials_dir / "museecho-app-task23-review1.tar",
        "gateway": materials_dir / "museecho-gateway-task20.tar",
    }
    image_ids = {name: image_id_from_tar(path) for name, path in tar_paths.items()}
    release_findings = audit_release_identity(
        release_identity,
        image_ids=image_ids,
        tar_digests={name: _sha256_file(path) for name, path in tar_paths.items()},
        scans={"app": app_scan, "gateway": gateway_scan},
    )
    if release_findings:
        raise AuditValidationError(
            "retained release identity mismatch: " + "; ".join(release_findings)
        )
    _validate_local_image_identities(image_id_reader, SECURITY_MANIFEST_CONTRACT)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", type=Path)
    parser.add_argument(
        "--schema-only",
        action="store_true",
        help="validate tracked audit/schema contracts without claiming retained materials",
    )
    parser.add_argument("--materials-dir", type=Path)
    parser.add_argument("--trivy-db-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        audit = load_audit(args.audit)
        repo_root = Path(__file__).resolve().parents[1]
        validate_audit(audit, repo_root=repo_root)
        if not args.schema_only:
            materials_dir = args.materials_dir or Path(
                os.environ.get(
                    "MUSEECHO_TASK23_EVIDENCE_DIR", repo_root / "tmp" / "task23-engineering"
                )
            )
            trivy_db_dir = args.trivy_db_dir or Path(
                os.environ.get("MUSEECHO_TASK20_TRIVY_DB_DIR", _default_trivy_db_dir(repo_root))
            )
            validate_security_materials(
                materials_dir=materials_dir,
                trivy_db_dir=trivy_db_dir,
                repo_root=repo_root,
            )
    except (AuditValidationError, OSError) as exc:
        print(f"engineering audit validation failed: {exc}", file=sys.stderr)
        return 1
    counts: dict[tuple[str, str], int] = {}
    for finding in audit.findings:
        key = (finding.status, finding.severity)
        counts[key] = counts.get(key, 0) + 1
    summary = ", ".join(
        f"{status}/{severity}={count}" for (status, severity), count in sorted(counts.items())
    )
    mode = (
        "schema only; retained materials NOT validated"
        if args.schema_only
        else "completion materials validated"
    )
    print(f"engineering findings validated ({mode}): {len(audit.findings)} ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
