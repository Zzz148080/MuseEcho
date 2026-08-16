# AI4SE 课程交付核对表

本表把课程最终交付清单映射到仓库现有材料与当前真实状态。它不替代课程要求，也不把未发生的
外部验收写成完成。

学生转述教师现在要求下列 9 项中至少完成 6 项才可通过。本表逐项记录证据与状态，**不**据此
代替教师判定，也不把“材料存在”“后续计划”或“学生草稿”计为已完成。

| # | 课程要求 | 仓库材料 | 当前结论 |
| --- | --- | --- | --- |
| 1 | `SPEC.md` | `SPEC.md`、`DESIGN.md`、`DECISIONS.md` | 材料已有；已同步当前七种音频格式与 100 MiB 边界。 |
| 2 | `PLAN.md` | `PLAN.md`、`docs/superpowers/plans/` | 24 个原始任务与 Task 24 后维护记录均存在；最终分支验证仍待如实记录。 |
| 3 | `SPEC_PROCESS.md` | `SPEC_PROCESS.md`、`COLD_START_REPORT.md`、`HUMAN_APPROVAL.md` | 已有真实 brainstorming、三轮迭代、不同 Agent cold-start 与修订记录。 |
| 4 | 源码、细粒度 Git/PR 历史 | `src/`、`frontend/`、`tests/`、Git 历史 | 已有实施历史与后续本地提交；当前状态是待推送并以最终 SHA 执行 GitHub CI 复验。 |
| 5 | 容器分发与 README | `Dockerfile`、`compose.yaml`、`README.md` | 本地容器构建/运行说明齐全；公开 registry 镜像与正式离线构建仍未完成，不能标记分发完成。 |
| 6 | `AGENT_LOG.md` | `AGENT_LOG.md` | Tasks 1–24 过程记录存在；Task 24 后维护的范围、提交与验证边界已补记，不能倒填不存在的技能、人工批准或测试。 |
| 7 | CI 配置与最后一次通过记录 | `.github/workflows/ci.yml` | 本次课程只要求 GitHub；final PR SHA is verified only by live GitHub checks after push。`DELIVERY_REPORT.md` 的 `DEL-011` 仅是历史 Task 24 implementation evidence，不能代替最终 CI。GitLab 配置保留为后续流水线材料。 |
| 8 | `REFLECTION.md` | `REFLECTION.md` | 学生本人正在修订；内容、最终签字和真实状态由学生负责确认。 |
| 9 | 后续线上 WebUI 部署 | `deploy/tencent-cloud/`、`DEPLOYMENT_EVIDENCE.md` | 不作为本次课程提交门禁；腾讯云、域名/DNS、可信 TLS、目标机 smoke、跨网/24 小时验证、备份恢复和回滚保留为下一步计划。 |

## 提交前必须关闭的事项

1. 整理工作区：决定未跟踪文件是否纳入提交，删除可再生临时目录，并确保最终分支只有有意变更。
2. 为 Task 24 后的代码与文档改动补齐 `PLAN.md` / `AGENT_LOG.md` 的真实记录；不得倒填不存在的
   Agent 技能、人工批准或测试结果。
3. 推送最终分支、建立 PR，并保留 GitHub 对最终 SHA 的通过记录。
4. 发布 digest 固定的 app/gateway OCI 镜像，完成正式 Docker 构建与安全/身份链复验。
5. 将腾讯云受信 TLS、公网 URL、真实上传、跨网、24 小时、备份恢复和回滚保留为下一步计划；
   获得授权后按 `DEPLOYMENT_EVIDENCE.md` 执行。
6. 学生本人完成 README 冷启动、真实音频验收、PR/CI/Secret 检查、反思定稿与签字；所有尚未完成
   项目保持 `MUSEECHO V1 PARTIALLY READY`。
