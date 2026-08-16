from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

import scripts.check_engineering_audit as checker
from scripts.check_engineering_audit import (
    EXPECTED_DOMAINS,
    AuditValidationError,
    EngineeringAudit,
    load_audit,
    validate_audit,
)

ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "docs" / "audits" / "ENGINEERING_AUDIT.md"
NOW = datetime(2026, 8, 15, tzinfo=UTC)
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


def _audit_text_with_formal_build_blocker() -> str:
    return _audit_text()


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


def test_verified_evidence_gap_requires_not_run_and_current_green(tmp_path: Path) -> None:
    mutation = _replace_table_cell(_audit_text(), FINDING_HEADING, "ENG-006", "Status", "VERIFIED")
    mutation = _replace_table_cell(
        mutation,
        FINDING_HEADING,
        "ENG-006",
        "Disposition",
        "VERIFIED: implementation-boundary CI executed the formerly unavailable "
        "frontend and browser gates.",
    )
    verified = load_audit(_write_audit(tmp_path, mutation))

    validate_audit(verified, repo_root=ROOT, now=NOW)

    without_not_run = _replace_table_cell(
        mutation, FINDING_HEADING, "ENG-006", "Evidence IDs", "E037"
    )
    assert "ENG-006 VERIFIED requires historical NOT_RUN and current GREEN evidence" in (
        _validation_error(tmp_path, without_not_run)
    )


def test_verified_gap_uses_implementation_boundary_green_not_branch_tip_evidence() -> None:
    audit = load_audit(AUDIT_PATH)
    evidence = next(item for item in audit.evidence if item.evidence_id == "E037")
    finding = next(item for item in audit.findings if item.finding_id == "ENG-006")

    assert evidence.kind == "IMPLEMENTATION_BOUNDARY_COMMAND"
    assert "implementation boundary" in evidence.result.lower()
    assert "exact-head" not in finding.description.lower()
    assert "exact head" not in finding.disposition.lower()


def test_old_current_command_kind_cannot_recast_e037_as_branch_tip_evidence(
    tmp_path: Path,
) -> None:
    mutation = _replace_table_cell(
        _audit_text(), EVIDENCE_HEADING, "E037", "Kind", "CURRENT_COMMAND"
    )

    assert "E037 does not match its fixed evidence contract" in _validation_error(
        tmp_path, mutation
    )


def test_verified_evidence_gap_cannot_masquerade_as_fixed_without_red(tmp_path: Path) -> None:
    mutation = _replace_table_cell(_audit_text(), FINDING_HEADING, "ENG-006", "Status", "FIXED")

    assert "ENG-006 FIXED requires RED and GREEN evidence" in _validation_error(tmp_path, mutation)


def test_verified_evidence_gap_rejects_unrelated_not_run_record(tmp_path: Path) -> None:
    mutation = _replace_table_cell(
        _audit_text(), EVIDENCE_HEADING, "E015", "Command", "NOT RUN: unrelated tool missing"
    )
    mutation = _replace_table_cell(
        mutation, EVIDENCE_HEADING, "E015", "Path", "scripts/check_engineering_audit.py"
    )
    mutation = _replace_table_cell(
        mutation,
        EVIDENCE_HEADING,
        "E015",
        "Result",
        "Unrelated unavailable command cannot establish the browser evidence gap.",
    )

    assert "E015 does not match its fixed evidence contract" in _validation_error(
        tmp_path, mutation
    )


def test_verified_evidence_gap_rejects_unrelated_current_green_record(tmp_path: Path) -> None:
    mutation = _replace_table_cell(
        _audit_text(),
        EVIDENCE_HEADING,
        "E037",
        "Command",
        "gh run view 99999999999 --repo Zzz148080/MuseEcho --json conclusion,jobs,url,headSha",
    )
    mutation = _replace_table_cell(
        mutation, EVIDENCE_HEADING, "E037", "Path", "frontend/package.json"
    )
    mutation = _replace_table_cell(
        mutation,
        EVIDENCE_HEADING,
        "E037",
        "Result",
        "Unrelated successful frontend package metadata inspection completed.",
    )

    assert "E037 does not match its fixed evidence contract" in _validation_error(
        tmp_path, mutation
    )


