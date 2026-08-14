#!/usr/bin/env python3
"""Fail-closed validator for the MuseEcho functional acceptance audit."""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import shutil
import subprocess
import sys
import tarfile
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Sequence

EXPECTED_ITEM_IDS = (
    "AC-A-1",
    "AC-A-2",
    "AC-A-3",
    "AC-A-4",
    "AC-B-1",
    "AC-B-2",
    "AC-B-3",
    "AC-C-1",
    "AC-C-2",
    "AC-C-3",
    "AC-D-1",
    "AC-D-2",
    "AC-D-3",
    "AC-D-4",
    "AC-E-1",
    "AC-E-2",
    "AC-E-3",
    "AC-E-4",
    "AC-F-1",
    "AC-F-2",
    "AC-F-3",
    "AC-F-4",
    "AC-F-5",
    "AC-F-6",
    "DOD-01",
    "DOD-02",
    "DOD-03",
    "DOD-04",
    "DOD-05",
    "DOD-06",
    "DOD-07",
    "DOD-08",
    "DOD-09",
    "DOD-10",
    "DOD-11",
    "DOD-12",
    "DOD-13",
    "DOD-14",
    "DOD-15",
    "DOD-16",
)

AC_COUNTS = {"A": 4, "B": 3, "C": 3, "D": 4, "E": 4, "F": 6}
DOD_FRAGMENTS = (
    "A–D 模块端到端运行",
    "真实上传分析",
    "交互时间轴",
    "确定性理论测试",
    "Evidence Explanation",
    "无 Key fallback",
    "全套测试与构建",
    "Docker runtime",
    "Secret audit",
    "合理 Git/PR 历史",
    "双 CI 配置",
    "全过程文档",
    "三轮 Audit",
    "无已知 Critical bug 和 High security issue",
    "没有伪造测试、CI、人工参与或部署证据",
    "学生最终仍须亲自完成",
)
REQUIRED_OPEN_BLOCKERS = (
    "TC-021",
    "CURRENT-BRANCH-DISTRIBUTION",
    "REMOTE-CI",
    "TASK24-AUDIT",
    "STUDENT-MANUAL",
)
VALID_VERDICTS = {"PASS", "PARTIAL", "FAIL"}
VALID_IMPORTANCE = {"IMPORTANT", "STANDARD"}
VALID_EVIDENCE_KINDS = {
    "CURRENT_COMMAND",
    "IMPLEMENTATION_BOUNDARY_COMMAND",
    "HISTORICAL_COMMIT",
    "EXTERNAL_NOT_RUN",
    "FILE_EXISTENCE",
}
EXECUTED_EVIDENCE_KINDS = {
    "CURRENT_COMMAND",
    "IMPLEMENTATION_BOUNDARY_COMMAND",
    "HISTORICAL_COMMIT",
}
FILE_ONLY_COMMAND = re.compile(
    r"^\s*(?:Test-Path\b|Get-Item\b|Get-ChildItem\b|ls\b|dir\b|test\s+-[efd]\b|git\s+ls-files\b)",
    re.IGNORECASE,
)
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
COMMIT_HASH = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

TASK19_EVIDENCE_COMMIT = "1047ce242884b6ba83a525524e88dcc44ab76a69"
TASK19_HISTORICAL_BOUNDARY_SHA256 = (
    "063f1dd0e3b9a27aa7772e3e2320e681facd7df2ff9e58e8e9e3c204f02bdc5d"
)
TASK19_BOUNDARY_PATHS = (
    "e2e",
    "frontend/src",
    "src/museecho",
    "tests/api",
    "tests/integration",
    "package.json",
    "package-lock.json",
    "frontend/package.json",
    "frontend/package-lock.json",
    "playwright.config.ts",
    "tsconfig.e2e.json",
)


class AuditValidationError(ValueError):
    """Raised when one or more fail-closed audit checks fail."""


@dataclass(frozen=True)
class EvidenceContract:
    kind: str
    command: str
    path: str
    coverage_ids: tuple[str, ...]
    result: str
    exit_code_raw: str
    commit: str = "-"
    supports_pass: bool = True


