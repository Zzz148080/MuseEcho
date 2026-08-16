from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

import scripts.check_acceptance_matrix as check_acceptance_matrix
from scripts.check_acceptance_matrix import (
    EXPECTED_ITEM_IDS,
    AuditValidationError,
    load_audit,
    validate_audit,
)
from scripts.check_engineering_audit import load_audit as load_engineering_audit

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "SPEC.md"
AUDIT_PATH = ROOT / "docs" / "audits" / "FUNCTIONAL_AUDIT.md"
NOW = datetime(2026, 8, 15, tzinfo=UTC)
HISTORICAL_EVIDENCE_COMMIT = "1047ce242884b6ba83a525524e88dcc44ab76a69"

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


def _require_git_history() -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("historical-tree integration requires Git")
    completed = subprocess.run(
        [git, "cat-file", "-e", f"{HISTORICAL_EVIDENCE_COMMIT}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        timeout=10,
    )
    if completed.returncode != 0:
        pytest.skip("historical-tree integration requires the retained Git object database")


def test_every_spec_acceptance_item_has_a_verdict_and_evidence():
    _require_git_history()
    audit = load_audit(SPEC_PATH, AUDIT_PATH)

    assert audit.missing_items == ()
    assert audit.duplicate_item_ids == ()
    assert all(item.verdict in {"PASS", "PARTIAL", "FAIL"} for item in audit.items)
    assert all(item.evidence_ids for item in audit.items if item.verdict == "PASS")
    validate_audit(audit, repo_root=ROOT, now=NOW)


def test_item_id_contract_covers_all_ac_and_definition_of_done_items():
    assert EXPECTED_ITEM_IDS == EXPECTED_IDS
    assert len(EXPECTED_ITEM_IDS) == 40


def test_current_definition_of_done_requires_github_ci_not_dual_ci() -> None:
    spec = SPEC_PATH.read_text(encoding="utf-8")

    assert check_acceptance_matrix._spec_issues(spec) == ()

    legacy_dual_ci = spec.replace(
        "合理 Git/PR 历史、GitHub CI、全过程文档",
        "合理 Git/PR 历史、双 CI 配置、全过程文档",
        1,
    )
    assert legacy_dual_ci != spec
    assert (
        "SPEC DOD-11 trace fragment is missing: "
        "合理 Git/PR 历史、GitHub CI、全过程文档"
        in check_acceptance_matrix._spec_issues(legacy_dual_ci)
    )


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


def test_current_frontend_evidence_accepts_78_and_rejects_stale_66(tmp_path: Path):
    _require_git_history()
    current = _audit_text()
    retained = current.replace("vitest-tests=66", "vitest-tests=78").replace(
        "12 files and 66 tests passed", "12 files and 78 tests passed"
    )
    audit = load_audit(SPEC_PATH, _write_audit(tmp_path, retained))

    validate_audit(audit, repo_root=ROOT, now=NOW)

    stale = _replace_table_cell(
        retained,
        "## Evidence index",
        "E001",
        "Result",
        "vitest-files=12; vitest-tests=66",
    )
    assert "E001 does not match its fixed evidence contract" in _validation_error(tmp_path, stale)


def test_exact_historical_evidence_uses_its_commit_tree_not_the_current_checkout() -> None:
    _require_git_history()
    audit = load_audit(SPEC_PATH, AUDIT_PATH)
    evidence = next(record for record in audit.evidence if record.evidence_id == "E004")

    assert evidence.boundary_sha256 != check_acceptance_matrix._current_boundary_sha256(ROOT)

    validate_audit(audit, repo_root=ROOT, now=NOW)


def test_historical_evidence_fails_closed_when_git_is_unavailable(monkeypatch):
    monkeypatch.setenv("PATH", "")
    audit = load_audit(SPEC_PATH, AUDIT_PATH)

    with pytest.raises(AuditValidationError) as caught:
        validate_audit(audit, repo_root=ROOT, now=NOW)

    assert "E004 exact historical commit/tree is unavailable" in str(caught.value)


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

    error = _validation_error(tmp_path, mutation)
    assert "E004 does not match its fixed evidence contract" in error
    assert "E004 historical commit does not match its exact evidence commit" in error


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
def test_historical_evidence_requires_exact_commit_boundary_hash(tmp_path: Path, replacement: str):
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

    assert "E004 historical boundary SHA256" in _validation_error(tmp_path, mutation)


def test_current_boundary_is_stable_across_text_checkout_line_endings(tmp_path: Path):
    source = tmp_path / "src" / "museecho" / "app.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"first\nsecond\n")
    lf_boundary = check_acceptance_matrix._current_boundary_sha256(tmp_path)

    source.write_bytes(b"first\r\nsecond\r\n")
    crlf_boundary = check_acceptance_matrix._current_boundary_sha256(tmp_path)

    assert crlf_boundary == lf_boundary


def test_boundary_keeps_binary_line_endings_exact():
    relative_path = "tests/api/fixture.bin"
    crlf_content = b"\0first\r\nsecond\r\n"
    lf_boundary = check_acceptance_matrix._digest_boundary_entries(
        [(relative_path, b"\0first\nsecond\n")]
    )
    crlf_boundary = check_acceptance_matrix._digest_boundary_entries(
        [(relative_path, crlf_content)]
    )
    expected = hashlib.sha256()
    expected.update(relative_path.encode("utf-8"))
    expected.update(b"\0")
    expected.update(hashlib.sha256(crlf_content).hexdigest().encode("ascii"))
    expected.update(b"\n")

    assert crlf_boundary != lf_boundary
    assert crlf_boundary == expected.hexdigest()


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
    "blocker_id",
    (
        "TC-021",
        "CURRENT-BRANCH-DISTRIBUTION",
        "REMOTE-CI",
        "TASK24-AUDIT",
        "STUDENT-MANUAL",
    ),
)
def test_external_follow_up_and_manual_work_cannot_be_marked_resolved_without_execution(
    tmp_path: Path, blocker_id: str
):
    mutation = _replace_table_cell(
        _audit_text(), "## Open blockers", blocker_id, "Status", "RESOLVED"
    )

    expected = (
        f"{blocker_id} must remain OPEN in the tracked audit"
        if blocker_id == "CURRENT-BRANCH-DISTRIBUTION"
        else f"{blocker_id} cannot be RESOLVED with NOT_RUN evidence"
    )
    assert expected in _validation_error(tmp_path, mutation)


