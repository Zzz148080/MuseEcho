#!/usr/bin/env python3
"""Fail-closed validator for the MuseEcho Task 24 delivery report."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

EXPECTED_SECTION_TITLES = (
    ("DR-01", "交付结论与状态摘要"),
    ("DR-02", "项目介绍"),
    ("DR-03", "核心功能"),
    ("DR-04", "架构"),
    ("DR-05", "技术栈"),
    ("DR-06", "目录"),
    ("DR-07", "环境"),
    ("DR-08", "安装"),
    ("DR-09", "本地运行"),
    ("DR-10", "测试"),
    ("DR-11", "Docker"),
    ("DR-12", "凭据"),
    ("DR-13", "安全"),
    ("DR-14", "分发"),
    ("DR-15", "部署"),
    ("DR-16", "限制"),
    ("DR-17", "许可证"),
)
EXPECTED_SECTION_IDS = tuple(item[0] for item in EXPECTED_SECTION_TITLES)
EXPECTED_PRODUCT_AUDIT_IDS = tuple(f"PA-{index:02d}" for index in range(1, 14))
EXPECTED_STUDENT_CHECK_IDS = tuple(f"STU-{index:02d}" for index in range(1, 7))
EXPECTED_EVIDENCE_IDS = tuple(f"DEL-{index:03d}" for index in range(1, 15)) + tuple(
    f"DEL-{index:03d}" for index in range(900, 905)
)
REQUIRED_BLOCKER_IDS = (
    "BLK-FORMAL-OFFLINE-BUILD",
    "BLK-STUDENT-MANUAL",
    "BLK-CONTROLLER-BROWSER",
)
SECTION_CONTRACTS = {
    "DR-01": (
        "PARTIAL",
        (
            "DEL-002",
            "DEL-003",
            "DEL-004",
            "DEL-006",
            "DEL-007",
            "DEL-008",
            "DEL-009",
            "DEL-010",
            "DEL-011",
            "DEL-012",
            "DEL-013",
            "DEL-014",
            "DEL-900",
            "DEL-901",
            "DEL-902",
            "DEL-903",
            "DEL-904",
        ),
    ),
    "DR-02": ("VERIFIED", ("DEL-001",)),
    "DR-03": ("PARTIAL", ("DEL-002", "DEL-004", "DEL-904")),
    "DR-04": ("VERIFIED", ("DEL-001",)),
    "DR-05": ("VERIFIED", ("DEL-001",)),
    "DR-06": ("VERIFIED", ("DEL-001",)),
    "DR-07": ("VERIFIED", ("DEL-001",)),
    "DR-08": ("VERIFIED", ("DEL-001",)),
    "DR-09": ("PARTIAL", ("DEL-001", "DEL-901", "DEL-904")),
    "DR-10": (
        "PARTIAL",
        (
            "DEL-002",
            "DEL-003",
            "DEL-004",
            "DEL-005",
            "DEL-006",
            "DEL-007",
            "DEL-008",
            "DEL-009",
            "DEL-010",
            "DEL-011",
            "DEL-012",
            "DEL-013",
            "DEL-014",
            "DEL-900",
            "DEL-901",
            "DEL-904",
        ),
    ),
    "DR-11": (
        "PARTIAL",
        ("DEL-001", "DEL-003", "DEL-004", "DEL-013", "DEL-014", "DEL-901", "DEL-902"),
    ),
    "DR-12": ("VERIFIED", ("DEL-001",)),
    "DR-13": (
        "VERIFIED",
        ("DEL-001", "DEL-002", "DEL-003", "DEL-004", "DEL-012", "DEL-013", "DEL-014"),
    ),
    "DR-14": (
        "PARTIAL",
        (
            "DEL-001",
            "DEL-002",
            "DEL-003",
            "DEL-004",
            "DEL-011",
            "DEL-012",
            "DEL-013",
            "DEL-014",
            "DEL-900",
            "DEL-902",
        ),
    ),
    "DR-15": ("PARTIAL", ("DEL-001", "DEL-002", "DEL-901")),
    "DR-16": ("PARTIAL", ("DEL-001", "DEL-002", "DEL-003", "DEL-902")),
    "DR-17": ("VERIFIED", ("DEL-001",)),
}
BLOCKER_CONTRACTS = {
    "BLK-FORMAL-OFFLINE-BUILD": ("构建环境负责人", ("DEL-902",)),
    "BLK-STUDENT-MANUAL": ("学生", ("DEL-903",)),
    "BLK-CONTROLLER-BROWSER": ("学生/产品复审者", ("DEL-904",)),
}
PRODUCT_DOMAINS = (
    "新手引导",
    "上传",
    "等待",
    "Music DNA",
    "结构地图",
    "和弦",
    "证据问答",
    "错误",
    "再次上传",
    "响应式",
    "可读性",
    "证据可追溯性",
    "隐私",
)
VALID_SECTION_STATUSES = frozenset({"VERIFIED", "PARTIAL", "PENDING"})
EXECUTED_KINDS = frozenset(
    {
        "RED_COMMAND",
        "CURRENT_COMMAND",
        "IMPLEMENTATION_BOUNDARY_COMMAND",
        "CONTROLLER_COMMAND",
    }
)
VALID_EVIDENCE_KINDS = EXECUTED_KINDS | {"EXTERNAL_NOT_RUN", "CONTROLLER_NOT_RUN"}
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
CURRENT_STATUS_START = "<!-- TASK24-CURRENT-STATUS:START -->"
CURRENT_STATUS_END = "<!-- TASK24-CURRENT-STATUS:END -->"
EXPECTED_PRODUCT_SCOPE = "PLAN 任务 24 要求的首次使用产品流程与产品质量复审"
EXPECTED_PRODUCT_METHOD = (
    "任务 24 控制器启动 no-build HTTPS 开发配置并观察到 API ready，但应用内浏览器在渲染前"
    "因 ERR_CERT_AUTHORITY_INVALID 拒绝内部 Caddy CA。浏览器安全策略禁止绕过该中间页，"
    "因此所有人工或视觉结论保持 CERT_TRUST_BLOCKED。已合并的任务 23 GitHub E2E 仅证明"
    "自动化实现边界。"
)
EXPECTED_DELIVERY_NARRATIVE_SHA256 = (
    "31a23e53719c5016779d3358bd2686be1723aecee7669c30fffc343dbee73960"
)
EXPECTED_PRODUCT_NARRATIVE_SHA256 = (
    "62e707d68c822b8f50643d2d2b4f50c093ddf77efb9335f68839e752c27aae08"
)
FINAL_IMPLEMENTATION_SHA_BOUNDARY = "d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1"
FINAL_CI_RUN = "31997390847"
RELEASE_CONTRACT: dict[str, Any] = {
    "repository": "Zzz148080/MuseEcho",
    "tag": "v0.1.0",
    "target": "d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1",
    "main-ci-run": 31997390847,
    "published-at": "2026-08-17T05:54:50Z",
    "release-url": "https://github.com/Zzz148080/MuseEcho/releases/tag/v0.1.0",
    "assets": (
        (
            "museecho-app.tar",
            366037504,
            "f8aaf8369f76bd70304e2770e21e1bfc5f5a45979b63d9eb512e39d58d2fff95",
        ),
        (
            "museecho-gateway.tar",
            59211776,
            "765a0b089f174ce57e92ffdac8aada6fa24475f0a445a361850e27764f3320a3",
        ),
        (
            "museecho-offline-runtime-v0.1.0.zip",
            9293,
            "e85248bbee5dd2e4b406f830db02e6547649cc948dbae01b04685882d827f80c",
        ),
        (
            "SHA256SUMS.txt",
            275,
            "058ae2c2f641fea7b311bf996c4d51d04fbd6d4b84955ae3dc501b98bf3b8d46",
        ),
    ),
}
REFLECTION_NOTES_DATED_HEADINGS = (
    "## 2026-08-08 — 前置设计阶段",
    "## 2026-08-11 — 任务 21 / 交付边界的本地证据",
    "## 2026-08-11 — 任务 22 / 证据驱动验收材料",
    "## 2026-08-11 — 任务 23 / 工程审计过程材料",
    "## 2026-08-13 — 任务 24 / 客观交付材料",
    "## 2026-08-17 — v0.1.0 离线运行发行客观材料",
)
FINAL_CI_MARKER_PREFIX = "<!-- FINAL-CI-RELATIONSHIP: "
FINAL_CI_MARKER_SUFFIX = " -->"
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
EXPECTED_FINAL_CI_RELATIONSHIP = {
    "implementation-sha": FINAL_IMPLEMENTATION_SHA_BOUNDARY,
    "run": FINAL_CI_RUN,
    "quality": "success",
    "e2e": "success",
    "distribution": "success",
    "github": "required",
    "gitlab": "supplemental-not-run",
    "reconciliation": "docs-only-after-release",
    "release-tag": "v0.1.0",
    "release-assets": "4",
}
VISIBLE_FINAL_CI_CONTRACTS = {
    "PLAN.md": {
        "run": ("main run `31997390847`",),
        "implementation-sha": ("合并 SHA `d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1`",),
        "jobs": ("main run `31997390847` 的 GitHub 质量门、E2E 和分发均通过",),
        "github": ("GitHub Release `v0.1.0` 已发布",),
        "gitlab": (
            "GitLab 与腾讯云/公网部署属于后续工作。",
            "本文不声称 GitLab、云端部署或学生验收已经完成。",
        ),
        "reconciliation": (FINAL_CI_STATEMENTS["PLAN.md"],),
    },
    "README.md": {
        "run": ("main run `31997390847`",),
        "implementation-sha": ("合并 SHA `d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1`",),
        "jobs": ("main run `31997390847` 的 GitHub 质量门、E2E 和分发均通过",),
        "github": ("GitHub Release `v0.1.0` 已发布",),
        "gitlab": (
            "GitLab 与腾讯云/公网部署属于后续工作，不是课程提交门禁。",
            "本文不声称 GitLab、",
            "云端部署或学生验收已经完成。",
        ),
        "reconciliation": (
            FINAL_CI_STATEMENTS["README.md"],
            "后续文档对账不改变产品架构或把未发生的",
        ),
    },
    "COURSE_DELIVERY_CHECKLIST.md": {
        "run": (
            "main run `31997390847` 在合并 SHA `d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1` 上通过。",
        ),
        "implementation-sha": (
            "main run `31997390847` 在合并 SHA `d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1` 上通过。",
        ),
        "jobs": ("`DEL-013` 记录 main run `31997390847` 的 quality/E2E/distribution 全绿。",),
        "github": ("GitHub `v0.1.0` 正式离线运行 Release 已发布",),
        "gitlab": ("GitLab 配置仅作为补充性后续材料保留。",),
        "reconciliation": (
            FINAL_CI_STATEMENTS["COURSE_DELIVERY_CHECKLIST.md"],
            "不得把文档提交冒充第二次产品实现验证。",
        ),
    },
}
AGENT_LOG_SUMMARY_HEADINGS = (
    "### 保留的任务 21 / 腾讯云交付脚本（仅本地）摘要",
    "### 保留的任务 21 / 复审修复第 1 轮摘要",
    "### 保留的任务 22 / 功能审计与验收缺口闭环摘要",
    "### 保留的任务 23 / 最终复审修复第 19/20 轮摘要",
    "### 保留的任务 24 / 产品审计与交付报告摘要",
    "### 当前任务 24 后维护摘要",
)
AGENT_LOG_SUMMARY_START = "## 保留的任务 21–24 摘要时间线"
AGENT_LOG_DETAIL_START = "## 按日期记录的详细实施日志"
EXPECTED_DEL_011_SUMMARY = (
    "仅作为历史任务 24 实现证据；它不能验证最终 PR SHA，后者由 DEL-012 单独记录。"
)


@dataclass(frozen=True)
class EvidenceContract:
    kind: str
    command: str
    path: str
    coverage: str
    result: str
    exit_code: str
    status: str


EVIDENCE_CONTRACTS = {
    "DEL-001": EvidenceContract(
        "CURRENT_COMMAND",
        "..\\audit-23-engineering\\.venv\\Scripts\\python.exe -m pytest "
        "tests/unit/test_task20_final_delivery_contract.py::"
        "test_readme_cold_start_contract_covers_locked_setup_https_health_and_cleanup "
        "-q --basetemp tmp/task24-readme -p no:cacheprovider",
        "tests/unit/test_task20_final_delivery_contract.py",
        "DR-02, DR-04, DR-05, DR-06, DR-07, DR-08, DR-09, DR-11, DR-12, DR-13, "
        "DR-14, DR-15, DR-16, DR-17",
        "pytest-tests=1; readme-cold-start-contract=pass",
        "0",
        "PASS",
    ),
    "DEL-002": EvidenceContract(
        "CURRENT_COMMAND",
        "..\\audit-23-engineering\\.venv\\Scripts\\python.exe "
        "scripts/check_acceptance_matrix.py SPEC.md docs/audits/FUNCTIONAL_AUDIT.md",
        "docs/audits/FUNCTIONAL_AUDIT.md",
        "DR-01, DR-03, DR-10, DR-13, DR-14, DR-15, DR-16",
        "acceptance-items=40; pass=36; partial=4; fail=0; readiness=PARTIALLY_READY",
        "0",
        "PASS",
    ),
    "DEL-003": EvidenceContract(
        "CURRENT_COMMAND",
        "..\\audit-23-engineering\\.venv\\Scripts\\python.exe "
        "scripts/check_engineering_audit.py docs/audits/ENGINEERING_AUDIT.md --schema-only",
        "docs/audits/ENGINEERING_AUDIT.md",
        "DR-01, DR-10, DR-11, DR-13, DR-14, DR-16",
        "findings=10; fixed-high=4; fixed-medium=2; verified-medium=1; "
        "blocked-medium=3; open=0; schema-only=true",
        "0",
        "PASS",
    ),
    "DEL-004": EvidenceContract(
        "IMPLEMENTATION_BOUNDARY_COMMAND",
        "gh pr view 1 --repo Zzz148080/MuseEcho --json "
        "state,headRefOid,mergeCommit,statusCheckRollup,url",
        ".github/workflows/ci.yml",
        "DR-03, DR-10, DR-11, DR-13, DR-14",
        "pr=1; state=MERGED; head=73869619bedf1298114d9755811f3f6e9f505de3; "
        "merge=79d87f4170f004f22d9e2c21151f59b757e272a3; quality=success; "
        "e2e=success; distribution=success",
        "0",
        "PASS",
    ),
    "DEL-005": EvidenceContract(
        "RED_COMMAND",
        "..\\audit-23-engineering\\.venv\\Scripts\\python.exe -m pytest "
        "tests/unit/test_delivery_report.py -q --basetemp tmp/task24-red -p no:cacheprovider",
        "tests/unit/test_delivery_report.py",
        "DR-10",
        "red=ModuleNotFoundError:scripts.check_delivery_report",
        "1",
        "EXPECTED_FAIL",
    ),
    "DEL-006": EvidenceContract(
        "CURRENT_COMMAND",
        "..\\audit-23-engineering\\.venv\\Scripts\\python.exe -m pytest "
        "tests/unit/test_delivery_report.py -q --basetemp tmp/task24-green -p no:cacheprovider",
        "tests/unit/test_delivery_report.py",
        "DR-01, DR-10",
        "pytest-tests=24; delivery-report-mutations=pass",
        "0",
        "PASS",
    ),
    "DEL-007": EvidenceContract(
        "CURRENT_COMMAND",
        "..\\audit-23-engineering\\.venv\\Scripts\\python.exe "
        "scripts/check_delivery_report.py DELIVERY_REPORT.md",
        "DELIVERY_REPORT.md",
        "DR-01, DR-10",
        "delivery-sections=17; evidence=19; blockers=3; readiness=MUSEECHO V1 PARTIALLY READY",
        "0",
        "PASS",
    ),
    "DEL-008": EvidenceContract(
        "CURRENT_COMMAND",
        "..\\audit-23-engineering\\.venv\\Scripts\\python.exe -m ruff check "
        "scripts/check_delivery_report.py tests/unit/test_delivery_report.py",
        "scripts/check_delivery_report.py",
        "DR-10",
        "ruff-files=2; lint=pass",
        "0",
        "PASS",
    ),
    "DEL-009": EvidenceContract(
        "CURRENT_COMMAND",
        "..\\audit-23-engineering\\.venv\\Scripts\\python.exe -m mypy "
        "scripts/check_delivery_report.py",
        "scripts/check_delivery_report.py",
        "DR-10",
        "mypy-files=1; strict=pass",
        "0",
        "PASS",
    ),
    "DEL-010": EvidenceContract(
        "CURRENT_COMMAND",
        "git diff --check",
        "DELIVERY_REPORT.md",
        "DR-01, DR-10",
        "diff-check=pass",
        "0",
        "PASS",
    ),
    "DEL-011": EvidenceContract(
        "IMPLEMENTATION_BOUNDARY_COMMAND",
        "gh run view 31687703913 --repo Zzz148080/MuseEcho --json "
        "status,conclusion,headSha,jobs,url",
        ".github/workflows/ci.yml",
        "DR-01, DR-10, DR-14",
        "run=31687703913; head=de5bc6f949e6e98cff32f16116708ec7b7409c9d; "
        "quality=success; e2e=success; distribution=success",
        "0",
        "PASS",
    ),
    "DEL-012": EvidenceContract(
        "IMPLEMENTATION_BOUNDARY_COMMAND",
        "gh run view 31966788273 --repo Zzz148080/MuseEcho --json "
        "status,conclusion,headBranch,headSha,jobs,url",
        ".github/workflows/ci.yml",
        "DR-01, DR-10, DR-13, DR-14",
        "run=31966788273; head=0674f74f4097e46cee98c4715a62ad5aa55101cf; "
        "branch=codex/expand-common-audio-formats; quality=success (5m43s); "
        "e2e=success (3m10s); distribution=success (7m30s)",
        "0",
        "PASS",
    ),
    "DEL-013": EvidenceContract(
        "IMPLEMENTATION_BOUNDARY_COMMAND",
        "gh run view 31997390847 --repo Zzz148080/MuseEcho --json "
        "status,conclusion,headBranch,headSha,jobs,url; gh api "
        "repos/Zzz148080/MuseEcho/actions/runs/31997390847/artifacts",
        ".github/workflows/ci.yml",
        "DR-01, DR-10, DR-11, DR-13, DR-14",
        "run=31997390847; head=d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1; "
        "branch=main; quality=success; e2e=success; distribution=success; "
        "artifacts=quota-skipped",
        "0",
        "PASS",
    ),
    "DEL-014": EvidenceContract(
        "CURRENT_COMMAND",
        "$releaseDir = Join-Path (Get-Location) 'tmp\\release-v0.1.0-verification'; "
        ".\\.venv\\Scripts\\python.exe scripts/verify_github_release.py --action Smoke "
        "--manifest release/v0.1.0-manifest.json --assets-directory $releaseDir --download",
        "RELEASE_REPRODUCTION.md",
        "DR-01, DR-10, DR-11, DR-13, DR-14",
        "tag=v0.1.0; target=d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1; "
        "draft=false; prerelease=false; assets=4; tag-resolved-to-target=pass; "
        "asset-metadata=pass; checksum-file-self-digest=pass; checksum-payloads=pass; "
        "offline-smoke=pass",
        "0",
        "PASS",
    ),
    "DEL-900": EvidenceContract(
        "EXTERNAL_NOT_RUN",
        "NOT RUN: GitLab has no Task 24 pipeline",
        ".gitlab-ci.yml",
        "DR-01, DR-10, DR-14",
        "gitlab=NOT_RUN",
        "NOT_RUN",
        "DEFERRED",
    ),
    "DEL-901": EvidenceContract(
        "EXTERNAL_NOT_RUN",
        "NOT RUN: Tencent Cloud, public trusted TLS, target-server benchmark, cross-network "
        "smoke, 24-hour observation, backup restore, and live rollback require authorization",
        "DEPLOYMENT_EVIDENCE.md",
        "DR-01, DR-09, DR-11, DR-15",
        "cloud=NOT_RUN; public-smoke=NOT_RUN; target-server=NOT_RUN; rollback=NOT_RUN",
        "NOT_RUN",
        "DEFERRED",
    ),
    "DEL-902": EvidenceContract(
        "EXTERNAL_NOT_RUN",
        "NOT RUN: formal current-source Dockerfile offline build requires the complete locked "
        "pip and apt BuildKit cache under network none",
        "Dockerfile",
        "DR-01, DR-11, DR-14, DR-16",
        "ENG-010=BLOCKED; formal-offline-build=NOT_RUN; derivative=NON_RELEASE",
        "NOT_RUN",
        "PENDING",
    ),
    "DEL-903": EvidenceContract(
        "EXTERNAL_NOT_RUN",
        "NOT RUN: student must personally complete the final acceptance checklist and sign "
        "the existing REFLECTION.md draft",
        "REFLECTION.md",
        "DR-01, DR-02, DR-03, DR-09, DR-10",
        "student-acceptance=RESERVED; reflection=DRAFT_PRESENT",
        "NOT_RUN",
        "PENDING",
    ),
    "DEL-904": EvidenceContract(
        "CONTROLLER_COMMAND",
        "Browser plugin: start Compose development profile --no-build; GET /api/health; "
        "navigate https://localhost:4173/; finalize; docker compose down --volumes",
        "docs/audits/PRODUCT_AUDIT.md",
        "DR-01, DR-03, DR-09, DR-10",
        "product-items=13; service-health=ready; navigation=ERR_CERT_AUTHORITY_INVALID; "
        "manual-pass=0; controller-status=CERT_TRUST_BLOCKED; cleanup=pass",
        "1",
        "PENDING",
    ),
}

PRODUCT_EVIDENCE_CONTRACTS = {
    "PAE-001": EvidenceContract(
        "IMPLEMENTATION_BOUNDARY_COMMAND",
        "gh pr view 1 --repo Zzz148080/MuseEcho --json "
        "state,headRefOid,mergeCommit,statusCheckRollup,url",
        ".github/workflows/ci.yml",
        ", ".join(EXPECTED_PRODUCT_AUDIT_IDS),
        "pr=1; state=MERGED; head=73869619bedf1298114d9755811f3f6e9f505de3; "
        "merge=79d87f4170f004f22d9e2c21151f59b757e272a3; quality=success; "
        "e2e=success; distribution=success",
        "0",
        "PASS",
    ),
    "PAE-900": EvidenceContract(
        "CONTROLLER_COMMAND",
        "Browser plugin: start Compose development profile --no-build; GET /api/health; "
        "navigate https://localhost:4173/; finalize; docker compose down --volumes",
        "docs/audits/PRODUCT_AUDIT.md",
        ", ".join(EXPECTED_PRODUCT_AUDIT_IDS),
        "service-health=ready; navigation=ERR_CERT_AUTHORITY_INVALID; manual-pass=0; "
        "controller-status=CERT_TRUST_BLOCKED; cleanup=pass",
        "1",
        "BLOCKED",
    ),
}

EXPECTED_REFLECTION_DRAFT_SHA256 = (
    "72a1f93f05435d003d8624cee147a3ec35250de43831eaee513a6d68a16a25c5"
)


class DeliveryValidationError(ValueError):
    """Raised when delivery evidence fails closed."""


@dataclass(frozen=True)
class DeliveryEvidence:
    evidence_id: str
    kind: str
    command: str
    path: str
    coverage: str
    result: str
    observed_at_raw: str
    exit_code_raw: str
    status: str
    summary: str


@dataclass(frozen=True)
class DeliverySection:
    section_id: str
    title: str
    status: str
    conclusion: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class BlockingReason:
    blocker_id: str
    owner: str
    status: str
    evidence_ids: tuple[str, ...]
    reason: str
    closure_criteria: str


@dataclass(frozen=True)
class StudentCheck:
    check_id: str
    item: str
    status: str
    evidence_ids: tuple[str, ...]
    student_record: str


@dataclass(frozen=True)
class ProductAuditItem:
    item_id: str
    domain: str
    flow_step: str
    status: str
    evidence_ids: tuple[str, ...]
    notes: str


@dataclass(frozen=True)
class DeliveryReport:
    path: Path
    generated_at_raw: str
    status: str
    sections: tuple[DeliverySection, ...]
    evidence: tuple[DeliveryEvidence, ...]
    blockers: tuple[BlockingReason, ...]
    student_checks: tuple[StudentCheck, ...]
    product_audit_items: tuple[ProductAuditItem, ...]
    product_audit_evidence: tuple[DeliveryEvidence, ...]
    product_audit_generated_at_raw: str
    product_audit_status: str
    product_audit_scope: str
    product_audit_method: str
    reflection_text: str
    raw_text: str
    parse_issues: tuple[str, ...]

    @property
    def blocking_reasons(self) -> tuple[BlockingReason, ...]:
        return tuple(item for item in self.blockers if item.status == "OPEN")

    @property
    def all_definition_of_done_items_have_current_pass_evidence(self) -> bool:
        return not self.blocking_reasons and self.status == "MUSEECHO V1 READY"


def _clean_cell(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
        return value[1:-1].strip()
    return value


def _refs(value: str) -> tuple[str, ...]:
    value = _clean_cell(value)
    if value in {"", "-"}:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _metadata(text: str, label: str, issues: list[str]) -> str:
    matches = re.findall(
        rf"^- \*\*{re.escape(label)}：\*\*\s+`([^`]+)`\s*$", text, flags=re.MULTILINE
    )
    if len(matches) != 1:
        issues.append(f"metadata {label!r} must appear exactly once")
        return ""
    return str(matches[0]).strip()


def _table(
    text: str, heading: str, expected_headers: Sequence[str], issues: list[str]
) -> list[dict[str, str]]:
    lines = text.splitlines()
    indexes = [index for index, line in enumerate(lines) if line.strip() == heading]
    if len(indexes) != 1:
        issues.append(f"heading {heading!r} must appear exactly once")
        return []
    index = indexes[0] + 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    table_lines: list[str] = []
    while index < len(lines) and lines[index].startswith("|"):
        table_lines.append(lines[index])
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
        re.fullmatch(r":?-{3,}:?", cell) is None for cell in separator
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


def _sections(text: str, issues: list[str]) -> tuple[DeliverySection, ...]:
    matches = list(re.finditer(r"(?m)^## (DR-\d{2}) — (.+)$", text))
    sections: list[DeliverySection] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end]
        status_match = re.findall(r"(?m)^- \*\*状态：\*\*\s+`?([^`\n]+)`?\s*$", body)
        conclusion_match = re.findall(r"(?m)^- \*\*结论：\*\*\s+(.+)$", body)
        evidence_match = re.findall(r"(?m)^- \*\*Evidence ID：\*\*\s+(.+)$", body)
        if len(status_match) != 1:
            issues.append(f"{match.group(1)} must have exactly one Status")
        if len(conclusion_match) != 1:
            issues.append(f"{match.group(1)} must have exactly one Conclusion")
        if len(evidence_match) != 1:
            issues.append(f"{match.group(1)} must have exactly one Evidence IDs line")
        sections.append(
            DeliverySection(
                match.group(1),
                match.group(2).strip(),
                _clean_cell(status_match[0]) if len(status_match) == 1 else "",
                conclusion_match[0].strip() if len(conclusion_match) == 1 else "",
                _refs(evidence_match[0]) if len(evidence_match) == 1 else (),
            )
        )
    return tuple(sections)


def _evidence_from_rows(
    rows: Iterable[dict[str, str]], *, id_column: str
) -> tuple[DeliveryEvidence, ...]:
    return tuple(
        DeliveryEvidence(
            row[id_column],
            row["类型"],
            row["命令"],
            row["路径"],
            row["覆盖范围"],
            row["结果"],
            row["观察时间（UTC）"],
            row["退出码"],
            row["状态"],
            row["摘要"],
        )
        for row in rows
    )


def load_delivery_report(
    report_path: Path | str,
    *,
    product_audit_path: Path | str | None = None,
    reflection_path: Path | str | None = None,
) -> DeliveryReport:
    path = Path(report_path)
    text = path.read_text(encoding="utf-8")
    issues: list[str] = []
    generated_at = _metadata(text, "生成时间（UTC）", issues)
    status = _metadata(text, "就绪度", issues)
    sections = _sections(text, issues)
    evidence_rows = _table(
        text,
        "## 证据索引",
        (
            "Evidence ID",
            "类型",
            "命令",
            "路径",
            "覆盖范围",
            "结果",
            "观察时间（UTC）",
            "退出码",
            "状态",
            "摘要",
        ),
        issues,
    )
    blocker_rows = _table(
        text,
        "## 阻塞原因",
        ("阻塞项 ID", "负责人", "状态", "Evidence ID", "原因", "关闭条件"),
        issues,
    )
    student_rows = _table(
        text,
        "## 学生最终核对表",
        ("检查 ID", "项目", "状态", "Evidence ID", "学生记录"),
        issues,
    )
    report_root = path.resolve().parent
    product_path = (
        Path(product_audit_path)
        if product_audit_path is not None
        else report_root / "docs" / "audits" / "PRODUCT_AUDIT.md"
    )
    product_text = product_path.read_text(encoding="utf-8")
    product_generated_at = _metadata(product_text, "生成时间（UTC）", issues)
    product_status = _metadata(product_text, "就绪度", issues)
    product_scope = _metadata(product_text, "范围", issues)
    product_method = _metadata(product_text, "方法", issues)
    product_rows = _table(
        product_text,
        "## 产品审计矩阵",
        ("条目 ID", "领域", "流程步骤", "状态", "Evidence ID", "说明"),
        issues,
    )
    product_evidence_rows = _table(
        product_text,
        "## 证据索引",
        (
            "Evidence ID",
            "类型",
            "命令",
            "路径",
            "覆盖范围",
            "结果",
            "观察时间（UTC）",
            "退出码",
            "状态",
            "摘要",
        ),
        issues,
    )
    selected_reflection_path = (
        Path(reflection_path) if reflection_path is not None else report_root / "REFLECTION.md"
    )
    reflection_text = selected_reflection_path.read_text(encoding="utf-8")
    return DeliveryReport(
        path,
        generated_at,
        status,
        sections,
        _evidence_from_rows(evidence_rows, id_column="Evidence ID"),
        tuple(
            BlockingReason(
                row["阻塞项 ID"],
                row["负责人"],
                row["状态"],
                _refs(row["Evidence ID"]),
                row["原因"],
                row["关闭条件"],
            )
            for row in blocker_rows
        ),
        tuple(
            StudentCheck(
                row["检查 ID"],
                row["项目"],
                row["状态"],
                _refs(row["Evidence ID"]),
                row["学生记录"],
            )
            for row in student_rows
        ),
        tuple(
            ProductAuditItem(
                row["条目 ID"],
                row["领域"],
                row["流程步骤"],
                row["状态"],
                _refs(row["Evidence ID"]),
                row["说明"],
            )
            for row in product_rows
        ),
        _evidence_from_rows(product_evidence_rows, id_column="Evidence ID"),
        product_generated_at,
        product_status,
        product_scope,
        product_method,
        reflection_text,
        text,
        tuple(issues),
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


def _semantic_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_repo_path(repo_root: Path, value: str) -> bool:
    if value in {"", "-"}:
        return False
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    resolved = (repo_root / candidate).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError:
        return False
    return resolved.exists()


def _validate_current_status_documents(repo_root: Path, errors: list[str]) -> None:
    for name in ("README.md", "PLAN.md", "AGENT_LOG.md", "BLOCKERS.md", "REFLECTION_NOTES.md"):
        text = (repo_root / name).read_text(encoding="utf-8")
        if text.count(CURRENT_STATUS_START) != 1 or text.count(CURRENT_STATUS_END) != 1:
            errors.append(f"{name} must contain exactly one Task 24 current-status block")
            continue
        block = text.split(CURRENT_STATUS_START, maxsplit=1)[1].split(
            CURRENT_STATUS_END, maxsplit=1
        )[0]
        if "任务 24 当前状态" not in block or "任务 23 当前状态" in block:
            errors.append(f"{name} current status is stale")
        if "MUSEECHO V1 PARTIALLY READY" not in block:
            errors.append(f"{name} current status lacks the exact readiness")
        if "TASK24-AUDIT" in block:
            errors.append("Task 24 audit cannot remain a current blocker")


def validate_course_status_documents(repo_root: Path) -> tuple[str, ...]:
    errors: list[str] = []
    documents = ("PLAN.md", "README.md", "COURSE_DELIVERY_CHECKLIST.md")
    text_by_name = {name: (repo_root / name).read_text(encoding="utf-8") for name in documents}
    plan_block = (
        text_by_name["PLAN.md"]
        .split(CURRENT_STATUS_START, maxsplit=1)[1]
        .split(CURRENT_STATUS_END, maxsplit=1)[0]
    )
    normalized_plan_block = re.sub(r"\s+", " ", plan_block.replace(">", " "))
    if "学生撰写的反思草稿" not in normalized_plan_block:
        errors.append("PLAN.md current status must describe the student-authored reflection draft")
    for name, text in text_by_name.items():
        marker_lines = [
            line
            for line in text.splitlines()
            if line.startswith(FINAL_CI_MARKER_PREFIX) and line.endswith(FINAL_CI_MARKER_SUFFIX)
        ]
        observed: dict[str, str] = {}
        if len(marker_lines) == 1:
            payload = marker_lines[0][len(FINAL_CI_MARKER_PREFIX) : -len(FINAL_CI_MARKER_SUFFIX)]
            for segment in payload.split(";"):
                if "=" not in segment:
                    continue
                key, value = (part.strip() for part in segment.split("=", maxsplit=1))
                if key == "jobs":
                    for job in value.split(","):
                        if ":" in job:
                            job_name, job_status = (
                                part.strip() for part in job.split(":", maxsplit=1)
                            )
                            observed[job_name] = job_status
                else:
                    observed[key] = value
        for field, expected in EXPECTED_FINAL_CI_RELATIONSHIP.items():
            if observed.get(field) != expected:
                errors.append(f"{name} final-CI relationship has invalid {field}")
        if text.count(FINAL_CI_STATEMENTS[name]) != 1:
            errors.append(f"{name} final-CI relationship has invalid statement")
        visible_text = "\n".join(
            line for line in text.splitlines() if not line.startswith(FINAL_CI_MARKER_PREFIX)
        )
        normalized_visible_text = re.sub(r"\s+", " ", visible_text.replace(">", " "))
        for field, required_fragments in VISIBLE_FINAL_CI_CONTRACTS[name].items():
            if any(fragment not in normalized_visible_text for fragment in required_fragments):
                errors.append(f"{name} visible final-CI relationship has invalid {field}")

    agent_log = (repo_root / "AGENT_LOG.md").read_text(encoding="utf-8")
    if AGENT_LOG_SUMMARY_START not in agent_log or AGENT_LOG_DETAIL_START not in agent_log:
        errors.append("AGENT_LOG.md chronology collection markers are missing")
    else:
        summary = agent_log.split(AGENT_LOG_SUMMARY_START, maxsplit=1)[1].split(
            AGENT_LOG_DETAIL_START, maxsplit=1
        )[0]
        observed_headings = tuple(line for line in summary.splitlines() if line.startswith("### "))
        if observed_headings != AGENT_LOG_SUMMARY_HEADINGS:
            errors.append("AGENT_LOG.md summary records must be oldest-to-newest")
        detail = agent_log.split(AGENT_LOG_DETAIL_START, maxsplit=1)[1]
        detail_dates = [
            datetime.strptime(match, "%Y-%m-%d").date()
            for match in re.findall(r"(?m)^## (\d{4}-\d{2}-\d{2})", detail)
        ]
        if any(later < earlier for earlier, later in zip(detail_dates, detail_dates[1:])):
            errors.append("AGENT_LOG.md detailed records must be oldest-to-newest")

    reflection_notes = (repo_root / "REFLECTION_NOTES.md").read_text(encoding="utf-8")
    reflection_headings = tuple(
        line for line in reflection_notes.splitlines() if re.match(r"^## \d{4}-\d{2}-\d{2}", line)
    )
    if reflection_headings != REFLECTION_NOTES_DATED_HEADINGS:
        errors.append("REFLECTION_NOTES.md dated heading inventory is invalid")
    reflection_dates = [
        datetime.strptime(match, "%Y-%m-%d").date()
        for match in re.findall(r"(?m)^## (\d{4}-\d{2}-\d{2})", reflection_notes)
    ]
    if any(later < earlier for earlier, later in zip(reflection_dates, reflection_dates[1:])):
        errors.append("REFLECTION_NOTES.md dated records must be oldest-to-newest")
    _validate_release_contract(repo_root, errors)
    return tuple(errors)


def _validate_release_contract(repo_root: Path, errors: list[str]) -> None:
    manifest_path = repo_root / "release" / "v0.1.0-manifest.json"
    reproduction_path = repo_root / "RELEASE_REPRODUCTION.md"
    verifier_path = repo_root / "scripts" / "verify_github_release.py"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        errors.append("release/v0.1.0-manifest.json release contract is unreadable")
        return
    manifest_fields = {
        "repository": manifest.get("repository"),
        "tag": manifest.get("tag"),
        "target": manifest.get("target_commit"),
        "main-ci-run": manifest.get("main_ci_run"),
        "published-at": manifest.get("published_at"),
        "release-url": manifest.get("release_url"),
    }
    for field in ("repository", "tag", "target", "main-ci-run", "published-at", "release-url"):
        if manifest_fields[field] != RELEASE_CONTRACT[field]:
            errors.append(f"release/v0.1.0-manifest.json release contract has invalid {field}")
    expected_assets = tuple(
        {"name": name, "size": size, "sha256": sha256}
        for name, size, sha256 in RELEASE_CONTRACT["assets"]
    )
    observed_assets = manifest.get("assets")
    if not isinstance(observed_assets, list) or tuple(observed_assets) != expected_assets:
        errors.append("release/v0.1.0-manifest.json release contract has invalid assets")
    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("release/v0.1.0-manifest.json release contract has invalid provenance")
    else:
        required_provenance = {
            "mode": "local-rebuild-from-exact-main-commit",
            "source_commit": RELEASE_CONTRACT["target"],
            "main_ci_run": RELEASE_CONTRACT["main-ci-run"],
            "ci_distribution_passed": True,
            "ci_artifact_retained": False,
            "published_bytes_identity_checksum_smoke_verified": True,
            "byte_equality_with_unretained_ci_output_claimed": False,
        }
        if any(provenance.get(key) != value for key, value in required_provenance.items()):
            errors.append("release/v0.1.0-manifest.json release contract has invalid provenance")

    try:
        reproduction = reproduction_path.read_text(encoding="utf-8")
    except OSError:
        errors.append("RELEASE_REPRODUCTION.md release contract is unreadable")
        return
    normalized_reproduction = re.sub(r"\s+", " ", reproduction)
    reproduction_fields = {
        "release-url": (RELEASE_CONTRACT["release-url"],),
        "tag": (f"标签 `{RELEASE_CONTRACT['tag']}`",),
        "target": (RELEASE_CONTRACT["target"],),
        "main-ci-run": (str(RELEASE_CONTRACT["main-ci-run"]),),
        "published-at": (RELEASE_CONTRACT["published-at"],),
        "asset-name": tuple(f"`{name}`" for name, _, _ in RELEASE_CONTRACT["assets"]),
        "asset-size": tuple(f"{size:,} 字节" for _, size, _ in RELEASE_CONTRACT["assets"]),
        "asset-sha256": tuple(sha256 for _, _, sha256 in RELEASE_CONTRACT["assets"]),
        "replay-command": (
            "scripts/verify_github_release.py",
            "--action Smoke",
            "--manifest release/v0.1.0-manifest.json",
            "--assets-directory $releaseDir",
            "--download",
        ),
        "provenance": (
            "Actions 配额跳过了制品留存",
            "从精确 `main` SHA 本地重建",
            "不声称与 CI 内未留存 tar 字节相同",
            "镜像身份、打包、回下载校验和与真实 no-build Smoke",
        ),
    }
    for field, fragments in reproduction_fields.items():
        if any(fragment not in normalized_reproduction for fragment in fragments):
            errors.append(f"RELEASE_REPRODUCTION.md release contract has invalid {field}")
    if not verifier_path.is_file():
        errors.append("scripts/verify_github_release.py replay verifier is missing")
    stale_claims = {
        "PLAN.md": "最终 main CI 的 tar 已下载",
        "SPEC.md": "只允许发布同一 distribution 作业产生并审计的",
        "README.md": "两个经过同一 distribution 作业审计的镜像 tar",
        "docs/superpowers/specs/2026-08-17-offline-runtime-release-design.md": (
            "`release-images.json`, copied from the distribution job"
        ),
    }
    for relative_path, stale_claim in stale_claims.items():
        try:
            text = (repo_root / relative_path).read_text(encoding="utf-8")
        except OSError:
            errors.append(f"{relative_path} release provenance document is unreadable")
            continue
        if stale_claim in text:
            errors.append(f"{relative_path} contains stale retained-CI artifact provenance")


def validate_delivery_report(
    report: DeliveryReport, *, repo_root: Path, now: datetime | None = None
) -> None:
    now = now or datetime.now(UTC)
    errors = list(report.parse_issues)
    generated_at = _parse_utc(report.generated_at_raw)
    if generated_at is None:
        errors.append("delivery report generated time is not strict UTC")
    elif generated_at > now:
        errors.append("delivery report generated time is future-dated")
    if "任务 24 当前状态" not in report.raw_text or "任务 23 当前状态" in report.raw_text:
        errors.append("DELIVERY_REPORT.md current status is stale")
    if "TASK24-AUDIT" in report.raw_text:
        errors.append("Task 24 audit cannot remain a current blocker")

    section_ids = tuple(item.section_id for item in report.sections)
    missing_sections = tuple(item for item in EXPECTED_SECTION_IDS if item not in section_ids)
    duplicate_sections = _duplicates(section_ids)
    if missing_sections:
        errors.append(f"missing delivery sections: {', '.join(missing_sections)}")
    if duplicate_sections:
        errors.append(f"duplicate delivery sections: {', '.join(duplicate_sections)}")
    unexpected_sections = tuple(sorted(set(section_ids) - set(EXPECTED_SECTION_IDS)))
    if unexpected_sections:
        errors.append(f"unexpected delivery sections: {', '.join(unexpected_sections)}")
    if not missing_sections and not duplicate_sections and section_ids != EXPECTED_SECTION_IDS:
        errors.append("delivery sections are out of order")

    evidence_by_id = {item.evidence_id: item for item in report.evidence}
    task24_ci_evidence = evidence_by_id.get("DEL-011")
    if task24_ci_evidence is None or task24_ci_evidence.summary != EXPECTED_DEL_011_SUMMARY:
        errors.append("DEL-011 must remain historical Task 24 implementation evidence")
    for section, (expected_id, expected_title) in zip(
        report.sections, EXPECTED_SECTION_TITLES, strict=False
    ):
        if section.section_id == expected_id and section.title != expected_title:
            errors.append(f"{section.section_id} title does not match: {expected_title}")
        if section.status not in VALID_SECTION_STATUSES:
            errors.append(f"{section.section_id} has invalid section status")
        if section.conclusion in {"", "-"}:
            errors.append(f"{section.section_id} requires a conclusion")
        if not section.evidence_ids:
            errors.append(f"{section.section_id} requires evidence")
        expected_section_contract = SECTION_CONTRACTS.get(section.section_id)
        if expected_section_contract != (section.status, section.evidence_ids):
            errors.append(f"{section.section_id} status/evidence does not match the fixed contract")
        for evidence_id in section.evidence_ids:
            if evidence_id not in evidence_by_id:
                errors.append(f"{section.section_id} references unknown evidence {evidence_id}")

    evidence_ids = tuple(item.evidence_id for item in report.evidence)
    missing_evidence = tuple(item for item in EXPECTED_EVIDENCE_IDS if item not in evidence_ids)
    duplicate_evidence = _duplicates(evidence_ids)
    unexpected_evidence = tuple(sorted(set(evidence_ids) - set(EXPECTED_EVIDENCE_IDS)))
    if missing_evidence:
        errors.append(f"missing evidence ids: {', '.join(missing_evidence)}")
    if duplicate_evidence:
        errors.append(f"duplicate evidence ids: {', '.join(duplicate_evidence)}")
    if unexpected_evidence:
        errors.append(f"unexpected evidence ids: {', '.join(unexpected_evidence)}")
    prior_observed_at: datetime | None = None
    prior_evidence_id: str | None = None
    for report_evidence in report.evidence:
        if report_evidence.kind not in VALID_EVIDENCE_KINDS:
            errors.append(f"{report_evidence.evidence_id} has invalid evidence kind")
        if not _validate_repo_path(repo_root, report_evidence.path):
            errors.append(f"{report_evidence.evidence_id} evidence path is invalid or missing")
        observed_at = _parse_utc(report_evidence.observed_at_raw)
        if observed_at is None:
            errors.append(f"{report_evidence.evidence_id} has invalid observed UTC")
        else:
            if prior_observed_at is not None and observed_at < prior_observed_at:
                errors.append(
                    "evidence index must be oldest-to-newest: "
                    f"{report_evidence.evidence_id} is older than preceding {prior_evidence_id}"
                )
            prior_observed_at = observed_at
            prior_evidence_id = report_evidence.evidence_id
            if observed_at > now or (generated_at is not None and observed_at > generated_at):
                errors.append(f"{report_evidence.evidence_id} has an impossible observed UTC")
        contract = EVIDENCE_CONTRACTS.get(report_evidence.evidence_id)
        observed_contract = EvidenceContract(
            report_evidence.kind,
            report_evidence.command,
            report_evidence.path,
            report_evidence.coverage,
            report_evidence.result,
            report_evidence.exit_code_raw,
            report_evidence.status,
        )
        if contract is None or observed_contract != contract:
            errors.append(
                f"{report_evidence.evidence_id} does not match its fixed evidence contract"
            )

    blocker_ids = tuple(item.blocker_id for item in report.blockers)
    for blocker_id in REQUIRED_BLOCKER_IDS:
        if blocker_id not in blocker_ids:
            errors.append(f"required blocking reason is missing: {blocker_id}")
    if _duplicates(blocker_ids):
        errors.append(f"duplicate blocker ids: {', '.join(_duplicates(blocker_ids))}")
    if set(blocker_ids) - set(REQUIRED_BLOCKER_IDS):
        errors.append("unexpected blocking reason is present")
    for blocker in report.blockers:
        expected_blocker_contract = BLOCKER_CONTRACTS.get(blocker.blocker_id)
        if expected_blocker_contract != (blocker.owner, blocker.evidence_ids):
            errors.append(f"{blocker.blocker_id} owner/evidence does not match the fixed contract")
        if blocker.status != "OPEN":
            errors.append(f"{blocker.blocker_id} must remain OPEN")
        if not blocker.evidence_ids:
            errors.append(f"{blocker.blocker_id} requires evidence")
        for evidence_id in blocker.evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                errors.append(f"{blocker.blocker_id} references unknown evidence {evidence_id}")
            elif evidence.status != "PENDING":
                errors.append(f"{blocker.blocker_id} requires pending evidence")
        if len(blocker.closure_criteria) < 20 or blocker.closure_criteria.lower() in {
            "later",
            "tbd",
            "todo",
        }:
            errors.append(f"{blocker.blocker_id} closure criteria are not precise")

    if report.status not in {"MUSEECHO V1 READY", "MUSEECHO V1 PARTIALLY READY"}:
        errors.append("invalid delivery readiness")
    if report.status == "MUSEECHO V1 READY" and report.blocking_reasons:
        errors.append("READY contradicts open blockers")
    if report.status == "MUSEECHO V1 PARTIALLY READY" and not report.blocking_reasons:
        errors.append("PARTIALLY READY requires exact open blockers")
    delivery_narrative = [
        [section.section_id, section.conclusion] for section in report.sections
    ] + [
        [blocker.blocker_id, blocker.reason, blocker.closure_criteria]
        for blocker in report.blockers
    ]
    if _semantic_digest(delivery_narrative) != EXPECTED_DELIVERY_NARRATIVE_SHA256:
        errors.append("delivery narrative does not match the fixed contract")

    student_ids = tuple(item.check_id for item in report.student_checks)
    if student_ids != EXPECTED_STUDENT_CHECK_IDS:
        errors.append("student checklist IDs/order do not match the fixed contract")
    for student_check in report.student_checks:
        if student_check.status != "RESERVED":
            errors.append(f"{student_check.check_id} must remain RESERVED for the student")
        if student_check.evidence_ids != ("DEL-903",):
            errors.append(f"{student_check.check_id} must cite the reserved student evidence")
        if student_check.student_record != "-":
            errors.append(f"{student_check.check_id} student record must remain blank")
    reflection_digest = hashlib.sha256(
        report.reflection_text.replace("\r\n", "\n").encode("utf-8")
    ).hexdigest()
    if reflection_digest != EXPECTED_REFLECTION_DRAFT_SHA256:
        errors.append("student reflection draft does not match the retained course record")

    product_ids = tuple(item.item_id for item in report.product_audit_items)
    if product_ids != EXPECTED_PRODUCT_AUDIT_IDS:
        errors.append("product audit IDs/order do not match the fixed contract")
    if tuple(item.domain for item in report.product_audit_items) != PRODUCT_DOMAINS:
        errors.append("product audit domain coverage does not match the fixed contract")
    product_evidence_ids = {item.evidence_id for item in report.product_audit_evidence}
    if product_evidence_ids != {"PAE-001", "PAE-900"}:
        errors.append("product audit evidence inventory does not match the fixed contract")
    product_generated_at = _parse_utc(report.product_audit_generated_at_raw)
    if product_generated_at is None:
        errors.append("product audit generated time is not strict UTC")
    elif product_generated_at > now or (
        generated_at is not None and product_generated_at > generated_at
    ):
        errors.append("product audit generated time is impossible")
    if report.product_audit_status != "CONTROLLER_BLOCKED":
        errors.append("product audit readiness must preserve the controller block")
    if report.product_audit_scope != EXPECTED_PRODUCT_SCOPE:
        errors.append("product audit scope does not match the fixed contract")
    if report.product_audit_method != EXPECTED_PRODUCT_METHOD:
        errors.append("product audit method does not match the fixed contract")
    for evidence in report.product_audit_evidence:
        contract = PRODUCT_EVIDENCE_CONTRACTS.get(evidence.evidence_id)
        observed_contract = EvidenceContract(
            evidence.kind,
            evidence.command,
            evidence.path,
            evidence.coverage,
            evidence.result,
            evidence.exit_code_raw,
            evidence.status,
        )
        if contract is None or observed_contract != contract:
            errors.append(
                f"{evidence.evidence_id} does not match its fixed product evidence contract"
            )
        observed_at = _parse_utc(evidence.observed_at_raw)
        if observed_at is None:
            errors.append(f"{evidence.evidence_id} has invalid observed UTC")
        elif observed_at > now or (
            product_generated_at is not None and observed_at > product_generated_at
        ):
            errors.append(f"{evidence.evidence_id} has an impossible observed UTC")
    for product_item in report.product_audit_items:
        if product_item.status != "CERT_TRUST_BLOCKED":
            errors.append(f"{product_item.item_id} cannot claim PASS without controller execution")
        if product_item.evidence_ids != ("PAE-001", "PAE-900"):
            errors.append(
                f"{product_item.item_id} must cite implementation and pending controller evidence"
            )
        if product_item.notes in {"", "-"}:
            errors.append(f"{product_item.item_id} requires truthful notes")
    product_narrative = [
        [product_item.item_id, product_item.flow_step, product_item.notes]
        for product_item in report.product_audit_items
    ]
    if _semantic_digest(product_narrative) != EXPECTED_PRODUCT_NARRATIVE_SHA256:
        errors.append("product audit narrative does not match the fixed contract")

    _validate_current_status_documents(repo_root, errors)
    errors.extend(validate_course_status_documents(repo_root))
    if errors:
        raise DeliveryValidationError(
            "delivery report validation failed:\n- " + "\n- ".join(dict.fromkeys(errors))
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args(argv)
    try:
        report = load_delivery_report(args.report)
        validate_delivery_report(report, repo_root=args.report.resolve().parent)
    except (DeliveryValidationError, OSError) as exc:
        print(f"delivery report validation failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"17 delivery sections validated; evidence={len(report.evidence)}; "
        f"blockers={len(report.blocking_reasons)}; readiness={report.status}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
