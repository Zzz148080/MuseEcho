# MuseEcho Blockers

当前没有已确认的真实 Blocker。

以下是尚未到达执行时点的外部 gate，不在本阶段虚假标记为 Blocker：

- 腾讯云账户实名认证、购买服务器和域名；
- NJU Git remote 与登录状态（仅在课程同步阶段需要）；
- 与 Codex 不同类型的第二 Agent 可用性；
- 最终学生人工验收和 `REFLECTION.md` 正文。

若其中任一在所需阶段确实不可用，将按用户要求记录精确错误、命令、日志、至少三种尝试和剩余可继续工作。

## 已解决的外部连接事项

- **GitHub — RESOLVED（2026-08-08）**：用户完成设备验证码授权后，GitHub CLI 在用户会话中确认登录账户 `Zzz148080`；私有仓库 `Zzz148080/MuseEcho` 可访问且初始为空。本地已配置 HTTPS `origin`，`main` 首次推送成功。

## CS-001：Codex 外部命令审批通道阻止 OpenCode cold-start

- **状态**：OPEN；只阻塞课程 cold-start 和其后的最终实施授权，不阻塞规格/计划文档工作。
- **问题**：OpenCode `1.17.14`、DeepSeek 凭据和 `deepseek/deepseek-v4-flash` 均已在用户会话中确认可见，但 Codex 在启动/探测 OpenCode 前的外部审批阶段反复连接中断。
- **精确错误**：`Automatic approval review failed: stream disconnected before completion: error sending request for url (https://chatgpt.com/backend-api/codex/responses)`。
- **相关命令**：`opencode.cmd run --help`；隔离 worktree 中的 `opencode.cmd run ... --model deepseek/deepseek-v4-flash ...`；位置参数前置的最小 parser probe。所有记录均不含 API Key。
- **已尝试方案**：1）用户首次明确批准后读取 run 参数；2）披露第三方传输/命令边界并再次获批后启动真实 cold-start；3）发现 `--file` 参数解析问题后用最小、无模型调用的 parser probe 验证修正。三次都被相同审批连接中断拒绝；另一次真实命令到达 OpenCode 参数解析，但未调用模型。
- **推荐恢复**：优先在审批通道恢复后重试“message 在前、`--file` 在后”的命令；备选为用户在可见终端中从隔离 worktree 手动启动 OpenCode，再将真实 session 输出交回审查。
- **仍可继续**：提交/推送真实记录、审阅命令与数据边界、保持 worktree 隔离；不得跳过 cold-start 或创建 `HUMAN_APPROVAL.md`。
