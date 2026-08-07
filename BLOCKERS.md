# MuseEcho Blockers

当前存在一个已确认的外部审批通道 Blocker（`CS-001`）。它不阻塞仓库内的文档、编码和本地测试，但会阻止 Codex 代为执行需要提升到用户会话的命令。

以下是尚未到达执行时点的外部 gate，不在本阶段虚假标记为 Blocker：

- 腾讯云账户实名认证、购买服务器和域名；
- NJU Git remote 与登录状态（仅在课程同步阶段需要）；
- 与 Codex 不同类型的第二 Agent 可用性；
- 最终学生人工验收和 `REFLECTION.md` 正文。

若其中任一在所需阶段确实不可用，将按用户要求记录精确错误、命令、日志、至少三种尝试和剩余可继续工作。

## 已解决的外部连接事项

- **GitHub — RESOLVED（2026-08-08）**：用户完成设备验证码授权后，GitHub CLI 在用户会话中确认登录账户 `Zzz148080`；私有仓库 `Zzz148080/MuseEcho` 可访问且初始为空。本地已配置 HTTPS `origin`，`main` 首次推送成功。

## CS-001：Codex 外部命令审批通道连接中断

- **状态**：OPEN；OpenCode cold-start 已由用户在可见终端手动启动，但同一故障仍阻塞 Codex 对 Docker/WSL/GitHub Actions/机器资源的用户会话只读复核，以及其他需要外部权限的命令。
- **问题**：Codex 在执行已获用户明确批准、且不读取密钥正文的外部命令前，自动审批服务反复连接中断；命令本身没有开始执行。
- **精确错误**：`Automatic approval review failed: stream disconnected before completion: error sending request for url (https://chatgpt.com/backend-api/codex/responses)`。
- **相关命令**：`opencode.cmd run --help`；隔离 worktree 中的 `opencode.cmd run ... --model deepseek/deepseek-v4-flash ...`；位置参数前置的最小 parser probe。所有记录均不含 API Key。
- **已尝试方案**：1）用户首次明确批准后读取 run 参数；2）披露第三方传输/命令边界并再次获批后启动真实 cold-start；3）发现 `--file` 参数解析问题后用最小、无模型调用的 parser probe 验证修正。三次都被相同审批连接中断拒绝；另一次真实命令到达 OpenCode 参数解析，但未调用模型。
- **新增复核失败（2026-08-08 05:54 +08:00）**：用户逐字批准“只读环境权限复核（Docker、WSL、GitHub Actions、机器资源），不读取密钥正文，不修改任何设置”后，复核命令仍在执行前被同一审批错误拒绝。没有读取密钥、没有修改设置。
- **推荐恢复**：等待审批服务恢复后重试；在此之前，用户可在自己的 PowerShell 中手动运行明确列出的只读命令并交回输出。不得通过其他命令间接绕过审批。
- **仍可继续**：仓库内编码、测试、文档审阅和隔离 worktree 工作；不得在 cold-start 报告未完成审查、书面规格/计划未按报告修订并获得最终批准前创建 `HUMAN_APPROVAL.md` 或开始正式实现。

## 尚待用户会话确认的准备项

- Docker CLI 与 Compose 已安装；沙箱内无法连接 Docker named pipe，需在用户会话确认 Docker Desktop/daemon 状态。
- WSL 状态、机器 CPU/内存/磁盘余量因权限边界未确认。
- GitHub 登录、私有仓库访问和历史推送已确认；仓库级 Actions 权限开关尚未从用户会话读取。
- NJU Git/GitLab remote、腾讯云服务器/域名/DNS/SSH 授权只在课程同步与部署阶段需要，目前未配置。
