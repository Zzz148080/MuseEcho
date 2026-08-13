from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.check_delivery_report import (
    EXPECTED_EVIDENCE_IDS,
    EXPECTED_PRODUCT_AUDIT_IDS,
    EXPECTED_SECTION_IDS,
    EXPECTED_STUDENT_CHECK_IDS,
    DeliveryValidationError,
    load_delivery_report,
    validate_delivery_report,
)

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "DELIVERY_REPORT.md"
NOW = datetime(2026, 8, 14, tzinfo=UTC)


def _report_text() -> str:
    return REPORT_PATH.read_text(encoding="utf-8")


def _write_report(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "DELIVERY_REPORT.md"
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


def _duplicate_table_row(text: str, heading: str, key: str) -> str:
    lines = text.splitlines()
    start, end = _table_bounds(lines, heading)
    for index in range(start + 2, end):
        if lines[index].split("|")[1].strip() == key:
            lines.insert(end, lines[index])
            return "\n".join(lines) + "\n"
    raise AssertionError(f"missing test fixture row: {heading} / {key}")


def _replace_section_metadata(text: str, section_id: str, label: str, value: str) -> str:
    lines = text.splitlines()
    heading_index = next(
        index for index, line in enumerate(lines) if line.startswith(f"## {section_id} ")
    )
    end_index = next(
        (index for index in range(heading_index + 1, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    prefix = f"- **{label}:**"
    for index in range(heading_index + 1, end_index):
        if lines[index].startswith(prefix):
            lines[index] = f"{prefix} {value}"
            return "\n".join(lines) + "\n"
    raise AssertionError(f"missing section metadata: {section_id} / {label}")


def _validation_error(tmp_path: Path, text: str) -> str:
    report = load_delivery_report(
        _write_report(tmp_path, text),
        product_audit_path=ROOT / "docs" / "audits" / "PRODUCT_AUDIT.md",
        reflection_path=ROOT / "REFLECTION.md",
    )
    with pytest.raises(DeliveryValidationError) as caught:
        validate_delivery_report(report, repo_root=ROOT, now=NOW)
    return str(caught.value)


def test_delivery_status_matches_evidence() -> None:
    report = load_delivery_report(REPORT_PATH)

    assert report.status == "MUSEECHO V1 PARTIALLY READY"
    assert report.blocking_reasons
    assert report.all_definition_of_done_items_have_current_pass_evidence is False
    validate_delivery_report(report, repo_root=ROOT, now=NOW)


def test_fixed_delivery_product_and_student_id_contracts() -> None:
    assert EXPECTED_SECTION_IDS == tuple(f"DR-{index:02d}" for index in range(1, 18))
    assert "DEL-011" in EXPECTED_EVIDENCE_IDS
    assert EXPECTED_PRODUCT_AUDIT_IDS == tuple(f"PA-{index:02d}" for index in range(1, 14))
    assert EXPECTED_STUDENT_CHECK_IDS == tuple(f"STU-{index:02d}" for index in range(1, 7))


def test_task24_github_boundary_is_fixed_while_gitlab_remains_pending(
    tmp_path: Path,
) -> None:
    report = load_delivery_report(REPORT_PATH)
    github = next(item for item in report.evidence if item.evidence_id == "DEL-011")
    gitlab = next(item for item in report.evidence if item.evidence_id == "DEL-900")

    assert github.kind == "IMPLEMENTATION_BOUNDARY_COMMAND"
    assert github.result == (
        "run=31687703913; head=de5bc6f949e6e98cff32f16116708ec7b7409c9d; "
        "quality=success; e2e=success; distribution=success"
    )
    assert github.exit_code_raw == "0"
    assert github.status == "PASS"
    assert gitlab.command == "NOT RUN: GitLab has no Task 24 pipeline"
    assert gitlab.result == "gitlab=NOT_RUN"
    assert "Task 24 GitHub branch-tip gate has not run" not in report.raw_text

    forged = _replace_table_cell(
        _report_text(), "## Evidence index", "DEL-011", "Result", "quality=success"
    )
    assert "DEL-011 does not match its fixed evidence contract" in _validation_error(
        tmp_path, forged
    )


def test_missing_or_duplicate_delivery_section_fails_closed(tmp_path: Path) -> None:
    text = _report_text()
    lines = text.splitlines()
    heading_index = next(i for i, line in enumerate(lines) if line.startswith("## DR-17 "))
    end_index = next(
        (i for i in range(heading_index + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    missing = "\n".join(lines[:heading_index] + lines[end_index:]) + "\n"
    duplicate = text + "\n" + "\n".join(lines[heading_index:end_index]) + "\n"

    assert "missing delivery sections: DR-17" in _validation_error(tmp_path, missing)
    assert "duplicate delivery sections: DR-17" in _validation_error(tmp_path, duplicate)


def test_wrong_section_title_or_order_fails_closed(tmp_path: Path) -> None:
    wrong_title = _report_text().replace("## DR-02 — 项目介绍", "## DR-02 — 产品概览", 1)
    wrong_order = wrong_title.replace("## DR-02 — 产品概览", "## DR-03 — 核心功能", 1)

    assert "DR-02 title does not match" in _validation_error(tmp_path, wrong_title)
    assert "duplicate delivery sections: DR-03" in _validation_error(tmp_path, wrong_order)


def test_each_section_requires_status_conclusion_and_known_evidence(tmp_path: Path) -> None:
    no_status = _replace_section_metadata(_report_text(), "DR-02", "Status", "-")
    no_conclusion = _replace_section_metadata(_report_text(), "DR-02", "Conclusion", "-")
    unknown_evidence = _replace_section_metadata(_report_text(), "DR-02", "Evidence IDs", "DEL-999")

    assert "DR-02 has invalid section status" in _validation_error(tmp_path, no_status)
    assert "DR-02 requires a conclusion" in _validation_error(tmp_path, no_conclusion)
    assert "DR-02 references unknown evidence DEL-999" in _validation_error(
        tmp_path, unknown_evidence
    )


def test_section_rejects_valid_but_wrong_status_or_evidence(tmp_path: Path) -> None:
    verified = _replace_section_metadata(_report_text(), "DR-03", "Status", "VERIFIED")
    swapped = _replace_section_metadata(_report_text(), "DR-03", "Evidence IDs", "DEL-001")

    assert "DR-03 status/evidence does not match" in _validation_error(tmp_path, verified)
    assert "DR-03 status/evidence does not match" in _validation_error(tmp_path, swapped)


def test_evidence_requires_fixed_command_exit_status_and_result(tmp_path: Path) -> None:
    text = _report_text()
    mutations = (
        ("Command", "Test-Path DELIVERY_REPORT.md", "does not match its fixed evidence contract"),
        ("Exit code", "NOT_RUN", "does not match its fixed evidence contract"),
        ("Status", "PENDING", "does not match its fixed evidence contract"),
        ("Result", "success", "does not match its fixed evidence contract"),
    )
    for column, value, expected in mutations:
        mutation = _replace_table_cell(text, "## Evidence index", "DEL-009", column, value)
        assert expected in _validation_error(tmp_path, mutation)


def test_missing_or_duplicate_evidence_fails_closed(tmp_path: Path) -> None:
    missing = _remove_table_row(_report_text(), "## Evidence index", "DEL-010")
    duplicate = _duplicate_table_row(_report_text(), "## Evidence index", "DEL-010")

    assert "missing evidence ids: DEL-010" in _validation_error(tmp_path, missing)
    assert "duplicate evidence ids: DEL-010" in _validation_error(tmp_path, duplicate)


def test_ready_is_rejected_while_any_blocker_is_open(tmp_path: Path) -> None:
    mutation = _report_text().replace("MUSEECHO V1 PARTIALLY READY", "MUSEECHO V1 READY", 1)

    assert "READY contradicts open blockers" in _validation_error(tmp_path, mutation)


def test_partially_ready_requires_each_exact_current_blocker(tmp_path: Path) -> None:
    for blocker_id in (
        "BLK-REMOTE-CI",
        "BLK-CLOUD-PUBLIC-TARGET",
        "BLK-FORMAL-OFFLINE-BUILD",
        "BLK-STUDENT-MANUAL",
        "BLK-CONTROLLER-BROWSER",
    ):
        mutation = _remove_table_row(_report_text(), "## Blocking reasons", blocker_id)
        assert f"required blocking reason is missing: {blocker_id}" in _validation_error(
            tmp_path, mutation
        )


def test_partially_ready_blocker_requires_pending_evidence_and_precise_closure(
    tmp_path: Path,
) -> None:
    no_evidence = _replace_table_cell(
        _report_text(), "## Blocking reasons", "BLK-REMOTE-CI", "Evidence IDs", "-"
    )
    vague = _replace_table_cell(
        _report_text(), "## Blocking reasons", "BLK-REMOTE-CI", "Closure criteria", "later"
    )

    assert "BLK-REMOTE-CI requires evidence" in _validation_error(tmp_path, no_evidence)
    assert "BLK-REMOTE-CI closure criteria are not precise" in _validation_error(tmp_path, vague)


def test_blocker_rejects_valid_but_wrong_owner_or_pending_evidence(tmp_path: Path) -> None:
    wrong_owner = _replace_table_cell(
        _report_text(),
        "## Blocking reasons",
        "BLK-STUDENT-MANUAL",
        "Owner",
        "Deployment owner",
    )
    wrong_evidence = _replace_table_cell(
        _report_text(),
        "## Blocking reasons",
        "BLK-STUDENT-MANUAL",
        "Evidence IDs",
        "DEL-901",
    )

    assert "BLK-STUDENT-MANUAL owner/evidence does not match" in _validation_error(
        tmp_path, wrong_owner
    )
    assert "BLK-STUDENT-MANUAL owner/evidence does not match" in _validation_error(
        tmp_path, wrong_evidence
    )


def test_product_audit_is_complete_machine_readable_and_controller_blocked() -> None:
    report = load_delivery_report(REPORT_PATH)

    assert tuple(item.item_id for item in report.product_audit_items) == EXPECTED_PRODUCT_AUDIT_IDS
    assert all(item.status == "CERT_TRUST_BLOCKED" for item in report.product_audit_items)
    assert all(item.evidence_ids for item in report.product_audit_items)


def test_product_audit_records_real_certificate_trust_block() -> None:
    report = load_delivery_report(REPORT_PATH)
    controller = next(
        item for item in report.product_audit_evidence if item.evidence_id == "PAE-900"
    )

    assert controller.kind == "CONTROLLER_COMMAND"
    assert controller.exit_code_raw == "1"
    assert controller.status == "BLOCKED"
    assert controller.result == (
        "service-health=ready; navigation=ERR_CERT_AUTHORITY_INVALID; manual-pass=0; "
        "controller-status=CERT_TRUST_BLOCKED; cleanup=pass"
    )


def test_product_audit_metadata_and_evidence_fail_closed(tmp_path: Path) -> None:
    product_path = ROOT / "docs" / "audits" / "PRODUCT_AUDIT.md"
    original = product_path.read_text(encoding="utf-8")
    mutations = (
        original.replace("CONTROLLER_BLOCKED", "CONTROLLER_READY", 1),
        _replace_table_cell(
            original,
            "## Evidence index",
            "PAE-900",
            "Command",
            "python -c pass",
        ),
        _replace_table_cell(
            original,
            "## Evidence index",
            "PAE-900",
            "Result",
            "controller-status=PASS; manual-pass=13",
        ),
    )

    for index, mutation in enumerate(mutations):
        mutated_path = tmp_path / f"PRODUCT_AUDIT-{index}.md"
        mutated_path.write_text(mutation, encoding="utf-8")
        report = load_delivery_report(REPORT_PATH, product_audit_path=mutated_path)
        with pytest.raises(DeliveryValidationError):
            validate_delivery_report(report, repo_root=ROOT, now=NOW)


def test_product_audit_scope_method_flow_and_notes_fail_closed(tmp_path: Path) -> None:
    product_path = ROOT / "docs" / "audits" / "PRODUCT_AUDIT.md"
    original = product_path.read_text(encoding="utf-8")
    mutations = (
        original.replace(
            "First-use product flow and product-quality review required by PLAN Task 24",
            "Automated regression only",
            1,
        ),
        original.replace(
            "The Task 24 controller started the no-build HTTPS development profile",
            "Merged automated E2E is complete manual visual PASS;",
            1,
        ),
        _replace_table_cell(
            original,
            "## Product audit matrix",
            "PA-01",
            "Flow step",
            "Skip first entry",
        ),
        _replace_table_cell(
            original,
            "## Product audit matrix",
            "PA-01",
            "Notes",
            "Automated E2E proves manual PASS.",
        ),
    )

    for index, mutation in enumerate(mutations):
        mutated_path = tmp_path / f"PRODUCT_AUDIT-semantics-{index}.md"
        mutated_path.write_text(mutation, encoding="utf-8")
        report = load_delivery_report(REPORT_PATH, product_audit_path=mutated_path)
        with pytest.raises(DeliveryValidationError):
            validate_delivery_report(report, repo_root=ROOT, now=NOW)


def test_delivery_evidence_records_merged_task23_ci() -> None:
    report = load_delivery_report(REPORT_PATH)
    ci = next(item for item in report.evidence if item.evidence_id == "DEL-004")

    assert ci.command == (
        "gh pr view 1 --repo Zzz148080/MuseEcho --json "
        "state,headRefOid,mergeCommit,statusCheckRollup,url"
    )
    assert ci.result == (
        "pr=1; state=MERGED; head=73869619bedf1298114d9755811f3f6e9f505de3; "
        "merge=79d87f4170f004f22d9e2c21151f59b757e272a3; quality=success; "
        "e2e=success; distribution=success"
    )


def test_delivery_conclusion_and_blocker_narrative_fail_closed(tmp_path: Path) -> None:
    conclusion = _replace_section_metadata(
        _report_text(),
        "DR-10",
        "Conclusion",
        "All remote, target-server, and manual browser gates passed.",
    )
    reason = _replace_table_cell(
        _report_text(),
        "## Blocking reasons",
        "BLK-CONTROLLER-BROWSER",
        "Reason",
        "All browser and manual checks passed.",
    )
    closure = _replace_table_cell(
        _report_text(),
        "## Blocking reasons",
        "BLK-CONTROLLER-BROWSER",
        "Closure criteria",
        "No further action is required because browser acceptance passed.",
    )

    assert "delivery narrative does not match" in _validation_error(tmp_path, conclusion)
    assert "delivery narrative does not match" in _validation_error(tmp_path, reason)
    assert "delivery narrative does not match" in _validation_error(tmp_path, closure)


def test_product_audit_cannot_claim_browser_pass_without_controller_execution(
    tmp_path: Path,
) -> None:
    product_path = ROOT / "docs" / "audits" / "PRODUCT_AUDIT.md"
    original = product_path.read_text(encoding="utf-8")
    mutation = _replace_table_cell(original, "## Product audit matrix", "PA-01", "Status", "PASS")
    mutated_path = tmp_path / "PRODUCT_AUDIT.md"
    mutated_path.write_text(mutation, encoding="utf-8")
    report = load_delivery_report(REPORT_PATH, product_audit_path=mutated_path)

    with pytest.raises(DeliveryValidationError, match="PA-01 cannot claim PASS"):
        validate_delivery_report(report, repo_root=ROOT, now=NOW)


def test_student_acceptance_and_reflection_remain_unclaimed(tmp_path: Path) -> None:
    checked = _replace_table_cell(
        _report_text(), "## Student final checklist", "STU-01", "Status", "COMPLETE"
    )
    assert "STU-01 must remain RESERVED for the student" in _validation_error(tmp_path, checked)

    reflection = (ROOT / "REFLECTION.md").read_text(encoding="utf-8")
    filled_reflection = reflection.replace(
        "<!-- STUDENT RESPONSE: leave blank until the student writes here -->",
        "I learned that this project was successful.",
        1,
    )
    reflection_path = tmp_path / "REFLECTION.md"
    reflection_path.write_text(filled_reflection, encoding="utf-8")
    report = load_delivery_report(REPORT_PATH, reflection_path=reflection_path)

    with pytest.raises(DeliveryValidationError, match="student reflection template was filled"):
        validate_delivery_report(report, repo_root=ROOT, now=NOW)


def test_current_status_documents_reject_stale_task23_or_task24_blocker(tmp_path: Path) -> None:
    stale = _report_text().replace("Task 24 current status", "Task 23 current status", 1)
    assert "DELIVERY_REPORT.md current status is stale" in _validation_error(tmp_path, stale)

    blocker = _report_text().replace("BLK-CONTROLLER-BROWSER", "TASK24-AUDIT", 1)
    assert "Task 24 audit cannot remain a current blocker" in _validation_error(tmp_path, blocker)


def test_checker_cli_accepts_the_committed_delivery_report() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/check_delivery_report.py", "DELIVERY_REPORT.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "17 delivery sections validated" in completed.stdout
    assert "readiness=MUSEECHO V1 PARTIALLY READY" in completed.stdout


def test_checker_cli_rejects_missing_report(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/check_delivery_report.py", str(tmp_path / "missing.md")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "delivery report validation failed" in completed.stderr
