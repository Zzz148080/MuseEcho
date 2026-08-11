from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.check_engineering_audit import (
    EXPECTED_DOMAINS,
    AuditValidationError,
    EngineeringAudit,
    load_audit,
    validate_audit,
)

ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "docs" / "audits" / "ENGINEERING_AUDIT.md"
NOW = datetime(2026, 8, 12, tzinfo=UTC)
DOMAIN_HEADING = "## Domain coverage"
EVIDENCE_HEADING = "## Evidence index"
FINDING_HEADING = "## Findings"

EXPECTED_DOMAIN_SET = {
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
}


@pytest.fixture
def audit() -> EngineeringAudit:
    return load_audit(AUDIT_PATH)


def test_engineering_audit_has_no_open_critical_or_high(
    audit: EngineeringAudit,
) -> None:
    assert [
        finding for finding in audit.open_findings if finding.severity in {"Critical", "High"}
    ] == []
    validate_audit(audit, repo_root=ROOT, now=NOW)


def _audit_text() -> str:
    return AUDIT_PATH.read_text(encoding="utf-8")


def _write_audit(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "ENGINEERING_AUDIT.md"
    path.write_text(text, encoding="utf-8")
    return path


def _table_bounds(lines: list[str], heading: str) -> tuple[int, int]:
    heading_index = lines.index(heading)
    header_index = next(
        index for index in range(heading_index + 1, len(lines)) if lines[index].startswith("|")
    )
    end_index = header_index
    while end_index < len(lines) and lines[end_index].startswith("|"):
        end_index += 1
    return header_index, end_index


def _replace_table_cell(text: str, heading: str, key: str, column: str, value: str) -> str:
    lines = text.splitlines()
    start, end = _table_bounds(lines, heading)
    headers = [cell.strip() for cell in lines[start].strip("|").split("|")]
    column_index = headers.index(column)
    for index in range(start + 2, end):
        cells = [cell.strip() for cell in lines[index].strip("|").split("|")]
        if cells[0] == key:
            cells[column_index] = value
            lines[index] = "| " + " | ".join(cells) + " |"
            return "\n".join(lines) + "\n"
    raise AssertionError(f"missing fixture row: {heading} / {key}")


def _remove_table_row(text: str, heading: str, key: str) -> str:
    lines = text.splitlines()
    start, end = _table_bounds(lines, heading)
    for index in range(start + 2, end):
        if lines[index].split("|")[1].strip() == key:
            del lines[index]
            return "\n".join(lines) + "\n"
    raise AssertionError(f"missing fixture row: {heading} / {key}")


def _duplicate_table_row(text: str, heading: str, key: str, *, new_key: str | None = None) -> str:
    lines = text.splitlines()
    start, end = _table_bounds(lines, heading)
    for index in range(start + 2, end):
        cells = [cell.strip() for cell in lines[index].strip("|").split("|")]
        if cells[0] == key:
            if new_key is not None:
                cells[0] = new_key
            lines.insert(end, "| " + " | ".join(cells) + " |")
            return "\n".join(lines) + "\n"
    raise AssertionError(f"missing fixture row: {heading} / {key}")


def _validation_error(tmp_path: Path, text: str) -> str:
    audit = load_audit(_write_audit(tmp_path, text))
    with pytest.raises(AuditValidationError) as caught:
        validate_audit(audit, repo_root=ROOT, now=NOW)
    return str(caught.value)


def test_domain_contract_is_the_complete_fixed_set() -> None:
    assert set(EXPECTED_DOMAINS) == EXPECTED_DOMAIN_SET
    assert len(EXPECTED_DOMAINS) == 15


@pytest.mark.parametrize("operation", ("missing", "duplicate"))
def test_missing_or_duplicate_domain_fails_closed(tmp_path: Path, operation: str) -> None:
    text = _audit_text()
    if operation == "missing":
        mutation = _remove_table_row(text, DOMAIN_HEADING, "observability")
        expected = "missing audit domains: observability"
    else:
        mutation = _duplicate_table_row(text, DOMAIN_HEADING, "observability")
        expected = "duplicate audit domains: observability"

    assert expected in _validation_error(tmp_path, mutation)


@pytest.mark.parametrize(
    ("heading", "key", "expected"),
    (
        (FINDING_HEADING, "ENG-001", "missing findings: ENG-001"),
        (EVIDENCE_HEADING, "E003", "missing evidence ids: E003"),
    ),
)
def test_deleting_a_finding_or_evidence_fails_closed(
    tmp_path: Path, heading: str, key: str, expected: str
) -> None:
    mutation = _remove_table_row(_audit_text(), heading, key)

    assert expected in _validation_error(tmp_path, mutation)


@pytest.mark.parametrize(
    ("heading", "key", "expected"),
    (
        (FINDING_HEADING, "ENG-001", "duplicate finding ids: ENG-001"),
        (EVIDENCE_HEADING, "E003", "duplicate evidence ids: E003"),
    ),
)
def test_duplicate_finding_or_evidence_id_fails_closed(
    tmp_path: Path, heading: str, key: str, expected: str
) -> None:
    mutation = _duplicate_table_row(_audit_text(), heading, key)

    assert expected in _validation_error(tmp_path, mutation)


def test_same_evidence_cannot_be_reindexed(tmp_path: Path) -> None:
    mutation = _duplicate_table_row(_audit_text(), EVIDENCE_HEADING, "E003", new_key="E999")

    assert "duplicate evidence records: E003 and E999" in _validation_error(tmp_path, mutation)


@pytest.mark.parametrize(
    ("column", "value", "expected"),
    (
        ("Command", "-", "E003 requires command"),
        ("Path", "-", "E003 requires path"),
        ("Result", "-", "E003 requires result"),
        ("Exit code", "-", "E003 has invalid exit code"),
        ("Observed at UTC", "2999-01-01T00:00:00Z", "E003 is future-dated"),
    ),
)
def test_evidence_schema_and_time_fail_closed(
    tmp_path: Path, column: str, value: str, expected: str
) -> None:
    mutation = _replace_table_cell(_audit_text(), EVIDENCE_HEADING, "E003", column, value)

    assert expected in _validation_error(tmp_path, mutation)


@pytest.mark.parametrize(
    ("column", "value", "expected"),
    (
        ("Severity", "Important", "ENG-001 has invalid severity"),
        ("Status", "DONE", "ENG-001 has invalid status"),
    ),
)
def test_finding_schema_fails_closed(
    tmp_path: Path, column: str, value: str, expected: str
) -> None:
    mutation = _replace_table_cell(_audit_text(), FINDING_HEADING, "ENG-001", column, value)

    assert expected in _validation_error(tmp_path, mutation)


def test_fixed_finding_requires_real_red_and_green_evidence(tmp_path: Path) -> None:
    mutation = _replace_table_cell(
        _audit_text(), FINDING_HEADING, "ENG-001", "Evidence IDs", "E003"
    )

    assert "ENG-001 FIXED requires RED and GREEN evidence" in _validation_error(tmp_path, mutation)


def test_accepted_finding_requires_specific_reason_owner_and_review_condition(
    tmp_path: Path,
) -> None:
    mutation = _replace_table_cell(_audit_text(), FINDING_HEADING, "ENG-004", "Status", "ACCEPTED")
    mutation = _replace_table_cell(mutation, FINDING_HEADING, "ENG-004", "Owner", "-")
    mutation = _replace_table_cell(mutation, FINDING_HEADING, "ENG-004", "Disposition", "accepted")
    mutation = _replace_table_cell(mutation, FINDING_HEADING, "ENG-004", "Review condition", "-")

    error = _validation_error(tmp_path, mutation)
    assert "ENG-004 ACCEPTED requires a specific risk rationale" in error
    assert "ENG-004 ACCEPTED requires an owner" in error
    assert "ENG-004 ACCEPTED requires a review condition" in error


def test_blocked_finding_requires_real_external_condition(tmp_path: Path) -> None:
    mutation = _replace_table_cell(
        _audit_text(), FINDING_HEADING, "ENG-006", "Disposition", "internal follow-up"
    )
    mutation = _replace_table_cell(mutation, FINDING_HEADING, "ENG-006", "Evidence IDs", "E003")

    assert "ENG-006 BLOCKED requires a real external condition" in _validation_error(
        tmp_path, mutation
    )


def test_open_critical_or_high_fails_closed(tmp_path: Path) -> None:
    mutation = _replace_table_cell(_audit_text(), FINDING_HEADING, "ENG-001", "Status", "OPEN")

    assert "OPEN Critical/High findings: ENG-001" in _validation_error(tmp_path, mutation)


def test_finding_severity_cannot_be_downgraded_in_the_audit(tmp_path: Path) -> None:
    mutation = _replace_table_cell(_audit_text(), FINDING_HEADING, "ENG-001", "Severity", "Medium")

    assert "ENG-001 does not match its fixed finding contract" in _validation_error(
        tmp_path, mutation
    )


def test_file_existence_cannot_masquerade_as_verification(tmp_path: Path) -> None:
    mutation = _replace_table_cell(
        _audit_text(), EVIDENCE_HEADING, "E003", "Kind", "FILE_EXISTENCE"
    )
    mutation = _replace_table_cell(
        mutation, EVIDENCE_HEADING, "E003", "Command", "Test-Path tests/deploy"
    )

    assert "E003 cannot use file existence as executed verification" in _validation_error(
        tmp_path, mutation
    )


@pytest.mark.parametrize("evidence_id", ("E020", "E022", "E025"))
def test_scan_audit_and_release_verification_cannot_be_rewritten_as_vacuous_success(
    tmp_path: Path, evidence_id: str
) -> None:
    mutation = _replace_table_cell(
        _audit_text(), EVIDENCE_HEADING, evidence_id, "Command", "python -c pass"
    )
    mutation = _replace_table_cell(
        mutation, EVIDENCE_HEADING, evidence_id, "Result", "exit=0; findings=0"
    )

    assert f"{evidence_id} does not match its fixed evidence contract" in _validation_error(
        tmp_path, mutation
    )


def test_audit_generated_time_cannot_be_future_dated(tmp_path: Path) -> None:
    mutation = _audit_text().replace(
        "- **Generated at UTC:** `2026-08-11T",
        "- **Generated at UTC:** `2999-08-11T",
        1,
    )

    assert "audit generated time is future-dated" in _validation_error(tmp_path, mutation)


def test_checker_cli_accepts_the_committed_engineering_audit() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_engineering_audit.py"),
            str(AUDIT_PATH),
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert "engineering findings validated" in completed.stdout
