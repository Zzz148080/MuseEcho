# MuseEcho Blockers

当前没有阻塞本地继续实施或完成 Task 23 的已确认 Blocker。历史审批通道问题 `CS-001` 已在此前通过多次真实提权命令成功执行而关闭。

当前 Functional Audit 矩阵为 `28 PASS / 12 PARTIAL / 0 FAIL`，结论为 `PARTIALLY_READY`；Task 23 复审将本轮未重跑的 frontend type/build 从当前 PASS 证据中移除。以下未完成条件阻止 `READY`。

以下外部验收条件会阻止 `MUSEECHO V1 READY`，但不阻止本地 Task 22 完成：

- `TC-021`：目标服务器五分钟性能实测、腾讯云公网 URL、受信 TLS 完整 smoke、跨网与 24 小时观察仍未执行；
- `REMOTE-CI`：当前合并状态的 GitHub Actions 和 GitLab CI 均未真实运行；
- `TASK24-AUDIT`：Engineering Audit 已完成；Product Audit 与最终交付验证尚未开始；
- `STUDENT-MANUAL`：学生最终亲自验收和 `REFLECTION.md` 正文仍保留为人工待办。
- `CURRENT-BROWSER-E2E`：Task 19 的浏览器证据与当前 108-file source/test boundary 不同；Task 23 no-build HTTPS 已可由宿主访问且 Chrome 存在，但保留的锁定 root Playwright 缓存目标已消失，在禁止下载下当前真实浏览器套件仍未运行。
- `FORMAL-OFFLINE-BUILD`：正式 current-source Dockerfile 在 `--network none` 下缺少完整锁定 pip/apt BuildKit cache，真实构建 exit 1；当前受控 derivative 仅供审计，禁止作为发布镜像。恢复完整缓存后必须重新构建并重跑 release identity 与安全链。

以下是尚未到达执行时点的外部 gate，不在本阶段虚假标记为 Blocker：

- 腾讯云账户实名认证、购买服务器和域名；
- NJU Git remote 与登录状态（仅在课程同步阶段需要）；
- 与 Codex 不同类型的第二 Agent 可用性；
- 最终学生人工验收和 `REFLECTION.md` 正文。

## TC-021：腾讯云公网部署授权与外部验收

- **状态：** 外部待决；不阻塞 Task 21/22 的本地脚本、审计和文档工作，但阻止目标服务器性能 PASS，以及任何真实公网 URL、TLS、跨网 smoke、24 小时清理观察或服务器回滚证据。
- **缺少条件：** 腾讯云账号/实名与 Lighthouse、可控域名/DNS、服务器 SSH 授权，以及可发布的 digest-qualified app/gateway OCI 镜像引用。
- **已完成的安全范围：** 本地实现只接受 `name@sha256:<digest>`，不使用 tag 回退；`install.sh --check-only` 和临时根目录合约测试没有修改真实主机、云资源或秘密。
- **后续动作：** 获授权后按 `DEPLOYMENT_EVIDENCE.md` 逐项执行，记录 UTC 时间、红acted 命令结果和真实失败；未完成前不得填写公网 URL 或 PASS。

## CURRENT-BROWSER-E2E：当前提交的真实浏览器边界

- **状态：** 环境待决；不阻止 Task 23 本地审计完成，但阻止依赖当前浏览器链路的 5 个验收项成为 PASS。
- **已验证：** 当前 frontend Vitest 为 12 files / 66 tests；锁定 current app 与 gateway 的 production no-build HTTPS smoke 可由宿主访问并完成重启与清理，已安装 Chrome 存在。保留的 root `node_modules` junction 目标已消失，当前没有锁定 Playwright harness；未执行 `npm ci` 或浏览器下载。
- **真实性边界：** 历史 `1047ce242884b6ba83a525524e88dcc44ab76a69` 有 4 个 Chrome E2E，但其 105-file browser/source/test manifest 与当前 108-file manifest 不同，不能作为当前 PASS。
- **后续动作：** 恢复与当前 lock 完全一致的 root/frontend dependency cache，或提供预建且 no-egress 的浏览器测试环境后重跑；否则 Task 24 继续保留这些条目为 PARTIAL。

若其中任一在所需阶段确实不可用，将按用户要求记录精确错误、命令、日志、至少三种尝试和剩余可继续工作。

## 已解决的外部连接事项

- **GitHub — RESOLVED（2026-08-08）**：用户完成设备验证码授权后，GitHub CLI 在用户会话中确认登录账户 `Zzz148080`；私有仓库 `Zzz148080/MuseEcho` 可访问且初始为空。本地已配置 HTTPS `origin`，`main` 首次推送成功。

## CS-001：Codex 外部命令审批通道连接中断

- **状态**：RESOLVED（2026-08-08）；本轮 Docker 验证、Git 合并/提交和 GitHub 推送均通过正常审批通道成功执行。
- **问题**：Codex 在执行已获用户明确批准、且不读取密钥正文的外部命令前，自动审批服务反复连接中断；命令本身没有开始执行。
- **精确错误**：`Automatic approval review failed: stream disconnected before completion: error sending request for url (https://chatgpt.com/backend-api/codex/responses)`。
- **相关命令**：`opencode.cmd run --help`；隔离 worktree 中的 `opencode.cmd run ... --model deepseek/deepseek-v4-flash ...`；位置参数前置的最小 parser probe。所有记录均不含 API Key。
- **已尝试方案**：1）用户首次明确批准后读取 run 参数；2）披露第三方传输/命令边界并再次获批后启动真实 cold-start；3）发现 `--file` 参数解析问题后用最小、无模型调用的 parser probe 验证修正。三次都被相同审批连接中断拒绝；另一次真实命令到达 OpenCode 参数解析，但未调用模型。
- **新增复核失败（2026-08-08 05:54 +08:00）**：用户逐字批准“只读环境权限复核（Docker、WSL、GitHub Actions、机器资源），不读取密钥正文，不修改任何设置”后，复核命令仍在执行前被同一审批错误拒绝。没有读取密钥、没有修改设置。
- **恢复证据**：本轮没有绕过审批；需要用户会话权限的命令经正常批准后成功执行。若将来同一错误再次出现，应作为新事件重新记录，而不是沿用已关闭状态。
- **门禁结果**：corrected cold-start 已完成审查并合并，用户已明确授权最终修订和生成 `HUMAN_APPROVAL.md`。

## 用户会话与外部准备状态

- Docker CLI、Compose 与 Docker Desktop Linux daemon 已确认可用；`docker info` 返回 Server `29.1.3`、Docker Desktop、16 CPU、14,551,777,280 字节容器内存。
- WSL 已确认可用：默认分发为 Ubuntu 20.04，默认版本为 WSL 2。
- 机器资源已确认：16 个逻辑处理器、29,860,155,392 字节物理内存，D 盘剩余 236,358,885,376 字节。
- GitHub Actions 已启用，允许全部 Actions；默认 `GITHUB_TOKEN` 工作流权限为只读，且不能批准 PR review。CI 应显式声明最小 `permissions`，需要写权限的发布任务必须单独授权。
- NJU Git/GitLab remote、腾讯云服务器/域名/DNS/SSH 授权只在课程同步与部署阶段需要，目前未配置。
