# MuseEcho Reflection Notes

本文件仅积累客观过程材料，不代写学生的 `REFLECTION.md`，也不替学生生成主观结论。

## 2026-08-11 — TASK 22 / 证据驱动验收材料

- 单纯列出文件无法证明验收通过。Task 22 将 24 个 AC 和 16 个 DoD 条目固定为 40 个 ID，并让 checker 拒绝缺失/重复、文件存在型 PASS、无命令/路径/UTC/退出码证据、未来时间和 blocker/READY 矛盾。
- 当前锁定 Linux 运行时没有 Git。checker 首版把“精确历史提交可验证”误实现为“任何环境都必须现场启动 Git”，导致 612 个既有测试通过而 23 个新测试同因 `FileNotFoundError` 失败。修复后的边界是 exact 40 位 commit 与 command/path 绑定；有 Git 时额外验证对象，没有 Git 时仍能运行离线矩阵门。
- PowerShell 会把子进程 ErrorRecord 按显示宽度换行。Secret scanner 已正确 fail-closed，但 synthetic harness 把格式化文本当原始字符串匹配而误报；对诊断输出先规范空白即可保持完整文件名断言，不需要降低扫描标准。
- 本地两核五分钟基准、内部 CA smoke 和配置文件存在不能替代目标服务器、公网受信 TLS 或远程 CI。矩阵因此保持 6 个 PARTIAL，且学生人工验收继续保留为人工待办。
- 容器 smoke 的强制 build 在缓存失效时执行了锁定 `npm ci`。虽然锁文件和依赖版本没有变化，这仍是一次与 Task 22 禁止下载约束不一致的过程事件，必须保留在报告而不能用“可复现构建”掩盖。

## 2026-08-11 — TASK 21 / 交付边界的本地证据

- Task 20 的 tar/config identity 不能被叙述成已发布的 registry digest；Task 21 因而明确拒绝 tag，要求部署操作员提供真实 `name@sha256:` 引用。
- 第一次 script integration test 暴露 test-root 的非 root 身份不能模拟生产 `chown`，因此测试适配器只在 `MUSEECHO_TEST_ROOT` 下省略所有者切换；真实路径仍使用 root 与 GID 10001。另一个 RED 暴露 systemd 只读取 runtime env 却没有 release image 变量，且 provider secret 路径被无条件配置；修复后每个 immutable release 有非秘密 `release.env`，默认 KEK-only 启动保持 provider 三项全空。
- 外部授权缺失不是停止可验证本地工作的理由。`DEPLOYMENT_EVIDENCE.md` 把脚本和临时根目录证据与尚未发生的公网 smoke、跨网测试、清理和回滚演练明确分开。

## 2026-08-08 — 前置设计阶段

- `brainstorming` 的一次一问机制产生了连续的真实用户选择，没有用 AI 自行模拟批准。
- 视觉伴侣用于比较三种布局和三种视觉方向；终端选择与浏览器点击记录一致。
- “LLM 永远不产生事实”被用户理解为“这些功能不做”。经质询后改写为 DSP/MIR 产生事实、LLM 解释证据。这是一次由 SPEC 措辞造成的真实误解案例。
- 最初的“分析后立即删除音频”与刷新后播放冲突。用户在看到三种方案后改选 24 小时加密保留，导致数据模型、Range API、密钥生命周期和测试范围扩大。
- Fly.io 的大陆访问和付款问题使初始部署建议失效。AutoDL 又因个人公网端口和第三方访问条款不满足课程公网 WebUI。最终选定腾讯云香港 Lighthouse。
- 此阶段尚未执行 TDD、subagent、worktree、CI 或 code review；不得提前评价它们的效果。
- 现有工作区没有 Git 历史，必须从设计文档开始建立真实的细粒度历史。
