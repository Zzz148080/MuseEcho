# MuseEcho 规格生成过程

本文件只记录真实发生的 brainstorming、设计确认和后续 cold-start 规约验证。未发生的活动不会补写或模拟。

## 1. 起始状态

时间：2026-08-08

主开发智能体：OpenAI Codex App

使用流程：`superpowers:using-superpowers` → `superpowers:brainstorming`

初始仓库检查结果：

- 工作区根目录没有 Git 仓库。
- 没有 MuseEcho 源码。
- 没有 `HUMAN_APPROVAL.md`。
- 存在两份 AI4SE 课程要求和一份 10 页 MuseEcho 产品 PDF。
- 存在 `ai4coding-agentos-lab` 旧项目目录，与 MuseEcho 无关，未作为代码基础。
- Superpowers 6.2.0 的当前 Skill 文档可读。

因此遵守 gate：不写应用实现，先完成真实 brainstorming 和设计确认。

## 2. 资料审查

已完整读取：

- `docs/input/AI4SE_Final_Project_通用要求.md`
- `docs/input/AI4SE_Final_Project_B_应用类项目.md`
- `docs/input/01-作品说明文档+乐见知音.pdf`
- 用户附加的 MuseEcho 总体执行要求
- 当前 `using-superpowers`、`brainstorming`、PDF 与视觉伴侣说明

产品 PDF 经文本提取和逐页渲染检查，确认原始设计包含音乐解析流程、Music DNA、多轨结构地图、和弦解构、片段追问与共鸣分享。

## 3. 关键 brainstorming 决策

以下按真实对话顺序记录。用户只回复选项字母或“是/批准”的地方，不补充其未表达的主观理由。

| 序号 | AI 提出的关键选择 | AI 推荐 | 用户实际决定 | 规格影响 |
| --- | --- | --- | --- | --- |
| 1 | CPU 务实基线 / 模型增强 / 限定曲风 | CPU 务实基线 | `A` | DSP/MIR 优先，低置信度允许 unknown，不做分轨和乐器识别 |
| 2 | 无登录公开体验 / 单用户库 / 多用户平台 | 无登录公开体验 | `A` | 无账户，短期结果与滥用防护 |
| 3 | 部署者 Key / 用户会话 Key / 无 LLM | 部署者 Key | `A` | 服务端可选 LLM，无 Key fallback |
| 4 | React/Vite+FastAPI / Next+FastAPI / HTMX | React/Vite+FastAPI | `A` | 模块化单体，同容器托管静态前端 |
| 5 | 上传和性能三档 | 10 分钟、30 MB、异步 | `A` | 固定输入上限和 5 分钟/90 秒性能目标 |
| 6 | 置信度分级 / 始终 top-1 / 仅高置信度 | 分级 | `A` | 高/中/unknown，低置信度不进入 LLM |
| 7 | 24 小时 / 7 天 / 页面关闭失效 | 24 小时 | `A` | 24 小时结果生命周期 |
| 8 | 三种核心工作区布局 | 引导式单画布 | `A`，浏览器点击记录一致 | 统一时间轴上的渐进式下钻 |
| 9 | 三种视觉方向 | 温暖共鸣 | `A`，浏览器点击记录一致 | 暖白、青绿、珊瑚橙、金黄 tokens |
| 10 | 进程池 / Redis Worker / 云异步任务 | 单体受限进程池 | `A` | 单实例并发 1，其余排队 |
| 11 | CLI / Web 管理页 / `.env` | 本地 CLI | `A` | Key set/status/update/clear，无远程 Secret API |
| 12 | 免费 / 小额付费 / 自有 VPS | 小额付费 | `B` | 预算约 50–100 元/月 |
| 13 | 模块化单体 / 分布式 / 本地分析 | 模块化单体 | `确认采用A` | 整体架构正式确认 |

## 4. 有价值的设计迭代

### 迭代 1：澄清“LLM 不产生事实”并非删除功能

AI 初始设计写道：“LLM 永远不产生和弦、调性、结构、时间戳或能量变化等音乐事实。”

用户质询：

> 为什么LLM 永远不产生和弦、调性、结构、时间戳或能量变化等音乐事实？这些功能不做吗？

澄清结果：这些功能全部实现，但由 DSP、MIR 算法或可追溯的专用模型产生；LLM 只负责把证据解释为自然语言。措辞修订为：

> LLM 不创造音乐事实；DSP、MIR 算法或专用模型负责分析事实，LLM 只解释已有证据。

用户回复“是”，批准澄清后的架构。

### 迭代 2：播放需求推翻“分析后立即删除音频”

最初用户选择原始音频分析后立即删除、结果保留 24 小时。数据/API 设计后发现：刷新后的时间跳转和播放与立即删除冲突。

AI 提出三种方案：浏览器本地播放、服务端加密保留 24 小时、完全不播放。用户选择：

> B

规格因此修订为：原始音频按分析独立密钥加密，最多保留 24 小时；主动删除或到期时执行加密擦除。该变化同时影响数据模型、Range API、安全测试和隐私文案。

### 迭代 3：部署平台从 Fly.io 转向腾讯云

AI 基于预算最初推荐 Fly.io。用户追问大陆可用性和充值，随后明确：

> 我无法使用Fly.io，用别的办法解决这个问题

AI 调研并提出腾讯云香港 Lighthouse。用户一度提出：

> 服务器直接改用AutoDL吧

官方资料显示普通 AutoDL 实例没有独立公网 IP，个人用户不能开放公网自定义服务，且自定义服务协议不允许向第三方转发链接；这与课程公网 WebUI 冲突。用户最终决定：

