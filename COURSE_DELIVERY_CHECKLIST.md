# AI4SE 课程交付核对表

本表把课程最终交付清单映射到仓库现有材料与当前真实状态。它不替代课程要求，也不把未发生的
外部验收写成完成。

学生转述教师现在要求下列 9 项中至少完成 6 项才可通过。本表逐项记录证据与状态，**不**据此
代替教师判定，也不把“材料存在”“后续计划”或“学生草稿”计为已完成。

| # | 课程要求 | 仓库材料 | 当前结论 |
| --- | --- | --- | --- |
| 1 | `SPEC.md` | `SPEC.md`、`DESIGN.md`、`DECISIONS.md` | 材料已有；已同步当前七种音频格式与 100 MiB 边界。 |
| 2 | `PLAN.md` | `PLAN.md`、`docs/superpowers/plans/` | 24 个原始任务、任务 24 后维护记录、最终 CI 与正式 Release 闭环均按时间线记录。 |
| 3 | `SPEC_PROCESS.md` | `SPEC_PROCESS.md`、`COLD_START_REPORT.md`、`HUMAN_APPROVAL.md` | 已有真实需求探索、三轮迭代、不同 Agent cold-start 与修订记录。 |
| 4 | 源码、细粒度 Git/PR 历史 | `src/`、`frontend/`、`tests/`、Git 历史 | 最终产品实现边界为 PR #3 run `31966788273` / SHA `0674f74f4097e46cee98c4715a62ad5aa55101cf`；PR #3 合并后，main run `31997390847` 在合并 SHA `d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1` 上通过。 |
| 5 | 容器分发与 README | `Dockerfile`、`compose.yaml`、`README.md`、`RELEASE_REPRODUCTION.md` | GitHub `v0.1.0` 正式离线运行 Release 已发布且完成回下载复现；公开 OCI registry 与当前源码断网重建 ENG-010 仍未完成。 |
| 6 | `AGENT_LOG.md` | `AGENT_LOG.md` | 任务 1–24 过程记录存在；任务 24 后维护的范围、提交与验证边界已补记，不能倒填不存在的技能、人工批准或测试。 |
| 7 | CI 配置与最后一次通过记录 | `.github/workflows/ci.yml` | 本次课程只要求 GitHub；`DEL-013` 记录 main run `31997390847` 的 quality/E2E/distribution 全绿。`DEL-012` 保留最终产品实现边界；GitLab 配置仅作为补充性后续材料保留。 |
| 8 | `REFLECTION.md` | `REFLECTION.md` | 学生本人正在修订；内容、最终签字和真实状态由学生负责确认。 |
| 9 | 后续线上 WebUI 部署 | `deploy/tencent-cloud/`、`DEPLOYMENT_EVIDENCE.md` | 不作为本次课程提交门禁；腾讯云、域名/DNS、可信 TLS、目标机 smoke、跨网/24 小时验证、备份恢复和回滚保留为下一步计划。 |

<!-- FINAL-CI-RELATIONSHIP: implementation-sha=d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1; run=31997390847; jobs=quality:success,e2e:success,distribution:success; github=required; gitlab=supplemental-not-run; reconciliation=docs-only-after-release; release-tag=v0.1.0; release-assets=4 -->
已发布的 v0.1.0 Release 绑定该精确 main SHA 与四项经过校验和验证的资产；后续仅文档证据对账须运行独立 CI，但不会改写已发布资产的身份。

## 提交前必须关闭的事项

1. 保持 GitHub `v0.1.0` 的四项已发布资产、Tag 与 SHA-256 清单不可变；如需更改发行内容，使用新版本而非覆盖资产。
2. 为本次 Release 后的文档证据对账运行独立 PR/main CI；不得把文档提交冒充第二次产品实现验证。
3. 公开 OCI registry 如后续启用，另行发布 app/gateway 摘要；它不影响已完成的 GitHub 离线运行发行。
4. 当前源码 Dockerfile 断网重建继续按 ENG-010 保留，不得用已有镜像导入结果将其标记完成。
5. 将腾讯云受信 TLS、公网 URL、真实上传、跨网、24 小时、备份恢复和回滚保留为下一步计划；
   获得授权后按 `DEPLOYMENT_EVIDENCE.md` 执行。
6. 学生本人完成 README 冷启动、真实音频验收、PR/CI/Secret 检查、反思定稿与签字；所有尚未完成
   项目保持 `MUSEECHO V1 PARTIALLY READY`。
