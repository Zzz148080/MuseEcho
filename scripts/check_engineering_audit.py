#!/usr/bin/env python3
"""Fail-closed validation for the tracked Task 23 engineering audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

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
}

# Security/release evidence is especially easy to turn into a vacuous success.
# Match the actual command, not merely a prose claim of zero findings.
FIXED_EVIDENCE_COMMANDS = {
    "E020": (
        "docker run --rm --network none "
        "--tmpfs /root/.cache/trivy:rw,nosuid,nodev,size=512m "
        "--mount type=bind,source=TASK20_TRIVY_DB,target=/root/.cache/trivy/db,readonly "
        "--mount type=bind,source=TASK23_EVIDENCE,target=/evidence aquasec/trivy:0.70.0 "
        "image --input /evidence/museecho-app-task23.tar --scanners vuln "
        "--severity HIGH,CRITICAL --format json "
        "--output /evidence/app-raw.json --skip-db-update --skip-java-db-update "
        "--skip-version-check --offline-scan"
    ),
    "E022": (
        "docker run --rm --network none --read-only --cap-drop ALL "
        "--security-opt no-new-privileges --workdir /workspace "
        "--mount type=bind,source=REPOSITORY,target=/workspace,readonly "
        "--mount type=bind,source=TASK23_EVIDENCE,target=/evidence "
        "--entrypoint /app/.venv/bin/python museecho-app:task23-audit "
        "/workspace/scripts/image_vulnerability_audit.py "
        "--scan /evidence/app-raw.json --package-files /evidence/app-package-files.json "
        "--policy /workspace/scripts/image-vulnerability-policy.json "
        "--release-identity /evidence/release-images.json --image-name app "
        "--vex-output /evidence/app-openvex.json "
        "--inventory-output /evidence/app-inventory.json"
    ),
    "E025": (
        "python scripts/verify_release_identity.py verify "
        "--manifest tmp/task23-engineering/release-images.json "
        "--tar app=tmp/task23-engineering/museecho-app-task23.tar "
        "--tar gateway=tmp/task23-engineering/museecho-gateway-task20.tar "
        "--scan app=tmp/task23-engineering/app-raw.json "
        "--scan gateway=tmp/task23-engineering/gateway-raw.json"
    ),
}

SECURITY_MANIFEST_PATH = "docs/audits/evidence/task23-security-manifest.json"
SECURITY_MANIFEST_SHA256 = "ff43291cd7a80ea7fe21982da55e77bf7c41305cc07fca758e095a3f7b678126"


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

    expected_evidence_ids = {f"E{index:03d}" for index in range(1, 35)}
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

    for evidence_id, expected_command in FIXED_EVIDENCE_COMMANDS.items():
        item = evidence_by_id.get(evidence_id)
        if item is not None and item.command != expected_command:
            errors.append(f"{evidence_id} does not match its fixed evidence contract")

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", type=Path)
    args = parser.parse_args(argv)
    try:
        audit = load_audit(args.audit)
        validate_audit(audit, repo_root=Path(__file__).resolve().parents[1])
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
    print(f"engineering findings validated: {len(audit.findings)} ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