> 那还是用腾讯云吧

部署规格修订为腾讯云 Lighthouse 中国香港、2 vCPU/4 GB、Docker Compose、Caddy、持久目录和仓库外 Secret 文件。用户选择购买低价域名用于 HTTPS。

### 迭代 4：把 Open Design 从“未安装”改为正式设计依赖

初版规格因当前 Skill 列表没有 Open Design 而如实写明未使用。用户在书面规格审阅阶段明确提出：

> SPEC中，课程推荐的open design可以安装使用，完整设计文档改为中文

课程文档中的链接确认目标仓库为 `nexu-io/open-design`。官方 OpenAI Skill 目录查询先返回 `HTTP 403`，但这不是正确来源；课程指定仓库的常规安装又因仓库体积在 120 秒后超时。随后使用安装器的稀疏 Git 模式，只安装 `skills/frontend-design`，命令成功并返回目标目录 `C:\Users\P\.codex\skills\frontend-design`。

设计系统从 Open Design 目录中选择与既有“温暖共鸣”最一致的 `Warm Editorial`，并新增项目级 `DESIGN.md`。完整设计文档改为中文；`SPEC.md` 与 ADR-007 同步记录设计系统、Skill、来源提交和非运行时依赖边界。

## 5. 分节设计确认

用户依次明确批准：

1. 系统架构与数据流；
2. 功能范围与模块边界；
3. 数据模型与 API 边界；
4. UI/UX 与核心交互；
5. 安全、隐私与凭据威胁模型；
6. 修订后的测试、CI、腾讯云部署与交付设计。

最后用户回复“是”，授权生成 `SPEC.md` 和 Superpowers 设计文档。该授权仅覆盖书面规格，不等于批准实现，也不等于 `HUMAN_APPROVAL.md`。

书面审阅期间，用户提出 Open Design 与中文化修订；修订后仍需重新确认书面规格。

## 6. Visual Companion 记录

用户明确同意打开视觉伴侣。浏览器中展示了：

- 三种核心工作区布局；用户终端回复和浏览器事件均选择 `a-guided-canvas`。
- 三种视觉风格；用户终端回复和浏览器事件均选择 `a-warm-resonance`。
- 系统架构与数据流图；用户在终端对澄清后的边界给出批准。

视觉伴侣文件保存在本地 `.superpowers/`，并由 `.gitignore` 排除，不作为产品源码或伪造的最终 UI。

## 7. Brainstorming 的客观观察

- 一次只提出一个关键问题，使用户连续作出真实选择。
- 可视化帮助确认布局和视觉风格；技术边界问题仍在终端文字中处理。
- 用户对“LLM 不产生事实”的质询暴露了措辞歧义。
- 播放与立即删除的冲突是在数据模型设计后暴露的，证明分节审查改变了实际规格。
- 部署平台经历两次真实修订，没有把不可用平台留在最终方案中。

## 8. Cold-Start Validation

尚未执行。课程要求在 `SPEC.md` 与 `PLAN.md` 均通过书面审阅后，由与 Codex 不同类型的全新 Agent 仅凭规格、计划和必要代码尝试 1–2 个任务。执行结果、问题、误解和修订必须在此处追加真实证据。

## 9. 书面 SPEC 批准

时间：2026-08-08T04:30:12+08:00

在 Open Design 与完整中文设计文档修订提交后，用户原话确认：

> 好，批准书面SPEC，进行下一步

该批准仅表示 `SPEC.md` 与配套设计文档通过书面审阅，授权进入 `PLAN.md` 阶段；它不等于批准实施，不触发 `HUMAN_APPROVAL.md`。计划仍需单独审阅，随后还需真实 cold-start 验证和最终人工实施确认。

## 10. 书面 PLAN 批准与 cold-start 准备

时间：2026-08-08T04:49:31+08:00

用户在审阅门禁中原话确认：

> 批准 PLAN

该批准授权进入不同类型 Agent 的 cold-start 规约验证，仍不等于正式实施授权，也不触发 `HUMAN_APPROVAL.md`。

环境检测发现 OpenCode `1.17.14` 已安装，可作为与 Codex 不同类型的 Agent。真实检测过程为：

1. npm PowerShell `.ps1` shim 被本机执行策略拒绝；
2. 沙箱内 `.cmd` shim 因无法访问用户配置目录报告 `EEXIST`；
3. 用户会话中 `.cmd` shim 成功运行，显示 `0 credentials`，但模型列表仍提供 `opencode/deepseek-v4-flash-free`、`opencode/north-mini-code-free` 等 6 个 OpenCode 免费模型。

尚未启动 cold-start session；查看 `opencode run --help` 时外部审批通道断开并拒绝命令，因此等待用户针对运行 OpenCode cold-start 的明确批准后继续。未伪造 Agent 输出或测试结果。

用户随后原话批准“批准运行 OpenCode cold-start 并推送记录”。主 Agent 已创建 `validation/opencode-cold-start` 分支及 `.worktrees/opencode-cold-start` 隔离 worktree，并用 sparse checkout 将可见的既有文件限制为 `SPEC.md`、`PLAN.md`、`.gitignore`。实际启动 `opencode/deepseek-v4-flash-free` 新会话时，外部审批器因连接中断再次拒绝命令；OpenCode 进程没有启动，未产生 Agent 输出、实现或测试证据。由于第三方模型调用会传输规格、计划、生成代码和测试输出并可在隔离区运行命令，需在披露该边界后取得用户再次明确授权。