def test_green_github_evidence_closes_frontend_and_browser_gaps() -> None:
    contract = check_acceptance_matrix.EVIDENCE_CONTRACTS["E002"]
    audit = load_audit(SPEC_PATH, AUDIT_PATH)
    item = next(item for item in audit.items if item.item_id == "AC-F-4")

    assert contract.kind == "IMPLEMENTATION_BOUNDARY_COMMAND"
    assert contract.exit_code_raw == "0"
    assert contract.supports_pass is True
    assert item.verdict == "PASS"
    assert item.disposition == "-"


def test_current_branch_evidence_does_not_recast_pre_feature_smoke_as_current() -> None:
    contracts = check_acceptance_matrix.EVIDENCE_CONTRACTS
    audit = load_audit(SPEC_PATH, AUDIT_PATH)
    evidence_by_id = {record.evidence_id: record for record in audit.evidence}
    remote_ci_item = next(item for item in audit.items if item.item_id == "DOD-10")
    remote_ci_blocker = next(
        blocker for blocker in audit.blockers if blocker.blocker_id == "REMOTE-CI"
    )

    assert "museecho-task3-verification-env:latest" in contracts["E008"].command
    assert "pytest-tests=649" != contracts["E008"].result
    assert contracts["E008"].kind == "IMPLEMENTATION_BOUNDARY_COMMAND"
    assert evidence_by_id["E008"].kind == "IMPLEMENTATION_BOUNDARY_COMMAND"
    assert "predates 7f8412b" in evidence_by_id["E008"].summary
    assert contracts["E009"].kind == "IMPLEMENTATION_BOUNDARY_COMMAND"
    assert contracts["E009"].supports_pass is False
    assert "-NoBuild -ReleaseManifest" in contracts["E009"].command
    assert "mypy-src-files=47" in contracts["E010"].result
    assert all("E009" not in item.evidence_ids for item in audit.items if item.verdict == "PASS")
    assert contracts["E003"].result == "secret-scan-files=210"
    assert "app-occurrences=181" in contracts["E902"].result
    assert "gateway-occurrences=0" in contracts["E902"].result
    assert evidence_by_id["E901"].kind == "EXTERNAL_NOT_RUN"
    assert "final branch GitHub CI" in evidence_by_id["E901"].command
    assert evidence_by_id["E901"].path == ".github/workflows/ci.yml"
    assert contracts["E906"].kind == "IMPLEMENTATION_BOUNDARY_COMMAND"
    assert contracts["E906"].supports_pass is True
    assert "run=31630284744" in contracts["E906"].result
    assert "head=2b2730eaf232f8edf3ead77be1830fa50d927a47" in contracts["E906"].result
    assert "quality=success; e2e=success; distribution=success" in contracts["E906"].result
    assert contracts["E906"].coverage_ids == (
        "AC-C-3",
        "AC-F-1",
        "AC-F-4",
        "DOD-01",
        "DOD-03",
        "DOD-07",
        "DOD-10",
    )
    assert remote_ci_item.evidence_ids == ("E901", "E906")
    assert remote_ci_blocker.evidence_ids == ("E901",)