@pytest.mark.parametrize(
    ("finding_id", "red_id", "green_id"),
    (
        ("ENG-001", "E002", "E003"),
        ("ENG-002", "E004", "E005"),
        ("ENG-003", "E006", "E007"),
        ("ENG-004", "E008", "E009"),
        ("ENG-005", "E010", "E011"),
        ("ENG-009", "E033", "E034"),
    ),
)
def test_each_fixed_finding_rejects_coherent_unrelated_red_green_evidence(
    tmp_path: Path, finding_id: str, red_id: str, green_id: str
) -> None:
    mutation = _audit_text()
    for evidence_id, exit_code in ((red_id, 23), (green_id, 0)):
        mutation = _replace_table_cell(
            mutation,
            EVIDENCE_HEADING,
            evidence_id,
            "Command",
            f"python -c print-unrelated-{finding_id.lower()}",
        )
        mutation = _replace_table_cell(
            mutation,
            EVIDENCE_HEADING,
            evidence_id,
            "Path",
            "scripts/check_engineering_audit.py",
        )
        mutation = _replace_table_cell(
            mutation,
            EVIDENCE_HEADING,
            evidence_id,
            "Result",
            f"unrelated coherent evidence exit={exit_code}",
        )

    assert (
        f"{finding_id} evidence {red_id} does not match its fixed evidence contract"
        in _validation_error(tmp_path, mutation)
    )


@pytest.mark.parametrize(
    "finding_id",
    ("ENG-001", "ENG-002", "ENG-003", "ENG-004", "ENG-005", "ENG-009"),
)
def test_each_fixed_finding_rejects_unrelated_evidence_coverage(
    tmp_path: Path, finding_id: str
) -> None:
    mutation = _replace_table_cell(
        _audit_text(), FINDING_HEADING, finding_id, "Evidence IDs", "E001, E012"
    )

    assert f"{finding_id} evidence coverage does not match its fixed contract" in _validation_error(
        tmp_path, mutation
    )


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
        _audit_text(), FINDING_HEADING, "ENG-007", "Disposition", "internal follow-up"
    )
    mutation = _replace_table_cell(mutation, FINDING_HEADING, "ENG-007", "Evidence IDs", "E003")

    assert "ENG-007 BLOCKED requires a real external condition" in _validation_error(
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


@pytest.mark.parametrize("evidence_id", ("E020", "E021", "E022", "E023", "E024", "E025"))
def test_scan_audit_and_release_verification_cannot_be_rewritten_as_vacuous_success(
    tmp_path: Path, evidence_id: str
) -> None:
    mutation = _replace_table_cell(
        _audit_text(), EVIDENCE_HEADING, evidence_id, "Command", "python -c pass"
    )
    mutation = _replace_table_cell(
        mutation, EVIDENCE_HEADING, evidence_id, "Result", "exit=0; findings=0"
    )
    mutation = _replace_table_cell(
        mutation, EVIDENCE_HEADING, evidence_id, "Path", "scripts/check_engineering_audit.py"
    )

    assert f"{evidence_id} does not match its fixed evidence contract" in _validation_error(
        tmp_path, mutation
    )


def test_security_domain_coverage_cannot_omit_a_gate(tmp_path: Path) -> None:
    mutation = _replace_table_cell(
        _audit_text(),
        DOMAIN_HEADING,
        "runtime-image-vulnerabilities",
        "Evidence IDs",
        "E020, E022, E023, E024, E025",
    )

    assert "runtime-image-vulnerabilities evidence coverage does not match its fixed contract" in (
        _validation_error(tmp_path, mutation)
    )


def _set_nested(payload: dict[str, object], path: tuple[str, ...], value: object) -> None:
    target: object = payload
    for key in path[:-1]:
        assert isinstance(target, dict)
        target = target[key]
    assert isinstance(target, dict)
    target[path[-1]] = value


@pytest.mark.parametrize(
    ("field_path", "replacement"),
    (
        (("app", "daemon_image_id"), "sha256:" + "1" * 64),
        (("app", "config_image_id"), "sha256:" + "2" * 64),
        (("app", "tar_sha256"), "3" * 64),
        (("app", "raw_sha256"), "4" * 64),
        (("app", "package_files_sha256"), "5" * 64),
        (("app", "inventory_sha256"), "6" * 64),
        (("app", "vex_sha256"), "7" * 64),
        (("app", "tuple_sha256"), "8" * 64),
        (("app", "audit_exit"), 7),
        (("app", "vex_gate_exit"), 7),
        (("gateway", "daemon_image_id"), "sha256:" + "9" * 64),
        (("gateway", "config_image_id"), "sha256:" + "a" * 64),
        (("gateway", "tar_sha256"), "b" * 64),
        (("gateway", "raw_sha256"), "c" * 64),
        (("gateway", "gate_exit"), 7),
        (("trivy", "image_digest"), "sha256:" + "d" * 64),
        (("trivy", "db_sha256"), "e" * 64),
        (("trivy", "db_updated_at"), "2026-08-10T00:00:00Z"),
        (("boundary", "task20_base_daemon_image_id"), "sha256:" + "f" * 64),
        (("boundary", "policy_sha256"), "0" * 64),
        (("boundary", "runtime_boundary_sha256"), "1" * 64),
        (("release_identity_sha256",), "2" * 64),
        (("release_verify_exit",), 7),
    ),
)
def test_security_manifest_rejects_coherent_audit_only_field_rewrites(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field_path: tuple[str, ...],
    replacement: object,
) -> None:
    manifest = json.loads(
        (ROOT / "docs/audits/evidence/task23-security-manifest.json").read_text(encoding="utf-8")
    )
    _set_nested(manifest, field_path, replacement)
    path = tmp_path / "task23-security-manifest.json"
    encoded = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(encoded)
    monkeypatch.setattr(checker, "SECURITY_MANIFEST_PATH", str(path))
    monkeypatch.setattr(checker, "SECURITY_MANIFEST_SHA256", hashlib.sha256(encoded).hexdigest())

    assert "security evidence manifest field contract changed" in _validation_error(
        tmp_path, _audit_text()
    )


def test_security_manifest_recomputes_historical_policy_runtime_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = json.loads((ROOT / checker.SECURITY_POLICY_SNAPSHOT_PATH).read_text(encoding="utf-8"))
    policy["runtime_boundary"]["src/museecho/runtime.py"] = "0" * 64
    path = tmp_path / "task23-image-vulnerability-policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")

    monkeypatch.setattr(checker, "SECURITY_POLICY_SNAPSHOT_PATH", str(path))
    errors: list[str] = []

    checker._validate_security_manifest(ROOT, errors)

    assert "security manifest runtime boundary does not match historical policy snapshot" in errors


