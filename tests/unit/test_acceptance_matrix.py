from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.check_acceptance_matrix import (
    EXPECTED_ITEM_IDS,
    AuditValidationError,
    load_audit,
    validate_audit,
)

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "SPEC.md"
AUDIT_PATH = ROOT / "docs" / "audits" / "FUNCTIONAL_AUDIT.md"
NOW = datetime(2026, 8, 12, tzinfo=UTC)

EXPECTED_IDS = (
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


def _audit_text() -> str:
    return AUDIT_PATH.read_text(encoding="utf-8")


def _write_audit(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "FUNCTIONAL_AUDIT.md"
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
    raise AssertionError(f"missing test fixture row: {heading} / {key}")


def _remove_table_row(text: str, heading: str, key: str) -> str:
    lines = text.splitlines()
    start, end = _table_bounds(lines, heading)
    for index in range(start + 2, end):
        if lines[index].split("|")[1].strip() == key:
            del lines[index]
            return "\n".join(lines) + "\n"
    raise AssertionError(f"missing test fixture row: {heading} / {key}")


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
    raise AssertionError(f"missing test fixture row: {heading} / {key}")


def _validation_error(tmp_path: Path, text: str) -> str:
    audit = load_audit(SPEC_PATH, _write_audit(tmp_path, text))
    with pytest.raises(AuditValidationError) as caught:
        validate_audit(audit, repo_root=ROOT, now=NOW)
    return str(caught.value)


def test_every_spec_acceptance_item_has_a_verdict_and_evidence():
    audit = load_audit(SPEC_PATH, AUDIT_PATH)

    assert audit.missing_items == ()
    assert audit.duplicate_item_ids == ()
    assert all(item.verdict in {"PASS", "PARTIAL", "FAIL"} for item in audit.items)
    assert all(item.evidence_ids for item in audit.items if item.verdict == "PASS")
    validate_audit(audit, repo_root=ROOT, now=NOW)


def test_item_id_contract_covers_all_ac_and_definition_of_done_items():
    assert EXPECTED_ITEM_IDS == EXPECTED_IDS
    assert len(EXPECTED_ITEM_IDS) == 40


def test_missing_item_fails_closed(tmp_path: Path):
    error = _validation_error(
        tmp_path,
        _remove_table_row(_audit_text(), "## Acceptance matrix", "AC-F-6"),
    )

    assert "missing acceptance items: AC-F-6" in error


def test_duplicate_item_fails_closed(tmp_path: Path):
    error = _validation_error(
        tmp_path,
        _duplicate_table_row(_audit_text(), "## Acceptance matrix", "AC-A-1"),
    )

    assert "duplicate acceptance items: AC-A-1" in error


def test_illegal_verdict_fails_closed(tmp_path: Path):
    mutation = _replace_table_cell(
        _audit_text(), "## Acceptance matrix", "AC-A-1", "Verdict", "READY"
    )

    assert "AC-A-1 has invalid verdict" in _validation_error(tmp_path, mutation)


def test_pass_without_evidence_fails_closed(tmp_path: Path):
    mutation = _replace_table_cell(
        _audit_text(), "## Acceptance matrix", "AC-A-1", "Evidence IDs", "-"
    )

    assert "AC-A-1 PASS requires evidence" in _validation_error(tmp_path, mutation)


@pytest.mark.parametrize(
    ("column", "value", "expected"),
    (
        ("Command", "-", "E001 requires an evidence command"),
        ("Path", "-", "E001 requires an evidence path"),
        ("Observed at UTC", "-", "E001 has invalid UTC timestamp"),
        ("Observed at UTC", "2999-01-01T00:00:00Z", "E001 is future-dated"),
    ),
)
def test_evidence_requires_command_path_and_non_future_utc_time(
    tmp_path: Path, column: str, value: str, expected: str
):
    mutation = _replace_table_cell(_audit_text(), "## Evidence index", "E001", column, value)

    assert expected in _validation_error(tmp_path, mutation)


def test_duplicate_evidence_id_fails_closed(tmp_path: Path):
    mutation = _duplicate_table_row(_audit_text(), "## Evidence index", "E001")

    assert "duplicate evidence ids: E001" in _validation_error(tmp_path, mutation)


def test_same_evidence_cannot_be_reindexed_under_another_id(tmp_path: Path):
    mutation = _duplicate_table_row(_audit_text(), "## Evidence index", "E001", new_key="E999")

    assert "duplicate evidence records: E001 and E999" in _validation_error(tmp_path, mutation)


def test_current_command_cannot_be_replaced_by_vacuous_success(tmp_path: Path):
    mutation = _replace_table_cell(
        _audit_text(), "## Evidence index", "E008", "Command", "python -c pass"
    )
    mutation = _replace_table_cell(
        mutation,
        "## Evidence index",
        "E008",
        "Summary",
        "The replacement command exited successfully without exercising MuseEcho.",
    )

    assert "E008 does not match its fixed evidence contract" in _validation_error(
        tmp_path, mutation
    )


def test_pass_item_rejects_successful_evidence_without_item_coverage(tmp_path: Path):
    mutation = _replace_table_cell(
        _audit_text(), "## Acceptance matrix", "AC-A-1", "Evidence IDs", "E001"
    )

    assert "E001 does not cover AC-A-1" in _validation_error(tmp_path, mutation)


def test_current_command_result_contract_cannot_be_rewritten_coherently(tmp_path: Path):
    text = _audit_text()
    result_column = "Result" if "| Result |" in text else "Summary"
    mutation = _replace_table_cell(
        text,
        "## Evidence index",
        "E008",
        result_column,
        "command-exit=0; functional-assertions=0",
    )

    assert "E008 does not match its fixed evidence contract" in _validation_error(
        tmp_path, mutation
    )


def test_exact_historical_evidence_is_structurally_verifiable_without_git(monkeypatch):
    monkeypatch.setenv("PATH", "")
    audit = load_audit(SPEC_PATH, AUDIT_PATH)

    validate_audit(audit, repo_root=ROOT, now=NOW)


def test_gitless_historical_evidence_rejects_coherent_fake_commit_and_command(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("PATH", "")
    fake_commit = "b" * 40
    mutation = _replace_table_cell(
        _audit_text(), "## Evidence index", "E004", "Commit", fake_commit
    )
    mutation = _replace_table_cell(
        mutation,
        "## Evidence index",
        "E004",
        "Command",
        f"git show --format=fuller --stat {fake_commit} -- AGENT_LOG.md PLAN.md",
    )

    assert "E004 does not match its fixed evidence contract" in _validation_error(
        tmp_path, mutation
    )


def test_historical_evidence_rejects_audit_only_boundary_path_drift(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    commit = "1047ce242884b6ba83a525524e88dcc44ab76a69"
    mutation = _replace_table_cell(
        _audit_text(), "## Evidence index", "E004", "Path", "frontend/src"
    )
    mutation = _replace_table_cell(
        mutation,
        "## Evidence index",
        "E004",
        "Command",
        f"git show --format=fuller --stat {commit} -- frontend/src",
    )

    assert "E004 does not match its fixed evidence contract" in _validation_error(
        tmp_path, mutation
    )


@pytest.mark.parametrize("replacement", ("-", "0" * 64))
def test_historical_evidence_requires_current_boundary_hash(tmp_path: Path, replacement: str):
    text = _audit_text()
    if "| Boundary SHA256 |" in text:
        mutation = _replace_table_cell(
            text,
            "## Evidence index",
            "E004",
            "Boundary SHA256",
            replacement,
        )
    else:
        mutation = text

    assert "E004 current boundary SHA256" in _validation_error(tmp_path, mutation)


def test_drifted_historical_browser_boundary_cannot_make_current_item_pass(tmp_path: Path):
    mutation = _replace_table_cell(
        _audit_text(), "## Acceptance matrix", "AC-C-3", "Evidence IDs", "E004"
    )
    mutation = _replace_table_cell(mutation, "## Acceptance matrix", "AC-C-3", "Verdict", "PASS")
    mutation = _replace_table_cell(mutation, "## Acceptance matrix", "AC-C-3", "Disposition", "-")

    assert "E004 historical boundary drift cannot support PASS" in _validation_error(
        tmp_path, mutation
    )


def test_ci_and_readme_evidence_cannot_omit_current_contract_scope(tmp_path: Path):
    text = _audit_text()
    if "| E005 | HISTORICAL_COMMIT |" in text:
        mutation = text
    else:
        mutation = _replace_table_cell(
            text,
            "## Evidence index",
            "E005",
            "Command",
            "python -c pass",
        )

    assert "E005 does not match its fixed evidence contract" in _validation_error(
        tmp_path, mutation
    )


def test_historical_evidence_command_must_bind_its_exact_commit_and_path(tmp_path: Path):
    mutation = _replace_table_cell(_audit_text(), "## Evidence index", "E004", "Commit", "b" * 40)

    assert "E004 historical command must bind its exact commit and path" in _validation_error(
        tmp_path, mutation
    )


@pytest.mark.parametrize("verdict", ("PARTIAL", "FAIL"))
def test_important_non_pass_requires_blocker_or_fix_revalidation(tmp_path: Path, verdict: str):
    mutation = _replace_table_cell(
        _audit_text(), "## Acceptance matrix", "AC-A-1", "Verdict", verdict
    )
    mutation = _replace_table_cell(
        mutation, "## Acceptance matrix", "AC-A-1", "Importance", "IMPORTANT"
    )
    mutation = _replace_table_cell(mutation, "## Acceptance matrix", "AC-A-1", "Disposition", "-")

    assert f"AC-A-1 {verdict} IMPORTANT requires BLOCKER or FIXED disposition" in _validation_error(
        tmp_path, mutation
    )


def test_ready_is_rejected_while_partial_items_and_blockers_exist(tmp_path: Path):
    mutation = _audit_text().replace(
        "- **Readiness:** `PARTIALLY_READY`", "- **Readiness:** `READY`", 1
    )

    assert "READY contradicts non-PASS items or open blockers" in _validation_error(
        tmp_path, mutation
    )


def test_file_existence_evidence_cannot_make_an_item_pass(tmp_path: Path):
    mutation = _replace_table_cell(
        _audit_text(), "## Evidence index", "E001", "Kind", "FILE_EXISTENCE"
    )

    assert "AC-A-3 PASS relies on non-executed evidence E001" in _validation_error(
        tmp_path, mutation
    )


def test_external_not_run_evidence_cannot_make_an_item_pass(tmp_path: Path):
    mutation = _replace_table_cell(
        _audit_text(), "## Acceptance matrix", "AC-A-1", "Evidence IDs", "E900"
    )

    assert "AC-A-1 PASS relies on non-executed evidence E900" in _validation_error(
        tmp_path, mutation
    )


@pytest.mark.parametrize(
    "blocker_id", ("TC-021", "REMOTE-CI", "TASK23-AUDIT", "TASK24-AUDIT", "STUDENT-MANUAL")
)
def test_external_follow_up_and_manual_work_cannot_be_marked_resolved_without_execution(
    tmp_path: Path, blocker_id: str
):
    mutation = _replace_table_cell(
        _audit_text(), "## Open blockers", blocker_id, "Status", "RESOLVED"
    )

    assert f"{blocker_id} cannot be RESOLVED with NOT_RUN evidence" in _validation_error(
        tmp_path, mutation
    )


def test_audit_generated_time_and_evidence_time_must_be_real_utc(tmp_path: Path):
    mutation = _audit_text().replace(
        "- **Generated at UTC:** `2026-08-11T", "- **Generated at UTC:** `2999-08-11T", 1
    )

    assert "audit generated time is future-dated" in _validation_error(tmp_path, mutation)


def test_checker_cli_accepts_the_committed_matrix():
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_acceptance_matrix.py"),
            str(SPEC_PATH),
            str(AUDIT_PATH),
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert "40 acceptance items validated" in completed.stdout