EVIDENCE_CONTRACTS = {
    "E001": EvidenceContract(
        kind="CURRENT_COMMAND",
        command=(
            "npm.cmd --prefix frontend test -- --run; "
            "npm.cmd --prefix frontend run typecheck; "
            "npm.cmd --prefix frontend run build"
        ),
        path="frontend/src",
        coverage_ids=(
            "AC-A-3",
            "AC-B-1",
            "AC-B-2",
            "AC-B-3",
            "AC-C-1",
            "AC-C-2",
            "AC-D-4",
            "AC-F-1",
            "AC-F-4",
            "DOD-01",
            "DOD-03",
            "DOD-05",
            "DOD-06",
            "DOD-07",
        ),
        result="vitest-files=12; vitest-tests=78; typecheck=pass; build-modules=95",
        exit_code_raw="0",
    ),
    "E002": EvidenceContract(
        kind="IMPLEMENTATION_BOUNDARY_COMMAND",
        command=(
            "gh run view 31630284744 --repo Zzz148080/MuseEcho --json conclusion,jobs,url,headSha"
        ),
        path="frontend",
        coverage_ids=("AC-F-1", "AC-F-4", "DOD-07"),
        result="frontend-tests=success; frontend-typecheck=success; frontend-build=success",
        exit_code_raw="0",
    ),
    "E003": EvidenceContract(
        kind="CURRENT_COMMAND",
        command=("powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/secret-scan.ps1"),
        path="scripts/secret-scan.ps1",
        coverage_ids=("AC-E-4", "DOD-09", "DOD-14"),
        result="secret-scan-files=210",
        exit_code_raw="0",
    ),
    "E004": EvidenceContract(
        kind="HISTORICAL_COMMIT",
        command=(
            "git show 1047ce242884b6ba83a525524e88dcc44ab76a69:AGENT_LOG.md "
            "1047ce242884b6ba83a525524e88dcc44ab76a69:PLAN.md"
        ),
        path="AGENT_LOG.md",
        coverage_ids=("AC-A-4", "AC-C-3", "AC-F-1", "DOD-01", "DOD-03", "DOD-07"),
        result=("browser-tests=4; benchmark-seconds=11.201268; boundary-state=DRIFT"),
        exit_code_raw="0",
        commit=TASK19_EVIDENCE_COMMIT,
        supports_pass=False,
    ),
    "E005": EvidenceContract(
        kind="CURRENT_COMMAND",
        command=(
            r".venv\Scripts\python.exe -m pytest "
            "tests/unit/test_task20_final_delivery_contract.py -q "
            "--basetemp=tmp/task23-review1-delivery"
        ),
        path="tests/unit/test_task20_final_delivery_contract.py",
        coverage_ids=("AC-F-2", "AC-F-3", "DOD-11", "DOD-12"),
        result=(
            "pytest-tests=8; github=parsed; gitlab=parsed; gitlab-unit-test=present; "
            "readme=verified"
        ),
        exit_code_raw="0",
    ),
    "E006": EvidenceContract(
        kind="CURRENT_COMMAND",
        command=(
            r"..\feat-20-production-delivery\.venv\Scripts\python.exe -m pytest "
            "tests/unit/test_acceptance_matrix.py -q"
        ),
        path="tests/unit/test_acceptance_matrix.py",
        coverage_ids=("DOD-15",),
        result="red=ModuleNotFoundError:scripts.check_acceptance_matrix",
        exit_code_raw="1",
        supports_pass=False,
    ),
    "E008": EvidenceContract(
        kind="CURRENT_COMMAND",
        command=(
            "powershell.exe -NoProfile -ExecutionPolicy Bypass -File "
            "scripts/container-pytest.ps1 -Image museecho-task3-verification-env:latest; "
            r".venv\Scripts\python.exe -m pytest "
            "tests/unit/test_task20_final_delivery_contract.py -q"
        ),
        path="tests",
        coverage_ids=(
            "AC-A-1",
            "AC-A-2",
            "AC-A-3",
            "AC-A-4",
            "AC-D-1",
            "AC-D-2",
            "AC-D-3",
            "AC-D-4",
            "AC-E-1",
            "AC-E-2",
            "AC-E-3",
            "AC-F-1",
            "DOD-01",
            "DOD-02",
            "DOD-04",
            "DOD-05",
            "DOD-06",
            "DOD-07",
            "DOD-14",
            "DOD-15",
        ),
        result="container-pytest=839; container-skipped=7; powershell-host-pytest=20",
        exit_code_raw="0",
    ),
    "E009": EvidenceContract(
        kind="IMPLEMENTATION_BOUNDARY_COMMAND",
        command=(
            "powershell.exe -NoProfile -ExecutionPolicy Bypass -File "
            "scripts/container-smoke.ps1 -NoBuild -ReleaseManifest "
            "docs/audits/evidence/task23-security-manifest.json -ExpectedAppDaemonImageId "
            "sha256:b0231299644d58f7845e3c137faeca6f0f8cc7df2f3dbbcb656c75060128a724 "
            "-ExpectedAppConfigImageId "
            "sha256:89c7b7ad0a9d1708ce0cf277389c1fca7e13e05bb3937b602a6e2533cf9729ac "
            "-ExpectedGatewayDaemonImageId "
            "sha256:2235e208dd7d8568c735ba19f1969644384626296eaff5cabb41acfaed86c547 "
            "-ExpectedGatewayConfigImageId "
            "sha256:8cc0429e45fd48c911a92fd8504c1f3c14daccb0fee8a24529d72af51b0b4053"
        ),
        path="scripts/container-smoke.ps1",
        coverage_ids=("AC-E-1", "AC-E-3", "AC-F-1", "AC-F-3", "DOD-07", "DOD-08"),
        result="no-build=trusted-identity+real-wav+restart+ciphertext+image-history+cleanup",
        exit_code_raw="0",
        supports_pass=False,
    ),
    "E010": EvidenceContract(
        kind="CURRENT_COMMAND",
        command=(
            r".venv\Scripts\python.exe -m ruff format --check src tests scripts; "
            r".venv\Scripts\python.exe -m ruff check .; "
            r".venv\Scripts\python.exe -m mypy src; "
            r".venv\Scripts\python.exe -m mypy --platform linux src; "
            r".venv\Scripts\python.exe -m mypy scripts/check_acceptance_matrix.py"
        ),
        path="scripts/check_acceptance_matrix.py",
        coverage_ids=("AC-F-1", "DOD-07"),
        result=("ruff-files=96; mypy-src-files=47; mypy-linux-src-files=47; mypy-checker-files=1"),
        exit_code_raw="0",
    ),
    "E011": EvidenceContract(
        kind="CURRENT_COMMAND",
        command=r".venv\Scripts\python.exe scripts/license_audit.py",
        path="scripts/license_audit.py",
        coverage_ids=("DOD-14",),
        result="license-audit=pass",
        exit_code_raw="0",
    ),
    "E012": EvidenceContract(
        kind="CURRENT_COMMAND",
        command=(
            "powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-secret-scan.ps1"
        ),
        path="scripts/test-secret-scan.ps1",
        coverage_ids=("AC-E-4", "DOD-09", "DOD-14"),
        result="secret-mutations=pass",
        exit_code_raw="0",
    ),
    "E013": EvidenceContract(
        kind="CURRENT_COMMAND",
        command=(
            "powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-secret-scan.ps1"
        ),
        path="scripts/test-secret-scan.ps1",
        coverage_ids=("AC-E-4", "DOD-09"),
        result="red=wrapped-unreadable-filename",
        exit_code_raw="1",
        supports_pass=False,
    ),
    "E014": EvidenceContract(
        kind="CURRENT_COMMAND",
        command=(
            ".venv\\Scripts\\python.exe -m pytest tests/unit/test_acceptance_matrix.py -q "
            "--basetemp tmp/task23-e014 -p no:cacheprovider; "
            "if ($LASTEXITCODE) { exit $LASTEXITCODE }; "
            ".venv\\Scripts\\python.exe scripts/check_acceptance_matrix.py "
            "SPEC.md docs/audits/FUNCTIONAL_AUDIT.md"
        ),
        path="tests/unit/test_acceptance_matrix.py",
        coverage_ids=("AC-F-1", "DOD-15"),
        result="pytest-tests=47; pass=31; partial=9; fail=0",
        exit_code_raw="0",
    ),
    "E902": EvidenceContract(
        kind="CURRENT_COMMAND",
        command=(
            r".venv\Scripts\python.exe scripts/check_engineering_audit.py "
            "docs/audits/ENGINEERING_AUDIT.md "
            "--materials-dir tmp/task23-engineering "
            "--trivy-db-dir ../feat-20-production-delivery/tmp/trivy-cache/db"
        ),
        path="docs/audits/ENGINEERING_AUDIT.md",
        coverage_ids=("AC-F-6", "DOD-13"),
        result=(
            "findings=10; fixed-high=4; fixed-medium=2; verified-medium=1; "
            "blocked-medium=3; open=0; "
            "app-occurrences=181; app-distinct-cves=67; gateway-occurrences=0"
        ),
        exit_code_raw="0",
    ),
    "E906": EvidenceContract(
        kind="IMPLEMENTATION_BOUNDARY_COMMAND",
        command=(
            "gh run view 31630284744 --repo Zzz148080/MuseEcho --json conclusion,jobs,url,headSha"
        ),
        path=".github/workflows/ci.yml",
        coverage_ids=(
            "AC-C-3",
            "AC-F-1",
            "AC-F-4",
            "DOD-01",
            "DOD-03",
            "DOD-07",
            "DOD-10",
        ),
        result=(
            "run=31630284744; head=2b2730eaf232f8edf3ead77be1830fa50d927a47; "
            "quality=success; e2e=success; distribution=success"
        ),
        exit_code_raw="0",
    ),
}


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    kind: str
    command: str
    path: str
    coverage_ids: tuple[str, ...]
    result: str
    boundary_sha256: str
    observed_at_raw: str
    exit_code_raw: str
    commit: str
    summary: str


