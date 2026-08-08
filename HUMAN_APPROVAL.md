# MuseEcho 正式实施人工批准

**状态：** APPROVED FOR IMPLEMENTATION

**批准日期：** 2026-08-08

## 1. 人工批准原文

用户在完成 corrected cold-start 审查后明确指示：

> 合并到主分支，最后审查修订SPEC和PLAN，批准生成HUMAN_APPROVAL.md

本文件由 Codex 按该明确指示生成，用于真实记录实施门禁已经放行；它不是代替用户签名的虚构材料。

## 2. 获批规格与计划

本次批准严格锚定以下不可变 Git 对象：

| 对象 | 标识 |
| --- | --- |
| 最终 SPEC/PLAN 修订提交 | `e1ecaae359db129b779f1ddcc83665bca8cdfe1c` |
| `SPEC.md` Git blob | `f0180ecbc5ce587c532d123881bee17ac889da08` |
| `SPEC.md` SHA-256 | `fe97597ab01aa122dd98b16b57be3316f7199a0de90caa324a00ccff3bca1593` |
| `PLAN.md` Git blob | `49f46e9700356be14e0d0e241a1d8ba69952ea7b` |
| `PLAN.md` SHA-256 | `40fd9c23f0ae47909bef8b29f59591c705ded47c97e746011072a6851293a644` |

任何后续修改都必须形成新的 Git 提交并在过程记录中说明；重大产品范围、隐私边界、部署目标或验收标准变更需要重新取得人工确认，不能沿用本批准冒充新授权。

## 3. 门禁证据

- 书面 SPEC 已批准，并已按 Open Design 与中文完整设计要求修订。
- PLAN 已批准；真实 OpenCode cold-start 使用 `njusehub/deepseek-v4-flash` 完成任务 1–2 尝试。
- 原始 cold-start 提交 `1a3545d` 因审查失败未被接受；修正提交 `07d135e` 经测试驱动修复和三轮独立复审后无剩余 Critical、Important 或 Minor。
- 用户选择把 corrected cold-start 合并到 `main`；合并提交为 `a2d7af5`。
- 合并后的主分支重新验证：39 个 Python 测试、Ruff、格式、mypy、fresh Alembic upgrade/check、Node 22 容器前端测试/typecheck/build 均通过，npm audit 为 0 漏洞。
- `SPEC_PROCESS.md`、`AGENT_LOG.md`、`COLD_START_REPORT.md`、`DECISIONS.md` 和 `BLOCKERS.md` 保留真实过程、失败和恢复证据。

## 4. 授权范围

- Tasks 1–2 作为已经完成并合并的正式基线保留。
- 授权从 `PLAN.md` 的 Task 3 开始继续 MuseEcho V1 正式实现，按依赖图推进 Tasks 3–24。
- 后续任务继续执行隔离分支、TDD、规格符合性审查、代码质量审查、完整验证、PR 和真实过程记录。
- 允许在项目范围内构建、运行和测试；所有结果必须以真实命令输出为证据。

## 5. 不包含的声明或授权

- 不代表 Tasks 3–24、GitHub/GitLab CI、腾讯云部署、公网测试、三轮最终 Audit 或学生验收已经完成。
- 不授权伪造测试、PR、CI、部署、人工参与或产品就绪状态。
- 不授权读取、记录或提交 API Key、密码、Cookie、私钥等密钥正文。
- 腾讯云购买/续费、域名、DNS、NJU Git/GitLab 登录、生产密钥配置和最终学生验收仍在到达相应阶段时使用真实 human-owned 权限与证据。
- 只有全部 Definition of Done 具有最新通过证据时，才能声明 `MUSEECHO V1 READY`。