def test_historical_security_manifest_validation_is_independent_of_current_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def drifted_current_runtime_boundary(_repository_root: Path) -> dict[str, str]:
        return {"src/museecho/runtime.py": "0" * 64}

    monkeypatch.setattr(
        checker,
        "build_runtime_boundary_manifest",
        drifted_current_runtime_boundary,
        raising=False,
    )
    errors: list[str] = []

    checker._validate_security_manifest(ROOT, errors)

    assert "security manifest runtime boundary does not match current source" not in errors


def test_audit_generated_time_cannot_be_future_dated(tmp_path: Path) -> None:
    text = _audit_text()
    generated_line = next(
        line for line in text.splitlines() if line.startswith("- **Generated at UTC:**")
    )
    mutation = text.replace(generated_line, "- **Generated at UTC:** `2999-08-12T19:15:00Z`", 1)

    assert "audit generated time is future-dated" in _validation_error(tmp_path, mutation)


def test_checker_cli_accepts_the_committed_engineering_audit() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_engineering_audit.py"),
            str(AUDIT_PATH),
            "--schema-only",
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert "engineering findings validated" in completed.stdout
    assert "schema only; retained materials NOT validated" in completed.stdout


def test_completion_cli_rejects_missing_retained_security_materials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MUSEECHO_TASK23_EVIDENCE_DIR", str(tmp_path / "missing-evidence"))
    monkeypatch.setenv("MUSEECHO_TASK20_TRIVY_DB_DIR", str(tmp_path / "missing-db"))

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

    assert completed.returncode != 0
    assert "retained security material" in completed.stderr