@dataclass(frozen=True)
class AcceptanceItem:
    item_id: str
    verdict: str
    importance: str
    evidence_ids: tuple[str, ...]
    owner: str
    disposition: str
    notes: str


@dataclass(frozen=True)
class BlockerRecord:
    blocker_id: str
    blocker_class: str
    status: str
    owner: str
    evidence_ids: tuple[str, ...]
    notes: str


@dataclass(frozen=True)
class AcceptanceAudit:
    generated_at_raw: str
    readiness: str
    items: tuple[AcceptanceItem, ...]
    evidence: tuple[EvidenceRecord, ...]
    blockers: tuple[BlockerRecord, ...]
    parse_issues: tuple[str, ...]
    spec_issues: tuple[str, ...]

    @property
    def missing_items(self) -> tuple[str, ...]:
        present = {item.item_id for item in self.items}
        return tuple(item_id for item_id in EXPECTED_ITEM_IDS if item_id not in present)

    @property
    def duplicate_item_ids(self) -> tuple[str, ...]:
        counts = Counter(item.item_id for item in self.items)
        return tuple(item_id for item_id in EXPECTED_ITEM_IDS if counts[item_id] > 1)


def _clean_cell(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
        return value[1:-1].strip()
    return value


def _refs(value: str) -> tuple[str, ...]:
    value = _clean_cell(value)
    if value in {"", "-"}:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _metadata(text: str, label: str, issues: list[str]) -> str:
    pattern = re.compile(rf"^- \*\*{re.escape(label)}:\*\*\s+`([^`]+)`\s*$", re.MULTILINE)
    matches = pattern.findall(text)
    if len(matches) != 1:
        issues.append(f"metadata {label!r} must appear exactly once")
        return ""
    return str(matches[0]).strip()


def _table(
    text: str,
    heading: str,
    expected_headers: Sequence[str],
    issues: list[str],
) -> list[dict[str, str]]:
    lines = text.splitlines()
    heading_indexes = [index for index, line in enumerate(lines) if line.strip() == heading]
    if len(heading_indexes) != 1:
        issues.append(f"heading {heading!r} must appear exactly once")
        return []
    index = heading_indexes[0] + 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    table_lines: list[str] = []
    while index < len(lines) and lines[index].lstrip().startswith("|"):
        table_lines.append(lines[index].strip())
        index += 1
    if len(table_lines) < 2:
        issues.append(f"{heading} table is missing")
        return []

    def cells(line: str) -> list[str]:
        return [_clean_cell(cell) for cell in line.strip().strip("|").split("|")]

    headers = cells(table_lines[0])
    if headers != list(expected_headers):
        issues.append(f"{heading} headers must be: {', '.join(expected_headers)}")
        return []
    separator = cells(table_lines[1])
    if len(separator) != len(headers) or any(
        not re.fullmatch(r":?-{3,}:?", cell) for cell in separator
    ):
        issues.append(f"{heading} has an invalid Markdown separator")
        return []
    rows: list[dict[str, str]] = []
    for row_number, line in enumerate(table_lines[2:], start=1):
        values = cells(line)
        if len(values) != len(headers):
            issues.append(
                f"{heading} row {row_number} has {len(values)} cells, expected {len(headers)}"
            )
            continue
        rows.append(dict(zip(headers, values, strict=True)))
    return rows


def _spec_issues(spec_text: str) -> tuple[str, ...]:
    issues: list[str] = []
    section_match = re.search(r"(?ms)^## 19\. 客观验收标准\s*(.*?)^## 20\.", spec_text)
    if section_match is None:
        issues.append("SPEC section 19 objective acceptance criteria is missing")
    else:
        section = section_match.group(1)
        observed_ids: list[str] = []
        for letter, expected_count in AC_COUNTS.items():
            category = re.search(rf"(?ms)^### AC-{letter}\b.*?\n(.*?)(?=^### AC-|\Z)", section)
            if category is None:
                issues.append(f"SPEC AC-{letter} is missing")
                continue
            bullets = re.findall(r"(?m)^-\s+\S.*$", category.group(1))
            if len(bullets) != expected_count:
                issues.append(
                    f"SPEC AC-{letter} has {len(bullets)} items, expected {expected_count}"
                )
            observed_ids.extend(f"AC-{letter}-{index}" for index in range(1, len(bullets) + 1))
        if tuple(observed_ids) != EXPECTED_ITEM_IDS[:24]:
            issues.append("SPEC AC item order/count does not match the acceptance ID contract")
    for index, fragment in enumerate(DOD_FRAGMENTS, start=1):
        if fragment not in spec_text:
            issues.append(f"SPEC DOD-{index:02d} trace fragment is missing: {fragment}")
    return tuple(issues)


def load_audit(spec_path: Path | str, audit_path: Path | str) -> AcceptanceAudit:
    spec = Path(spec_path).read_text(encoding="utf-8")
    text = Path(audit_path).read_text(encoding="utf-8")
    issues: list[str] = []
    generated_at = _metadata(text, "Generated at UTC", issues)
    readiness = _metadata(text, "Readiness", issues)

    evidence_rows = _table(
        text,
        "## Evidence index",
        (
            "Evidence ID",
            "Kind",
            "Command",
            "Path",
            "Coverage",
            "Result",
            "Boundary SHA256",
            "Observed at UTC",
            "Exit code",
            "Commit",
            "Summary",
        ),
        issues,
    )
    item_rows = _table(
        text,
        "## Acceptance matrix",
        (
            "Item ID",
            "Verdict",
            "Importance",
            "Evidence IDs",
            "Owner",
            "Disposition",
            "Notes",
        ),
        issues,
    )
    blocker_rows = _table(
        text,
        "## Open blockers",
        ("Blocker ID", "Class", "Status", "Owner", "Evidence IDs", "Notes"),
        issues,
    )

    evidence = tuple(
        EvidenceRecord(
            evidence_id=row["Evidence ID"],
            kind=row["Kind"],
            command=row["Command"],
            path=row["Path"],
            coverage_ids=_refs(row["Coverage"]),
            result=row["Result"],
            boundary_sha256=row["Boundary SHA256"],
            observed_at_raw=row["Observed at UTC"],
            exit_code_raw=row["Exit code"],
            commit=row["Commit"],
            summary=row["Summary"],
        )
        for row in evidence_rows
    )
    items = tuple(
        AcceptanceItem(
            item_id=row["Item ID"],
            verdict=row["Verdict"],
            importance=row["Importance"],
            evidence_ids=_refs(row["Evidence IDs"]),
            owner=row["Owner"],
            disposition=row["Disposition"],
            notes=row["Notes"],
        )
        for row in item_rows
    )
    blockers = tuple(
        BlockerRecord(
            blocker_id=row["Blocker ID"],
            blocker_class=row["Class"],
            status=row["Status"],
            owner=row["Owner"],
            evidence_ids=_refs(row["Evidence IDs"]),
            notes=row["Notes"],
        )
        for row in blocker_rows
    )
    return AcceptanceAudit(
        generated_at_raw=generated_at,
        readiness=readiness,
        items=items,
        evidence=evidence,
        blockers=blockers,
        parse_issues=tuple(issues),
        spec_issues=_spec_issues(spec),
    )


def _parse_utc(value: str) -> datetime | None:
    if UTC_TIMESTAMP.fullmatch(value) is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _duplicates(values: Iterable[str]) -> tuple[str, ...]:
    counts = Counter(values)
    return tuple(sorted(value for value, count in counts.items() if count > 1))


def _resolve_evidence_path(repo_root: Path, value: str) -> Path | None:
    if value in {"", "-"}:
        return None
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    resolved = (repo_root / candidate).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError:
        return None
    return resolved


def _is_boundary_file(relative_path: Path) -> bool:
    return "__pycache__" not in relative_path.parts and relative_path.suffix != ".pyc"


def _digest_boundary_entries(entries: Iterable[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for relative_path, content in sorted(entries):
        if b"\0" not in content:
            content = content.replace(b"\r\n", b"\n")
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _current_boundary_sha256(repo_root: Path) -> str:
    entries: list[tuple[str, bytes]] = []
    for value in TASK19_BOUNDARY_PATHS:
        path = repo_root / value
        candidates = (path,) if path.is_file() else path.rglob("*")
        for candidate in candidates:
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(repo_root)
            if _is_boundary_file(relative):
                entries.append((relative.as_posix(), candidate.read_bytes()))
    return _digest_boundary_entries(entries)


def _historical_boundary_sha256(repo_root: Path, commit: str) -> str | None:
    archive = subprocess.run(
        [
            "git",
            "-c",
            "core.autocrlf=false",
            "archive",
            "--format=tar",
            commit,
            "--",
            *TASK19_BOUNDARY_PATHS,
        ],
        cwd=repo_root,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if archive.returncode != 0:
        return None
    entries: list[tuple[str, bytes]] = []
    with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as boundary_archive:
        for member in boundary_archive.getmembers():
            relative = Path(member.name)
            if not member.isfile() or not _is_boundary_file(relative):
                continue
            extracted = boundary_archive.extractfile(member)
            if extracted is None:
                return None
            entries.append((relative.as_posix(), extracted.read()))
    return _digest_boundary_entries(entries)


def _validate_task19_historical_boundary(
    record: EvidenceRecord,
    *,
    repo_root: Path,
    issues: list[str],
) -> None:
    if SHA256.fullmatch(record.boundary_sha256) is None:
        issues.append("E004 current boundary SHA256 is missing or invalid")
    else:
        current_boundary = _current_boundary_sha256(repo_root)
        if record.boundary_sha256 != current_boundary:
            issues.append("E004 current boundary SHA256 does not match repository content")

    plan_path = repo_root / "PLAN.md"
    if not plan_path.is_file() or TASK19_EVIDENCE_COMMIT not in plan_path.read_text(
        encoding="utf-8"
    ):
        issues.append("E004 authoritative PLAN anchor does not confirm its exact commit")

    if shutil.which("git") is None:
        return
    historical_boundary = _historical_boundary_sha256(repo_root, TASK19_EVIDENCE_COMMIT)
    if historical_boundary != TASK19_HISTORICAL_BOUNDARY_SHA256:
        issues.append("E004 historical boundary does not match its exact commit")
    anchor = subprocess.run(
        ["git", "show", f"{TASK19_EVIDENCE_COMMIT}:AGENT_LOG.md"],
        cwd=repo_root,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    if anchor.returncode != 0 or not all(
        fragment in anchor.stdout for fragment in ("真实浏览器 `4 passed`", "11.201268")
    ):
        issues.append("E004 historical AGENT_LOG anchor does not expose the claimed results")


def validate_audit(
    audit: AcceptanceAudit,
    *,
    repo_root: Path,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(UTC)
    issues = [*audit.parse_issues, *audit.spec_issues]
    if audit.missing_items:
        issues.append(f"missing acceptance items: {', '.join(audit.missing_items)}")
    if audit.duplicate_item_ids:
        issues.append(f"duplicate acceptance items: {', '.join(audit.duplicate_item_ids)}")
    unexpected_items = sorted({item.item_id for item in audit.items}.difference(EXPECTED_ITEM_IDS))
    if unexpected_items:
        issues.append(f"unexpected acceptance items: {', '.join(unexpected_items)}")

    generated_at = _parse_utc(audit.generated_at_raw)
    if generated_at is None:
        issues.append("audit generated time is not strict UTC")
    elif generated_at > now:
        issues.append("audit generated time is future-dated")
    if audit.readiness not in {"READY", "PARTIALLY_READY"}:
        issues.append(f"invalid readiness: {audit.readiness or '<missing>'}")

    duplicate_evidence_ids = _duplicates(record.evidence_id for record in audit.evidence)
    if duplicate_evidence_ids:
        issues.append(f"duplicate evidence ids: {', '.join(duplicate_evidence_ids)}")
    duplicate_blocker_ids = _duplicates(record.blocker_id for record in audit.blockers)
    if duplicate_blocker_ids:
        issues.append(f"duplicate blocker ids: {', '.join(duplicate_blocker_ids)}")

    evidence_by_id: dict[str, EvidenceRecord] = {}
    fingerprints: dict[tuple[str, ...], str] = {}
    evidence_exit_codes: dict[str, int | None] = {}
    for record in audit.evidence:
        evidence_by_id.setdefault(record.evidence_id, record)
        if re.fullmatch(r"E\d{3}", record.evidence_id) is None:
            issues.append(f"invalid evidence id: {record.evidence_id or '<missing>'}")
        if record.kind not in VALID_EVIDENCE_KINDS:
            issues.append(f"{record.evidence_id} has invalid evidence kind: {record.kind}")
        if record.command in {"", "-"}:
            issues.append(f"{record.evidence_id} requires an evidence command")
        if not record.coverage_ids:
            issues.append(f"{record.evidence_id} requires declared item coverage")
        if record.result in {"", "-"}:
            issues.append(f"{record.evidence_id} requires a measurable result")
        if record.boundary_sha256 == "":
            issues.append(f"{record.evidence_id} requires a boundary SHA256 field")
        resolved_path = _resolve_evidence_path(repo_root, record.path)
        if resolved_path is None:
            issues.append(f"{record.evidence_id} requires an evidence path")
        elif not resolved_path.exists():
            issues.append(f"{record.evidence_id} evidence path does not exist: {record.path}")
        observed_at = _parse_utc(record.observed_at_raw)
        if observed_at is None:
            issues.append(f"{record.evidence_id} has invalid UTC timestamp")
        else:
            if observed_at > now:
                issues.append(f"{record.evidence_id} is future-dated")
            if generated_at is not None and observed_at > generated_at:
                issues.append(f"{record.evidence_id} occurs after the audit generated time")
        exit_code: int | None = None
        if record.kind == "EXTERNAL_NOT_RUN":
            if record.exit_code_raw != "NOT_RUN":
                issues.append(f"{record.evidence_id} EXTERNAL_NOT_RUN must use exit NOT_RUN")
        else:
            try:
                exit_code = int(record.exit_code_raw)
            except ValueError:
                issues.append(f"{record.evidence_id} has invalid exit code")
        evidence_exit_codes[record.evidence_id] = exit_code
        contract = EVIDENCE_CONTRACTS.get(record.evidence_id)
        if record.kind in EXECUTED_EVIDENCE_KINDS and contract is None:
            issues.append(f"{record.evidence_id} has no fixed evidence contract")
        if contract is not None:
            fixed_fields_match = (
                record.kind == contract.kind
                and record.command == contract.command
                and record.path == contract.path
                and record.coverage_ids == contract.coverage_ids
                and record.result == contract.result
                and record.exit_code_raw == contract.exit_code_raw
                and record.commit == contract.commit
                and (record.evidence_id == "E004" or record.boundary_sha256 == "-")
            )
            if not fixed_fields_match:
                issues.append(f"{record.evidence_id} does not match its fixed evidence contract")
        if record.evidence_id == "E004":
            _validate_task19_historical_boundary(record, repo_root=repo_root, issues=issues)
        if record.kind == "HISTORICAL_COMMIT":
            if COMMIT_HASH.fullmatch(record.commit) is None:
                issues.append(f"{record.evidence_id} requires an exact 40-character commit")
            elif record.commit not in record.command or record.path not in record.command:
                issues.append(
                    f"{record.evidence_id} historical command must bind its exact commit and path"
                )
            elif resolved_path is not None and shutil.which("git") is not None:
                completed = subprocess.run(
                    ["git", "cat-file", "-e", f"{record.commit}:{record.path}"],
                    cwd=repo_root,
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=10,
                )
                if completed.returncode != 0:
                    issues.append(
                        f"{record.evidence_id} historical path is not verifiable at {record.commit}"
                    )
        elif record.commit not in {"", "-"}:
            issues.append(f"{record.evidence_id} non-historical evidence must not claim a commit")
        fingerprint = (
            record.kind,
            record.command,
            record.path,
            *record.coverage_ids,
            record.result,
            record.boundary_sha256,
            record.observed_at_raw,
            record.exit_code_raw,
            record.commit,
        )
        prior = fingerprints.get(fingerprint)
        if prior is not None and prior != record.evidence_id:
            issues.append(f"duplicate evidence records: {prior} and {record.evidence_id}")
        else:
            fingerprints[fingerprint] = record.evidence_id

    blocker_by_id = {record.blocker_id: record for record in audit.blockers}
    for blocker_id in REQUIRED_OPEN_BLOCKERS:
        blocker = blocker_by_id.get(blocker_id)
        if blocker is None:
            issues.append(f"required truthful blocker is missing: {blocker_id}")
            continue
        if blocker.status != "OPEN":
            if any(
                evidence_by_id.get(evidence_id) is not None
                and evidence_by_id[evidence_id].kind == "EXTERNAL_NOT_RUN"
                for evidence_id in blocker.evidence_ids
            ):
                issues.append(f"{blocker_id} cannot be RESOLVED with NOT_RUN evidence")
            else:
                issues.append(f"{blocker_id} must remain OPEN in the tracked audit")

    referenced_blockers: set[str] = set()
    referenced_evidence: set[str] = set()
    for item in audit.items:
        if item.verdict not in VALID_VERDICTS:
            issues.append(f"{item.item_id} has invalid verdict: {item.verdict}")
        if item.importance not in VALID_IMPORTANCE:
            issues.append(f"{item.item_id} has invalid importance: {item.importance}")
        if item.owner in {"", "-"}:
            issues.append(f"{item.item_id} requires an owner")
        if item.notes in {"", "-"}:
            issues.append(f"{item.item_id} requires notes")
        if item.verdict == "PASS" and not item.evidence_ids:
            issues.append(f"{item.item_id} PASS requires evidence")
        for evidence_id in item.evidence_ids:
            referenced_evidence.add(evidence_id)
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                issues.append(f"{item.item_id} references unknown evidence {evidence_id}")
                continue
            if item.item_id not in evidence.coverage_ids:
                issues.append(f"{evidence_id} does not cover {item.item_id}")
            if item.verdict == "PASS":
                contract = EVIDENCE_CONTRACTS.get(evidence_id)
                if evidence_id == "E004":
                    issues.append("E004 historical boundary drift cannot support PASS")
                elif contract is None or not contract.supports_pass:
                    issues.append(
                        f"{item.item_id} PASS lacks a fixed passing contract for {evidence_id}"
                    )
                if evidence.kind not in EXECUTED_EVIDENCE_KINDS or FILE_ONLY_COMMAND.match(
                    evidence.command
                ):
                    issues.append(
                        f"{item.item_id} PASS relies on non-executed evidence {evidence_id}"
                    )
                elif evidence_exit_codes.get(evidence_id) != 0:
                    issues.append(f"{item.item_id} PASS relies on failing evidence {evidence_id}")
        needs_disposition = item.verdict == "FAIL" or (
            item.verdict == "PARTIAL" and item.importance == "IMPORTANT"
        )
        if needs_disposition and not (
            item.disposition.startswith("BLOCKER:") or item.disposition.startswith("FIXED:")
        ):
            issues.append(
                f"{item.item_id} {item.verdict} {item.importance} requires "
                "BLOCKER or FIXED disposition"
            )
        if item.disposition.startswith("BLOCKER:"):
            blocker_id = item.disposition.removeprefix("BLOCKER:").strip()
            referenced_blockers.add(blocker_id)
            blocker = blocker_by_id.get(blocker_id)
            if blocker is None:
                issues.append(f"{item.item_id} references unknown blocker {blocker_id}")
            elif blocker.status != "OPEN":
                issues.append(f"{item.item_id} references non-open blocker {blocker_id}")
            if item.verdict == "PASS":
                issues.append(f"{item.item_id} PASS cannot have an open blocker")
        elif item.disposition.startswith("FIXED:"):
            fix_ids = _refs(item.disposition.removeprefix("FIXED:"))
            if not fix_ids:
                issues.append(f"{item.item_id} FIXED disposition requires revalidation evidence")
            for evidence_id in fix_ids:
                referenced_evidence.add(evidence_id)
                evidence = evidence_by_id.get(evidence_id)
                if (
                    evidence is None
                    or evidence.kind not in EXECUTED_EVIDENCE_KINDS
                    or evidence_exit_codes.get(evidence_id) != 0
                ):
                    issues.append(
                        f"{item.item_id} FIXED disposition lacks passing revalidation {evidence_id}"
                    )

    for blocker in audit.blockers:
        if blocker.blocker_class not in {"EXTERNAL", "FOLLOW_UP", "MANUAL", "ENVIRONMENT"}:
            issues.append(f"{blocker.blocker_id} has invalid blocker class")
        if blocker.status not in {"OPEN", "RESOLVED"}:
            issues.append(f"{blocker.blocker_id} has invalid blocker status")
        if blocker.owner in {"", "-"} or blocker.notes in {"", "-"}:
            issues.append(f"{blocker.blocker_id} requires owner and notes")
        if not blocker.evidence_ids:
            issues.append(f"{blocker.blocker_id} requires evidence")
        for evidence_id in blocker.evidence_ids:
            referenced_evidence.add(evidence_id)
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                issues.append(f"{blocker.blocker_id} references unknown evidence {evidence_id}")
            elif blocker.blocker_class in {"EXTERNAL", "FOLLOW_UP", "MANUAL"}:
                contract = EVIDENCE_CONTRACTS.get(evidence_id)
                is_truthful_pending_evidence = evidence.kind == "EXTERNAL_NOT_RUN" or (
                    evidence.kind in EXECUTED_EVIDENCE_KINDS
                    and contract is not None
                    and not contract.supports_pass
                )
                if not is_truthful_pending_evidence:
                    issues.append(
                        f"{blocker.blocker_id} pending status must use NOT_RUN "
                        "or fixed negative evidence"
                    )

    for blocker in audit.blockers:
        if blocker.status == "OPEN" and blocker.blocker_id not in referenced_blockers:
            issues.append(f"open blocker is not linked from the matrix: {blocker.blocker_id}")
    has_non_pass = any(item.verdict != "PASS" for item in audit.items)
    has_open_blocker = any(blocker.status == "OPEN" for blocker in audit.blockers)
    if audit.readiness == "READY" and (has_non_pass or has_open_blocker):
        issues.append("READY contradicts non-PASS items or open blockers")
    if audit.readiness == "PARTIALLY_READY" and not (has_non_pass or has_open_blocker):
        issues.append("PARTIALLY_READY requires a non-PASS item or open blocker")

    if issues:
        raise AuditValidationError("acceptance audit validation failed:\n- " + "\n- ".join(issues))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("audit", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        audit = load_audit(args.spec, args.audit)
        validate_audit(audit, repo_root=args.spec.resolve().parent)
    except (AuditValidationError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    counts = Counter(item.verdict for item in audit.items)
    print(
        f"{len(audit.items)} acceptance items validated: "
        f"PASS={counts['PASS']} PARTIAL={counts['PARTIAL']} FAIL={counts['FAIL']}; "
        f"readiness={audit.readiness}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
