from __future__ import annotations

import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.check_delivery_report import (
    EVIDENCE_CONTRACTS,
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
NOW = datetime(2026, 8, 18, tzinfo=UTC)


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


def _swap_table_rows(text: str, heading: str, first_key: str, second_key: str) -> str:
    lines = text.splitlines()
    start, end = _table_bounds(lines, heading)
    indexes = {lines[index].split("|")[1].strip(): index for index in range(start + 2, end)}
    first_index = indexes[first_key]
    second_index = indexes[second_key]
    lines[first_index], lines[second_index] = lines[second_index], lines[first_index]
    return "\n".join(lines) + "\n"


def _replace_section_metadata(text: str, section_id: str, label: str, value: str) -> str:
    lines = text.splitlines()
    heading_index = next(
        index for index, line in enumerate(lines) if line.startswith(f"## {section_id} ")
    )
    end_index = next(
        (index for index in range(heading_index + 1, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    prefix = f"- **{label}：**"
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
    assert EXPECTED_EVIDENCE_IDS[:14] == tuple(f"DEL-{index:03d}" for index in range(1, 15))
    assert EXPECTED_PRODUCT_AUDIT_IDS == tuple(f"PA-{index:02d}" for index in range(1, 14))
    assert EXPECTED_STUDENT_CHECK_IDS == tuple(f"STU-{index:02d}" for index in range(1, 7))


def test_task24_github_boundary_is_fixed_while_external_work_remains_deferred(
    tmp_path: Path,
) -> None:
    report = load_delivery_report(REPORT_PATH)
    github = next(item for item in report.evidence if item.evidence_id == "DEL-011")
    final_ci = next(item for item in report.evidence if item.evidence_id == "DEL-012")
    release_main_ci = next(item for item in report.evidence if item.evidence_id == "DEL-013")
    formal_release = next(item for item in report.evidence if item.evidence_id == "DEL-014")
    gitlab = next(item for item in report.evidence if item.evidence_id == "DEL-900")
    cloud = next(item for item in report.evidence if item.evidence_id == "DEL-901")

    assert github.kind == "IMPLEMENTATION_BOUNDARY_COMMAND"
    assert github.result == (
        "run=31687703913; head=de5bc6f949e6e98cff32f16116708ec7b7409c9d; "
        "quality=success; e2e=success; distribution=success"
    )
    assert github.exit_code_raw == "0"
    assert github.status == "PASS"
    assert github.summary == (
        "仅作为历史任务 24 实现证据；它不能验证最终 PR SHA，后者由 DEL-012 单独记录。"
    )
    assert final_ci.result == (
        "run=31966788273; head=0674f74f4097e46cee98c4715a62ad5aa55101cf; "
        "branch=codex/expand-common-audio-formats; quality=success (5m43s); "
        "e2e=success (3m10s); distribution=success (7m30s)"
    )
    assert final_ci.status == "PASS"
    assert release_main_ci.result == (
        "run=31997390847; head=d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1; "
        "branch=main; quality=success; e2e=success; distribution=success; artifacts=quota-skipped"
    )
    assert release_main_ci.command.endswith(
        "status,conclusion,headBranch,headSha,jobs,url; gh api "
        "repos/Zzz148080/MuseEcho/actions/runs/31997390847/artifacts"
    )
    assert release_main_ci.status == "PASS"
    assert formal_release.result == (
        "tag=v0.1.0; target=d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1; "
        "draft=false; prerelease=false; assets=4; tag-resolved-to-target=pass; "
        "asset-metadata=pass; checksum-file-self-digest=pass; checksum-payloads=pass; "
        "offline-smoke=pass"
    )
    assert formal_release.command.endswith(
        "scripts/verify_github_release.py --action Smoke "
        "--manifest release/v0.1.0-manifest.json --assets-directory $releaseDir --download"
    )
    assert formal_release.status == "PASS"
    assert gitlab.command == "NOT RUN: GitLab has no Task 24 pipeline"
    assert gitlab.result == "gitlab=NOT_RUN"
    assert gitlab.exit_code_raw == "NOT_RUN"
    assert gitlab.status == "DEFERRED"
    assert cloud.exit_code_raw == "NOT_RUN"
    assert cloud.status == "DEFERRED"
    assert "Task 24 GitHub branch-tip gate has not run" not in report.raw_text

    forged = _replace_table_cell(
        _report_text(), "## 证据索引", "DEL-011", "结果", "quality=success"
    )
    assert "DEL-011 does not match its fixed evidence contract" in _validation_error(
        tmp_path, forged
    )

    stale_branch_tip = _replace_table_cell(
        _report_text(), "## 证据索引", "DEL-011", "摘要", "最终分支顶端 CI 已通过。"
    )
    assert "DEL-011 must remain historical Task 24 implementation evidence" in _validation_error(
        tmp_path, stale_branch_tip
    )

    externally_executed = _replace_table_cell(
        _report_text(), "## 证据索引", "DEL-900", "状态", "PASS"
    )
    assert "DEL-900 does not match its fixed evidence contract" in _validation_error(
        tmp_path, externally_executed
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
    no_status = _replace_section_metadata(_report_text(), "DR-02", "状态", "-")
    no_conclusion = _replace_section_metadata(_report_text(), "DR-02", "结论", "-")
    unknown_evidence = _replace_section_metadata(_report_text(), "DR-02", "Evidence ID", "DEL-999")

    assert "DR-02 has invalid section status" in _validation_error(tmp_path, no_status)
    assert "DR-02 requires a conclusion" in _validation_error(tmp_path, no_conclusion)
    assert "DR-02 references unknown evidence DEL-999" in _validation_error(
        tmp_path, unknown_evidence
    )


def test_section_rejects_valid_but_wrong_status_or_evidence(tmp_path: Path) -> None:
    verified = _replace_section_metadata(_report_text(), "DR-03", "状态", "VERIFIED")
    swapped = _replace_section_metadata(_report_text(), "DR-03", "Evidence ID", "DEL-001")

    assert "DR-03 status/evidence does not match" in _validation_error(tmp_path, verified)
    assert "DR-03 status/evidence does not match" in _validation_error(tmp_path, swapped)


def test_evidence_requires_fixed_command_exit_status_and_result(tmp_path: Path) -> None:
    text = _report_text()
    mutations = (
        ("命令", "Test-Path DELIVERY_REPORT.md", "does not match its fixed evidence contract"),
        ("退出码", "NOT_RUN", "does not match its fixed evidence contract"),
        ("状态", "PENDING", "does not match its fixed evidence contract"),
        ("结果", "success", "does not match its fixed evidence contract"),
    )
    for column, value, expected in mutations:
        mutation = _replace_table_cell(text, "## 证据索引", "DEL-009", column, value)
        assert expected in _validation_error(tmp_path, mutation)


def test_missing_or_duplicate_evidence_fails_closed(tmp_path: Path) -> None:
    missing = _remove_table_row(_report_text(), "## 证据索引", "DEL-010")
    duplicate = _duplicate_table_row(_report_text(), "## 证据索引", "DEL-010")

    assert "missing evidence ids: DEL-010" in _validation_error(tmp_path, missing)
    assert "duplicate evidence ids: DEL-010" in _validation_error(tmp_path, duplicate)


def test_ready_is_rejected_while_any_blocker_is_open(tmp_path: Path) -> None:
    mutation = _report_text().replace("MUSEECHO V1 PARTIALLY READY", "MUSEECHO V1 READY", 1)

    assert "READY contradicts open blockers" in _validation_error(tmp_path, mutation)


def test_partially_ready_requires_each_exact_current_course_blocker(tmp_path: Path) -> None:
    for blocker_id in (
        "BLK-FORMAL-OFFLINE-BUILD",
        "BLK-STUDENT-MANUAL",
        "BLK-CONTROLLER-BROWSER",
    ):
        mutation = _remove_table_row(_report_text(), "## 阻塞原因", blocker_id)
        assert f"required blocking reason is missing: {blocker_id}" in _validation_error(
            tmp_path, mutation
        )


def test_partially_ready_blocker_requires_pending_evidence_and_precise_closure(
    tmp_path: Path,
) -> None:
    no_evidence = _replace_table_cell(
        _report_text(), "## 阻塞原因", "BLK-FORMAL-OFFLINE-BUILD", "Evidence ID", "-"
    )
    vague = _replace_table_cell(
        _report_text(),
        "## 阻塞原因",
        "BLK-FORMAL-OFFLINE-BUILD",
        "关闭条件",
        "later",
    )

    assert "BLK-FORMAL-OFFLINE-BUILD requires evidence" in _validation_error(tmp_path, no_evidence)
    assert "BLK-FORMAL-OFFLINE-BUILD closure criteria are not precise" in _validation_error(
        tmp_path, vague
    )


def test_blocker_rejects_valid_but_wrong_owner_or_pending_evidence(tmp_path: Path) -> None:
    wrong_owner = _replace_table_cell(
        _report_text(),
        "## 阻塞原因",
        "BLK-STUDENT-MANUAL",
        "负责人",
        "部署负责人",
    )
    wrong_evidence = _replace_table_cell(
        _report_text(),
        "## 阻塞原因",
        "BLK-STUDENT-MANUAL",
        "Evidence ID",
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
            "## 证据索引",
            "PAE-900",
            "命令",
            "python -c pass",
        ),
        _replace_table_cell(
            original,
            "## 证据索引",
            "PAE-900",
            "结果",
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
            "PLAN 任务 24 要求的首次使用产品流程与产品质量复审",
            "仅自动化回归",
            1,
        ),
        original.replace(
            "任务 24 控制器启动 no-build HTTPS 开发配置",
            "已合并自动化 E2E 等同完整人工视觉 PASS；",
            1,
        ),
        _replace_table_cell(
            original,
            "## 产品审计矩阵",
            "PA-01",
            "流程步骤",
            "跳过首次进入",
        ),
        _replace_table_cell(
            original,
            "## 产品审计矩阵",
            "PA-01",
            "说明",
            "自动化 E2E 证明人工 PASS。",
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
        "结论",
        "所有远端、目标服务器和人工浏览器门禁均已通过。",
    )
    reason = _replace_table_cell(
        _report_text(),
        "## 阻塞原因",
        "BLK-CONTROLLER-BROWSER",
        "原因",
        "所有浏览器和人工检查均已通过。",
    )
    closure = _replace_table_cell(
        _report_text(),
        "## 阻塞原因",
        "BLK-CONTROLLER-BROWSER",
        "关闭条件",
        "浏览器验收已通过，因此无需进一步操作。",
    )

    assert "delivery narrative does not match" in _validation_error(tmp_path, conclusion)
    assert "delivery narrative does not match" in _validation_error(tmp_path, reason)
    assert "delivery narrative does not match" in _validation_error(tmp_path, closure)


def test_product_audit_cannot_claim_browser_pass_without_controller_execution(
    tmp_path: Path,
) -> None:
    product_path = ROOT / "docs" / "audits" / "PRODUCT_AUDIT.md"
    original = product_path.read_text(encoding="utf-8")
    mutation = _replace_table_cell(original, "## 产品审计矩阵", "PA-01", "状态", "PASS")
    mutated_path = tmp_path / "PRODUCT_AUDIT.md"
    mutated_path.write_text(mutation, encoding="utf-8")
    report = load_delivery_report(REPORT_PATH, product_audit_path=mutated_path)

    with pytest.raises(DeliveryValidationError, match="PA-01 cannot claim PASS"):
        validate_delivery_report(report, repo_root=ROOT, now=NOW)


def test_student_acceptance_and_reflection_remain_unclaimed(tmp_path: Path) -> None:
    report = load_delivery_report(REPORT_PATH)
    draft = next(item for item in report.evidence if item.evidence_id == "DEL-903")

    assert draft.result == "student-acceptance=RESERVED; reflection=DRAFT_PRESENT"
    assert draft.status == "PENDING"
    assert all(item.status == "RESERVED" for item in report.student_checks)

    checked = _replace_table_cell(_report_text(), "## 学生最终核对表", "STU-01", "状态", "COMPLETE")
    assert "STU-01 must remain RESERVED for the student" in _validation_error(tmp_path, checked)

    reflection = (ROOT / "REFLECTION.md").read_text(encoding="utf-8")
    filled_reflection = reflection + "\n学生最终验收：MUSEECHO V1 READY。\n"
    reflection_path = tmp_path / "REFLECTION.md"
    reflection_path.write_text(filled_reflection, encoding="utf-8")
    report = load_delivery_report(REPORT_PATH, reflection_path=reflection_path)

    with pytest.raises(DeliveryValidationError, match="student reflection draft does not match"):
        validate_delivery_report(report, repo_root=ROOT, now=NOW)


def test_current_status_documents_reject_stale_task23_or_task24_blocker(tmp_path: Path) -> None:
    stale = _report_text().replace("任务 24 当前状态", "任务 23 当前状态", 1)
    assert "DELIVERY_REPORT.md current status is stale" in _validation_error(tmp_path, stale)

    blocker = _report_text().replace("BLK-CONTROLLER-BROWSER", "TASK24-AUDIT", 1)
    assert "Task 24 audit cannot remain a current blocker" in _validation_error(tmp_path, blocker)


def _validate_with_course_document_mutation(tmp_path: Path, name: str, old: str, new: str) -> None:
    report = load_delivery_report(REPORT_PATH)
    repository_copy = tmp_path / f"{name}-{old}"
    required_paths = {
        "README.md",
        "PLAN.md",
        "AGENT_LOG.md",
        "BLOCKERS.md",
        "REFLECTION_NOTES.md",
        "COURSE_DELIVERY_CHECKLIST.md",
        *(evidence.path for evidence in report.evidence),
    }
    for relative_path in required_paths:
        source = ROOT / relative_path
        destination = repository_copy / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    path = repository_copy / name
    original = path.read_text(encoding="utf-8")
    assert old in original
    path.write_text(original.replace(old, new), encoding="utf-8")
    validate_delivery_report(report, repo_root=repository_copy, now=NOW)


FINAL_CI_MARKER = (
    "<!-- FINAL-CI-RELATIONSHIP: "
    "implementation-sha=d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1; "
    "run=31997390847; "
    "jobs=quality:success,e2e:success,distribution:success; "
    "github=required; gitlab=supplemental-not-run; "
    "reconciliation=docs-only-after-release; release-tag=v0.1.0; release-assets=4 -->"
)
FINAL_CI_STATEMENTS = {
    "PLAN.md": (
        "已发布的 `v0.1.0` Release 绑定到这一精确 main SHA 和四项经校验和验证的资产；"
        "后续仅文档对账需要自己的 CI，但不会改写已发布资产的身份。"
    ),
    "README.md": (
        "已发布的 `v0.1.0` Release 绑定到这一精确 main SHA 和四项经校验和验证的资产；"
        "后续仅文档对账需要自己的 CI，但不会改写已发布资产的身份。"
    ),
    "COURSE_DELIVERY_CHECKLIST.md": (
        "已发布的 v0.1.0 Release 绑定该精确 main SHA 与四项经过校验和验证的资产；"
        "后续仅文档证据对账须运行独立 CI，但不会改写已发布资产的身份。"
    ),
}


def _repository_copy(tmp_path: Path, label: str) -> Path:
    report = load_delivery_report(REPORT_PATH)
    repository_copy = tmp_path / label
    required_paths = {
        "README.md",
        "PLAN.md",
        "AGENT_LOG.md",
        "BLOCKERS.md",
        "REFLECTION_NOTES.md",
        "COURSE_DELIVERY_CHECKLIST.md",
        "release/v0.1.0-manifest.json",
        "scripts/verify_github_release.py",
        "SPEC.md",
        "docs/superpowers/specs/2026-08-17-offline-runtime-release-design.md",
        *(evidence.path for evidence in report.evidence),
    }
    for relative_path in required_paths:
        source = ROOT / relative_path
        destination = repository_copy / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return repository_copy


def _validate_course_document_text(tmp_path: Path, name: str, text: str, *, label: str) -> None:
    repository_copy = _repository_copy(tmp_path, label)
    (repository_copy / name).write_text(text, encoding="utf-8")
    report = load_delivery_report(REPORT_PATH)
    validate_delivery_report(report, repo_root=repository_copy, now=NOW)


def _repository_copy_with_relationship_contracts(tmp_path: Path, label: str) -> Path:
    repository_copy = _repository_copy(tmp_path, label)
    for name in ("PLAN.md", "README.md", "COURSE_DELIVERY_CHECKLIST.md"):
        path = repository_copy / name
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"(?m)^<!-- FINAL-CI-RELATIONSHIP: .+ -->\n?", "", text)
        text = text.replace(FINAL_CI_STATEMENTS[name] + "\n", "")
        path.write_text(
            text.rstrip() + f"\n\n{FINAL_CI_MARKER}\n{FINAL_CI_STATEMENTS[name]}\n",
            encoding="utf-8",
        )
    return repository_copy


def _relationship_validation_error(
    tmp_path: Path, name: str, old: str, new: str, field: str
) -> str:
    repository_copy = _repository_copy_with_relationship_contracts(
        tmp_path, f"relationship-{name}-{field}"
    )
    path = repository_copy / name
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    report = load_delivery_report(REPORT_PATH)
    with pytest.raises(DeliveryValidationError) as caught:
        validate_delivery_report(report, repo_root=repository_copy, now=NOW)
    return str(caught.value)


def _visible_relationship_validation_error(
    tmp_path: Path, name: str, old: str, new: str, field: str
) -> str:
    repository_copy = _repository_copy(tmp_path, f"visible-relationship-{name}-{field}")
    path = repository_copy / name
    text = path.read_text(encoding="utf-8")
    visible_before, visible_after = text.split(FINAL_CI_MARKER, maxsplit=1)
    assert old in visible_before + visible_after
    mutated = visible_before.replace(old, new) + FINAL_CI_MARKER + visible_after.replace(old, new)
    assert FINAL_CI_MARKER in mutated
    path.write_text(mutated, encoding="utf-8")
    report = load_delivery_report(REPORT_PATH)
    with pytest.raises(DeliveryValidationError) as caught:
        validate_delivery_report(report, repo_root=repository_copy, now=NOW)
    return str(caught.value)


def test_delivery_evidence_index_rejects_descending_observed_timestamps(
    tmp_path: Path,
) -> None:
    mutation = _swap_table_rows(_report_text(), "## 证据索引", "DEL-004", "DEL-005")

    assert "evidence index must be oldest-to-newest" in _validation_error(tmp_path, mutation)


def test_agent_log_summary_and_detailed_records_reject_reverse_order(tmp_path: Path) -> None:
    summary_first = "### 保留的任务 21 / 腾讯云交付脚本（仅本地）摘要"
    summary_second = "### 保留的任务 21 / 复审修复第 1 轮摘要"
    agent_log = (ROOT / "AGENT_LOG.md").read_text(encoding="utf-8")
    swapped = (
        agent_log.replace(summary_first, "SUMMARY-SWAP", 1)
        .replace(summary_second, summary_first, 1)
        .replace("SUMMARY-SWAP", summary_second, 1)
    )
    with pytest.raises(DeliveryValidationError, match="summary records must be oldest-to-newest"):
        _validate_course_document_text(
            tmp_path, "AGENT_LOG.md", swapped, label="agent-log-summary-reverse"
        )

    reverse_detail = agent_log.replace(
        "## 2026-08-08T03:21:59+08:00",
        "## 2026-08-17T03:21:59+08:00",
        1,
    )
    with pytest.raises(DeliveryValidationError, match="detailed records must be oldest-to-newest"):
        _validate_course_document_text(
            tmp_path, "AGENT_LOG.md", reverse_detail, label="agent-log-detail-reverse"
        )


def test_reflection_notes_dated_records_reject_reverse_order(tmp_path: Path) -> None:
    notes = (ROOT / "REFLECTION_NOTES.md").read_text(encoding="utf-8")
    reversed_notes = notes.replace(
        "## 2026-08-08 — 前置设计阶段",
        "## 2026-08-18 — 前置设计阶段",
        1,
    )

    with pytest.raises(
        DeliveryValidationError,
        match="REFLECTION_NOTES.md dated records must be oldest-to-newest",
    ):
        _validate_course_document_text(
            tmp_path,
            "REFLECTION_NOTES.md",
            reversed_notes,
            label="reflection-notes-reverse",
        )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        (
            lambda text: text.replace("## 2026-08-11 — 任务 22 / 证据驱动验收材料\n", "", 1),
            "REFLECTION_NOTES.md dated heading inventory is invalid",
        ),
        (
            lambda text: text.replace(
                "## 2026-08-11 — 任务 22 / 证据驱动验收材料",
                "## 2026-08-11 — 任务 21 / 交付边界的本地证据",
                1,
            ),
            "REFLECTION_NOTES.md dated heading inventory is invalid",
        ),
        (
            lambda text: text.replace(
                "## 2026-08-11 — 任务 22 / 证据驱动验收材料",
                "## 2026-08-11 — 任务 22 / 被重命名材料",
                1,
            ),
            "REFLECTION_NOTES.md dated heading inventory is invalid",
        ),
    ),
)
def test_reflection_notes_reject_missing_duplicate_or_relabeled_dated_heading(
    tmp_path: Path, mutation, expected: str
) -> None:
    notes = (ROOT / "REFLECTION_NOTES.md").read_text(encoding="utf-8")

    with pytest.raises(DeliveryValidationError, match=expected):
        _validate_course_document_text(
            tmp_path,
            "REFLECTION_NOTES.md",
            mutation(notes),
            label="reflection-notes-inventory",
        )


@pytest.mark.parametrize(
    ("field", "old", "new"),
    (
        (
            "release-url",
            "https://github.com/Zzz148080/MuseEcho/releases/tag/v0.1.0",
            "https://example.invalid/release",
        ),
        ("tag", "标签 `v0.1.0`", "标签 `v0.1.1`"),
        (
            "target",
            "d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1",
            "c99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1",
        ),
        ("published-at", "2026-08-17T05:54:50Z", "2026-08-17T05:54:51Z"),
        ("asset-name", "`museecho-app.tar`", "`wrong-app.tar`"),
        ("asset-size", "366,037,504 字节", "366,037,505 字节"),
        (
            "asset-sha256",
            "f8aaf8369f76bd70304e2770e21e1bfc5f5a45979b63d9eb512e39d58d2fff95",
            "08aaf8369f76bd70304e2770e21e1bfc5f5a45979b63d9eb512e39d58d2fff95",
        ),
    ),
)
def test_release_reproduction_rejects_each_bound_release_fact_mutation(
    tmp_path: Path, field: str, old: str, new: str
) -> None:
    reproduction = (ROOT / "RELEASE_REPRODUCTION.md").read_text(encoding="utf-8")
    assert old in reproduction

    with pytest.raises(
        DeliveryValidationError,
        match=f"RELEASE_REPRODUCTION.md release contract has invalid {field}",
    ):
        _validate_course_document_text(
            tmp_path,
            "RELEASE_REPRODUCTION.md",
            reproduction.replace(old, new),
            label=f"release-reproduction-{field}",
        )


def test_release_manifest_mutation_cannot_redefine_the_document_contract(tmp_path: Path) -> None:
    repository_copy = _repository_copy(tmp_path, "release-manifest-target")
    manifest_path = repository_copy / "release" / "v0.1.0-manifest.json"
    manifest = manifest_path.read_text(encoding="utf-8").replace(
        "d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1",
        "c99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1",
    )
    manifest_path.write_text(manifest, encoding="utf-8")
    report = load_delivery_report(REPORT_PATH)

    with pytest.raises(
        DeliveryValidationError,
        match="release/v0.1.0-manifest.json release contract has invalid target",
    ):
        validate_delivery_report(report, repo_root=repository_copy, now=NOW)


@pytest.mark.parametrize(
    ("name", "stale_claim"),
    (
        ("PLAN.md", "最终 main CI 的 tar 已下载"),
        ("SPEC.md", "只允许发布同一 distribution 作业产生并审计的"),
        ("README.md", "两个经过同一 distribution 作业审计的镜像 tar"),
        (
            "docs/superpowers/specs/2026-08-17-offline-runtime-release-design.md",
            "`release-images.json`, copied from the distribution job",
        ),
    ),
)
def test_course_documents_reject_stale_retained_ci_artifact_provenance(
    tmp_path: Path, name: str, stale_claim: str
) -> None:
    repository_copy = _repository_copy(tmp_path, f"stale-provenance-{Path(name).name}")
    path = repository_copy / name
    current = path.read_text(encoding="utf-8")
    path.write_text(current + f"\n{stale_claim}\n", encoding="utf-8")
    report = load_delivery_report(REPORT_PATH)

    with pytest.raises(
        DeliveryValidationError,
        match=f"{re.escape(name)} contains stale retained-CI artifact provenance",
    ):
        validate_delivery_report(report, repo_root=repository_copy, now=NOW)


@pytest.mark.parametrize("name", ("PLAN.md", "README.md", "COURSE_DELIVERY_CHECKLIST.md"))
@pytest.mark.parametrize(
    ("field", "old", "new"),
    (
        (
            "implementation-sha",
            "implementation-sha=d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1",
            "implementation-sha=966d403196e838d4b0589b410d684376e092e55c",
        ),
        ("run", "run=31997390847", "run=31997390848"),
        ("quality", "quality:success", "quality:failed"),
        ("e2e", "e2e:success", "e2e:missing"),
        ("distribution", "distribution:success", "distribution:failed"),
        ("github", "github=required", "github=supplemental"),
        ("gitlab", "gitlab=supplemental-not-run", "gitlab=required"),
        (
            "reconciliation",
            "reconciliation=docs-only-after-release",
            "reconciliation=inherits-product-run",
        ),
        ("release-tag", "release-tag=v0.1.0", "release-tag=v0.1.1"),
        ("release-assets", "release-assets=4", "release-assets=3"),
        (
            "statement",
            None,
            "后续仅文档对账继承产品实现运行。",
        ),
    ),
)
def test_course_documents_reject_each_broken_final_ci_relationship(
    tmp_path: Path, name: str, field: str, old: str | None, new: str
) -> None:
    effective_old = FINAL_CI_STATEMENTS[name] if field == "statement" else old
    assert effective_old is not None
    error = _relationship_validation_error(tmp_path, name, effective_old, new, field)

    assert f"{name} final-CI relationship has invalid {field}" in error


@pytest.mark.parametrize(
    ("name", "field", "old", "new"),
    (
        ("PLAN.md", "run", "`31997390847`", "`31997390848`"),
        (
            "PLAN.md",
            "implementation-sha",
            "`d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1`",
            "`966d403196e838d4b0589b410d684376e092e55c`",
        ),
        ("PLAN.md", "jobs", "GitHub 质量门、E2E 和分发", "GitHub 质量门失败、E2E 和分发"),
        ("README.md", "run", "`31997390847`", "`31997390848`"),
        (
            "README.md",
            "implementation-sha",
            "`d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1`",
            "`966d403196e838d4b0589b410d684376e092e55c`",
        ),
        ("README.md", "jobs", "GitHub 质量门、E2E 和分发", "GitHub 质量门失败、E2E 和分发"),
        ("COURSE_DELIVERY_CHECKLIST.md", "run", "`31997390847`", "`31997390848`"),
        (
            "COURSE_DELIVERY_CHECKLIST.md",
            "implementation-sha",
            "`d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1`",
            "`966d403196e838d4b0589b410d684376e092e55c`",
        ),
        (
            "COURSE_DELIVERY_CHECKLIST.md",
            "jobs",
            "quality/E2E/distribution 全绿",
            "quality/E2E/distribution 未全绿",
        ),
    ),
)
def test_course_documents_reject_visible_final_ci_drift_with_marker_unchanged(
    tmp_path: Path, name: str, field: str, old: str, new: str
) -> None:
    error = _visible_relationship_validation_error(tmp_path, name, old, new, field)

    assert f"{name} visible final-CI relationship has invalid {field}" in error


def test_course_status_documents_reject_stale_draft_and_final_ci_claims(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        DeliveryValidationError,
        match="PLAN.md current status must describe the student-authored reflection draft",
    ):
        _validate_with_course_document_mutation(
            tmp_path, "PLAN.md", "学生撰写的反思草稿", "空白学生草稿"
        )

    for name in ("PLAN.md", "README.md", "COURSE_DELIVERY_CHECKLIST.md"):
        with pytest.raises(
            DeliveryValidationError,
            match=f"{name} final-CI relationship has invalid implementation-sha",
        ):
            _validate_with_course_document_mutation(
                tmp_path,
                name,
                "d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1",
                "unverified-final-sha",
            )


def test_checker_cli_accepts_the_committed_delivery_report(tmp_path: Path) -> None:
    expected = (
        "delivery-sections=17; evidence=19; blockers=3; readiness=MUSEECHO V1 PARTIALLY READY"
    )
    report = load_delivery_report(REPORT_PATH)
    evidence = next(item for item in report.evidence if item.evidence_id == "DEL-007")

    assert EVIDENCE_CONTRACTS["DEL-007"].result == expected
    assert evidence.result == expected
    mutation = _report_text().replace(expected, expected.replace("blockers=3", "blockers=5"), 1)
    assert "DEL-007 does not match its fixed evidence contract" in _validation_error(
        tmp_path, mutation
    )

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