def test_completion_material_validation_rejects_present_but_forged_files(
    tmp_path: Path,
) -> None:
    materials = tmp_path / "evidence"
    database = tmp_path / "db"
    materials.mkdir()
    database.mkdir()
    for filename in checker.SECURITY_MATERIAL_FILENAMES:
        (materials / filename).write_bytes(f"forged:{filename}".encode())
    (database / "trivy.db").write_bytes(b"forged-db")
    (database / "metadata.json").write_text(
        '{"UpdatedAt":"2026-08-09T12:54:52.355618652Z"}', encoding="utf-8"
    )

    with pytest.raises(AuditValidationError, match="retained security material digest mismatch"):
        checker.validate_security_materials(
            materials_dir=materials,
            trivy_db_dir=database,
        )


@pytest.mark.parametrize(
    "missing_name",
    (*checker.SECURITY_MATERIAL_FILENAMES, "trivy.db", "metadata.json"),
)
def test_completion_material_validation_rejects_each_missing_input(
    tmp_path: Path, missing_name: str
) -> None:
    materials = tmp_path / "evidence"
    database = tmp_path / "db"
    materials.mkdir()
    database.mkdir()
    for filename in checker.SECURITY_MATERIAL_FILENAMES:
        if filename != missing_name:
            (materials / filename).write_bytes(b"present")
    for filename in ("trivy.db", "metadata.json"):
        if filename != missing_name:
            (database / filename).write_bytes(b"present")

    with pytest.raises(AuditValidationError, match=re.escape(missing_name)):
        checker.validate_security_materials(
            materials_dir=materials,
            trivy_db_dir=database,
        )


def test_scan_summary_counts_occurrences_severity_and_distinct_cves() -> None:
    scan = {
        "Results": [
            {
                "Vulnerabilities": [
                    {"VulnerabilityID": "CVE-1", "Severity": "HIGH"},
                    {"VulnerabilityID": "CVE-1", "Severity": "CRITICAL"},
                    {"VulnerabilityID": "CVE-2", "Severity": "HIGH"},
                ]
            },
            {"Vulnerabilities": None},
        ]
    }

    assert checker._scan_summary(scan) == {
        "occurrences": 3,
        "high_occurrences": 2,
        "critical_occurrences": 1,
        "distinct_cves": 2,
    }


def test_scan_summary_rejects_malformed_vulnerability_inventory() -> None:
    with pytest.raises(AuditValidationError, match="raw scan Results must be an array"):
        checker._scan_summary({"Results": None})

    with pytest.raises(AuditValidationError, match="Vulnerabilities must be an array or null"):
        checker._scan_summary({"Results": [{"Vulnerabilities": {}}]})


def test_canonical_finding_digest_is_order_stable_and_content_sensitive() -> None:
    first = {"cve": "CVE-1", "package": "alpha", "severity": "HIGH"}
    second = {"cve": "CVE-2", "package": "beta", "severity": "CRITICAL"}

    observed = checker._canonical_finding_digest([second, first])

    assert observed == checker._canonical_finding_digest([first, second])
    assert observed != checker._canonical_finding_digest([first, {**second, "severity": "HIGH"}])


def test_trivy_metadata_and_local_image_identity_are_fail_closed() -> None:
    expected = checker.SECURITY_MANIFEST_CONTRACT
    image_ids = {
        "museecho-app:task23-review1": expected["app"]["daemon_image_id"],
        "museecho-gateway:local": expected["gateway"]["daemon_image_id"],
        "museecho-app:task20-final": expected["boundary"]["task20_base_daemon_image_id"],
        "aquasec/trivy:0.70.0": expected["trivy"]["image_digest"],
    }

    checker._validate_trivy_metadata({"UpdatedAt": expected["trivy"]["db_updated_at"]}, expected)
    checker._validate_local_image_identities(image_ids.__getitem__, expected)

    with pytest.raises(AuditValidationError, match="Trivy DB metadata UpdatedAt mismatch"):
        checker._validate_trivy_metadata({"UpdatedAt": "2000-01-01T00:00:00Z"}, expected)
    with pytest.raises(AuditValidationError, match="local image identity mismatch"):
        checker._validate_local_image_identities(lambda _tag: "sha256:" + "0" * 64, expected)