def test_pre_feature_smoke_cannot_be_recast_as_current_branch_evidence(
    tmp_path: Path,
) -> None:
    for evidence_id in ("E008", "E009"):
        mutation = _replace_table_cell(
            _audit_text(), "## Evidence index", evidence_id, "Kind", "CURRENT_COMMAND"
        )

        assert f"{evidence_id} does not match its fixed evidence contract" in _validation_error(
            tmp_path, mutation
        )


@pytest.mark.parametrize("evidence_id", ("E002", "E906"))
def test_product_ci_pass_uses_the_last_implementation_boundary_not_the_branch_tip(
    evidence_id: str,
) -> None:
    audit = load_audit(SPEC_PATH, AUDIT_PATH)
    evidence = next(record for record in audit.evidence if record.evidence_id == evidence_id)

    assert evidence.kind == "IMPLEMENTATION_BOUNDARY_COMMAND"
    assert "implementation boundary" in evidence.summary.lower()
    assert "exact-head" not in evidence.summary.lower()


def test_old_current_command_kind_cannot_recast_implementation_boundary_as_tip_evidence(
    tmp_path: Path,
) -> None:
    mutation = _replace_table_cell(
        _audit_text(), "## Evidence index", "E906", "Kind", "CURRENT_COMMAND"
    )

    assert "E906 does not match its fixed evidence contract" in _validation_error(
        tmp_path, mutation
    )


def test_functional_engineering_evidence_matches_current_engineering_audit() -> None:
    contract = check_acceptance_matrix.EVIDENCE_CONTRACTS["E902"]
    engineering = load_engineering_audit(ROOT / "docs" / "audits" / "ENGINEERING_AUDIT.md")
    counts = Counter((finding.severity, finding.status) for finding in engineering.findings)
    open_count = sum(count for (_severity, status), count in counts.items() if status == "OPEN")
    expected_prefix = (
        f"findings={len(engineering.findings)}; "
        f"fixed-high={counts[('High', 'FIXED')]}; "
        f"fixed-medium={counts[('Medium', 'FIXED')]}; "
        f"verified-medium={counts[('Medium', 'VERIFIED')]}; "
        f"blocked-medium={counts[('Medium', 'BLOCKED')]}; open={open_count}; "
    )

    assert contract.result.startswith(expected_prefix)


def test_current_acceptance_evidence_uses_the_executed_locked_python_command(
    request: pytest.FixtureRequest,
) -> None:
    expected_command = (
        ".venv\\Scripts\\python.exe -m pytest tests/unit/test_acceptance_matrix.py -q "
        "--basetemp tmp/task23-e014 -p no:cacheprovider; "
        "if ($LASTEXITCODE) { exit $LASTEXITCODE }; "
        ".venv\\Scripts\\python.exe scripts/check_acceptance_matrix.py "
        "SPEC.md docs/audits/FUNCTIONAL_AUDIT.md"
    )
    contract = check_acceptance_matrix.EVIDENCE_CONTRACTS["E014"]
    engineering = load_engineering_audit(ROOT / "docs" / "audits" / "ENGINEERING_AUDIT.md")
    engineering_e030 = next(
        evidence for evidence in engineering.evidence if evidence.evidence_id == "E030"
    )
    acceptance_path = Path(__file__).resolve()
    collected_count = sum(
        Path(str(item.path)).resolve() == acceptance_path for item in request.session.items
    )

    assert contract.command == expected_command
    assert engineering_e030.command == expected_command
    assert contract.result == (f"pytest-tests={collected_count}; pass=31; partial=9; fail=0")
    assert engineering_e030.result == (
        f"{collected_count} passed; 40 items validated PASS=31 PARTIAL=9 FAIL=0"
    )


def test_task23_report_labels_superseded_statistics_and_attributes_round_four() -> None:
    report = (ROOT / ".superpowers" / "sdd" / "PLAN" / "task-23-report.md").read_text(
        encoding="utf-8"
    )

    assert "## 初始实现验证（已由后续复审轮取代）" in report
    assert "初始实现 focused GREEN（已由后续复审轮取代）" in report
    assert "Round-4 implementation is committed as `f75c808" in report


def test_audit_generated_time_and_evidence_time_must_be_real_utc(tmp_path: Path):
    text = _audit_text()
    generated_line = next(
        line for line in text.splitlines() if line.startswith("- **Generated at UTC:**")
    )
    mutation = text.replace(generated_line, "- **Generated at UTC:** `2999-08-12T19:15:00Z`", 1)

    assert "audit generated time is future-dated" in _validation_error(tmp_path, mutation)


def test_checker_cli_accepts_the_committed_matrix():
    _require_git_history()
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
