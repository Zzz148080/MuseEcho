# MuseEcho Reflection Notes

本文件仅积累客观过程材料，不代写学生的 `REFLECTION.md`，也不替学生生成主观结论。

<!-- TASK24-CURRENT-STATUS:START -->
## Task 24 current status

`MUSEECHO V1 PARTIALLY READY`. Task 24's Product Audit, fixed 17-section
Delivery Report, validator, tests, and blank student reflection template are
complete. Task 24 is not a blocker. Task 23 PR #1 is merged with all three
GitHub jobs green. GitLab, the Task 24 branch-tip gate, cloud/public/target-server
smoke and rollback, formal offline build ENG-010, trusted-certificate controller
browser observation, and student gates remain open. Older statements below are
historical timeline evidence.
<!-- TASK24-CURRENT-STATUS:END -->

## 2026-08-13 — TASK 24 / 客观交付材料

- 交付报告的 17 节来自状态摘要加 README 交付合同的 16 类，不把 SPEC 的 24 章误称为用户要求的 17 节。
- 产品审计表完整覆盖 13 个体验域；控制器真实启动了 no-build HTTPS 服务并观察到 API ready，但浏览器在渲染前拒绝内部 CA。自动测试不能替代未发生的视觉观察，因此统一保留 `CERT_TRUST_BLOCKED`。
- `PARTIALLY READY` 不是模糊结论。每个 blocker 都有 owner、pending evidence 和可执行 closure criteria；Task 24 artifact 完成后不再把自身留作 blocker。
- 学生反思的真实性边界由空白模板与 validator 双重保护：学生 checklist 不能被 Agent 勾选，反思正文和签名保持空白。

## 2026-08-11 — TASK 22 / 证据驱动验收材料

- 单纯列出文件无法证明验收通过。Task 22 将 24 个 AC 和 16 个 DoD 条目固定为 40 个 ID，并让 checker 拒绝缺失/重复、文件存在型 PASS、无命令/路径/UTC/退出码证据、未来时间和 blocker/READY 矛盾。
- 当前锁定 Linux 运行时没有 Git。checker 首版把“精确历史提交可验证”误实现为“任何环境都必须现场启动 Git”，导致 612 个既有测试通过而 23 个新测试同因 `FileNotFoundError` 失败。修复后的边界是 exact 40 位 commit 与 command/path 绑定；有 Git 时额外验证对象，没有 Git 时仍能运行离线矩阵门。
- PowerShell 会把子进程 ErrorRecord 按显示宽度换行。Secret scanner 已正确 fail-closed，但 synthetic harness 把格式化文本当原始字符串匹配而误报；对诊断输出先规范空白即可保持完整文件名断言，不需要降低扫描标准。
- 本地两核五分钟基准、内部 CA smoke 和配置文件存在不能替代目标服务器、公网受信 TLS 或远程 CI。Task 23 复审后的当前矩阵为 `28 PASS / 12 PARTIAL / 0 FAIL`；frontend type/build 在本轮未运行即不得沿用 Task 22 PASS，且学生人工验收继续保留为人工待办。
- 容器 smoke 的强制 build 在缓存失效时执行了锁定 `npm ci`。虽然锁文件和依赖版本没有变化，这仍是一次与 Task 22 禁止下载约束不一致的过程事件，必须保留在报告而不能用“可复现构建”掩盖。
- exit 0 只是进程结果，不是功能证据。审查 mutation 证明把当前 evidence 的命令和结果一起改成无意义成功仍可绕过初版 checker；代码内逐 evidence 固定 command、coverage、可量化 result 后，审计文本本身不能同步改写策略。
- 无 Git 可移植性不能以放弃真实性为代价。历史 E2E 现在同时绑定 PLAN 中的完整 commit 锚点、历史内容摘要和当前 source/test SHA-256 manifest；有 Git 时再用单次 archive 校验历史 manifest。这样 Git-less runtime 能拒绝 audit-only 伪造，同时不要求生产镜像安装 Git。
- “过去跑过浏览器测试”只有在相关边界未变时才能支撑当前 PASS。Task 19 与当前 manifest 的客观漂移使 5 个条目从 PASS 降为 PARTIAL；这比用历史成功填满矩阵更准确，也保留了在合适隔离环境重跑的明确闭环。
- README 与 CI 文件存在不等于交付可用。当前 E005 通过解析两套 CI（包括 GitLab `unit-test`）并断言 README 的锁定安装、开发 HTTPS、生产 smoke、health 与 cleanup 路径，把 AC-F-2/AC-F-3/DOD-11/DOD-12 绑定到可测合约而不是 `git show --stat`。

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

## 2026-08-11 — TASK 23 / 工程审计过程材料

- 多文件 CLI 的“exit 0”不能证明每个输入都被消费。Bash `-n` 只解析第一个脚本的行为说明，mutation 必须放在最后一个输入才能暴露这种 coverage gap；修复应逐文件建立独立进程边界。
- cleanup 不是附属成功路径。部分启动后必须进入 cleanup，且 primary failure 与 cleanup failure 是两个独立事实；只保留任一都会让运维诊断失真。
- “no-build”不仅是不运行 build，还要在启动前确认 exact local image identity，并让 Compose 显式 `up --no-build`。这使离线审计不会因 cache miss 意外进入依赖下载。
- 完整 runtime manifest 揭示了 gitignored egg-info 被 Docker context 带入 Task20 镜像/策略。`.gitignore` 不等于 `.dockerignore`；干净 checkout 可复现性必须从真实 Docker context 和镜像内容验证，而不是从 tracked 文件列表推断。
- VEX 可以在 raw 181/67 不变时得到 residual zero，但前提是每个 CVE 的 package/file/reachability 证据、完整 source/runtime hash 与 exact image identity 均未漂移。本轮 observability 变更不增加 decoder、FFmpeg、动态 SQL、subprocess 或外部执行路径，因此保留原 67 条 statement；先观察到的 boundary drift 被明确当作 RED，而非自动刷新掩盖。
- 大型安全证据不必全量进入 Git，但 compact manifest 必须是确定性的、由 checker 固定并包含足够交叉字段。单独的“文件存在”或 Markdown 中的“0 findings”仍不构成验证。
- 宿主缺 ffmpeg 导致 benchmark 失败时，应在实际锁定 Linux 镜像中复验；本轮同一五分钟测试在镜像内 51.24 秒通过。相同原则适用于缺 `pwsh`、`uv`、`@types/node` 或 Playwright cache：记录精确环境限制，不下载修环境，也不把历史成功伪装成本轮执行。
- 复审还说明“证据内部自洽”并不等于证据独立。FIXED finding 必须绑定它自己的 RED/GREEN 命令、路径、结果和覆盖；no-build 必须绑定信任身份并检查实际运行容器；历史 frontend build 也不能在本轮未执行时继续支持 PASS。
- Task 23 第二轮复审进一步证明 compact manifest 自身固定仍不足以构成 completion：默认 checker 必须实际读取并复算 retained raw/package/VEX/inventory/tar/release/DB/image；无材料的便携校验只能显式称为 `--schema-only`。正式离线 Dockerfile 构建失败也必须成为独立 BLOCKED finding，而不能只藏在报告 concern 中。