def test_completion_cli_accepts_the_actual_retained_materials_when_available() -> None:
    materials = ROOT / "tmp" / "task23-engineering"
    database = ROOT.parent / "feat-20-production-delivery" / "tmp" / "trivy-cache" / "db"
    if not materials.is_dir() or not database.is_dir():
        pytest.skip("Task 23 retained completion materials are not present in this checkout")

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_engineering_audit.py"),
            str(AUDIT_PATH),
            "--materials-dir",
            str(materials),
            "--trivy-db-dir",
            str(database),
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=180,
    )

    assert completed.returncode == 0, completed.stderr
    assert "completion materials validated" in completed.stdout
    assert "10" in completed.stdout


def test_formal_dockerfile_offline_build_blocker_is_a_fixed_audit_contract(
    tmp_path: Path,
) -> None:
    audit = load_audit(_write_audit(tmp_path, _audit_text_with_formal_build_blocker()))

    validate_audit(audit, repo_root=ROOT, now=NOW)


def test_formal_dockerfile_offline_build_blocker_cannot_be_deleted(tmp_path: Path) -> None:
    mutation = _remove_table_row(
        _audit_text_with_formal_build_blocker(), FINDING_HEADING, "ENG-010"
    )

    assert "missing findings: ENG-010" in _validation_error(tmp_path, mutation)


@pytest.mark.parametrize(("column", "value"), (("Severity", "Low"), ("Status", "FIXED")))
def test_formal_dockerfile_offline_build_blocker_cannot_be_downgraded_or_fake_fixed(
    tmp_path: Path, column: str, value: str
) -> None:
    mutation = _replace_table_cell(
        _audit_text_with_formal_build_blocker(), FINDING_HEADING, "ENG-010", column, value
    )

    assert "ENG-010 does not match its fixed finding contract" in _validation_error(
        tmp_path, mutation
    )


def test_current_acceptance_evidence_is_a_fixed_engineering_contract(tmp_path: Path) -> None:
    expected_command = (
        ".venv\\Scripts\\python.exe -m pytest tests/unit/test_acceptance_matrix.py -q "
        "--basetemp tmp/task23-e014 -p no:cacheprovider; "
        "if ($LASTEXITCODE) { exit $LASTEXITCODE }; "
        ".venv\\Scripts\\python.exe scripts/check_acceptance_matrix.py "
        "SPEC.md docs/audits/FUNCTIONAL_AUDIT.md"
    )
    collected_count = 47
    expected_result = f"{collected_count} passed; 40 items validated PASS=31 PARTIAL=9 FAIL=0"

    assert checker.FIXED_EVIDENCE_CONTRACTS["E030"] == (
        "CURRENT_COMMAND",
        expected_command,
        "docs/audits/FUNCTIONAL_AUDIT.md",
        expected_result,
    )

    mutation = _replace_table_cell(
        _audit_text(), EVIDENCE_HEADING, "E030", "Result", "36 passed; stale current result"
    )
    assert "E030 does not match its fixed evidence contract" in _validation_error(
        tmp_path, mutation
    )


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("Command", "python -c pass"),
        ("Result", "forged static quality gates passed"),
    ),
)
def test_current_dual_platform_type_evidence_is_a_fixed_engineering_contract(
    tmp_path: Path, column: str, value: str
) -> None:
    mutation = _replace_table_cell(_audit_text(), EVIDENCE_HEADING, "E012", column, value)

    assert "E012 does not match its fixed evidence contract" in _validation_error(
        tmp_path, mutation
    )


def test_current_engineering_gates_do_not_recast_pre_feature_image_evidence() -> None:
    contracts = checker.FIXED_EVIDENCE_CONTRACTS

    assert "mypy each passed 47 source files" in contracts["E012"][3]
    assert "museecho-task3-verification-env:latest" in contracts["E013"][1]
    assert contracts["E022"][0] == "IMPLEMENTATION_BOUNDARY_COMMAND"
    assert "pre-feature task 23 image" in contracts["E022"][3].lower()


def test_pre_feature_image_audit_cannot_be_recast_as_current_runtime_evidence(
    tmp_path: Path,
) -> None:
    mutation = _replace_table_cell(
        _audit_text(), EVIDENCE_HEADING, "E022", "Kind", "CURRENT_COMMAND"
    )

    assert "E022 does not match its fixed evidence contract" in _validation_error(
        tmp_path, mutation
    )


def test_checker_cli_help_is_runnable_outside_the_repository(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_engineering_audit.py"), "--help"],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
