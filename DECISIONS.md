# MuseEcho Architecture Decisions

## ADR-001：CPU 优先的可解释分析基线

**Context**
V1 必须真实分析任意合法上传，而不是复用演示数据；部署预算和课程周期有限。

**Options**
1. CPU DSP/MIR 基线；2. 重型预训练模型；3. 限定单一曲风。

**Decision**
采用 CPU 优先的 DSP/MIR 基线。和弦与结构为 best-effort，必须携带置信度；低置信度为 unknown。

**Reason**
用户选择 A；该方案最容易在 2 vCPU 环境中测试、容器化和解释。

**Consequences**
复杂和声和曲式的结果可能稀疏；V1 不做分轨和乐器识别。

## ADR-002：模块化单体

**Context**
产品需要富交互前端、Python 音频生态、异步任务和低复杂度部署。

**Options**
1. React/Vite + FastAPI 模块化单体；2. Next.js + FastAPI 双服务；3. HTMX 单体；4. Redis Worker 分布式架构。

**Decision**
React/Vite/TypeScript 前端由 FastAPI 同一应用镜像托管；分析使用受限进程池，单实例并发 1。

**Reason**
用户分别选择前端/后端方案 A、任务模型 A，并最终确认整体方案 A。

**Consequences**
部署与测试简单，但不支持水平扩展；未来通过 repository 和 analysis interfaces 拆分。

## ADR-003：Evidence First 的 LLM 边界

**Context**
通用 LLM 无法可靠、可复现地从原始音频生成时间对齐的音乐事实。

**Options**
1. LLM 生成分析；2. LLM 解释结构化证据；3. 完全无 LLM。

**Decision**
DSP、MIR 或可追溯专用模型生成事实；确定性乐理引擎计算理论；LLM 只解释白名单证据。

**Reason**
符合产品 Evidence First 原则。用户质询措辞后批准澄清后的边界。

**Consequences**
需要版本化 Evidence schema 和 fallback；LLM 输出不能回写事实表。

## ADR-004：无登录、能力令牌访问

**Context**
V1 需要公网体验，但账户体系属于范围膨胀。

**Options**
1. 无登录短期访问；2. 单用户库；3. 多用户账户。

**Decision**
使用不可猜测 Analysis ID + 独立访问令牌，令牌哈希入库并通过 HttpOnly Cookie 使用。

**Reason**
用户选择 A；兼顾刷新恢复和范围控制。

**Consequences**
Cookie 丢失后无法恢复结果；不提供分享和长期历史。

## ADR-005：加密保留音频 24 小时

**Context**
最初决定分析后立即删除音频，但刷新后播放与时间跳转需要服务端音频。

**Options**
1. 浏览器本地播放；2. 服务端加密保留 24 小时；3. 不播放。

**Decision**
采用独立数据密钥的分块 AEAD，加密音频与结果保留最多 24 小时；删除时执行加密擦除。

**Reason**
用户在冲突被明确指出后选择 B。

**Consequences**
增加 Range 解密、安全测试和密钥生命周期复杂度；换取刷新后完整播放器体验。

## ADR-006：Secret 由部署者本地管理

**Context**
课程要求 Key 安全录入、状态、更新和清除；公网无登录管理页会扩大攻击面。

**Options**
1. 本地 CLI；2. Web 管理页；3. `.env` only。

**Decision**
提供本地 CLI。原生使用系统凭据库，Docker 使用仓库外只读 Secret 文件。

**Reason**
用户选择 A；避免新增管理员账户和远程 Secret API。

**Consequences**
部署者需要服务器或本地终端权限；Key 变更属于运维操作。

## ADR-007：Open Design 引导式单画布与温暖编辑视觉

**Context**
原始设计强调从 DNA 到结构、和弦和追问的连续体验，不能做成后台管理系统。

**Options**
布局：引导式单画布、三栏工作台、故事式步骤。视觉：温暖共鸣、深色录音室、清晰分析仪。设计工具：自定义 tokens、Open Design 或不设品牌契约。

**Decision**
采用引导式单画布；使用 Open Design `Warm Editorial` 设计系统与 `frontend-design` Skill，并在根目录 `DESIGN.md` 中记录 MuseEcho 的项目级改编。

**Reason**
用户终端选择与视觉伴侣点击记录一致；随后用户明确要求 Open Design 可以安装使用。`Warm Editorial` 的暖纸色、陶土色、森林绿、编辑型字体和克制层级与既有方向一致。

**Consequences**
移动端纵向重排；专业密集信息需要逐级展开。实现必须遵守 `DESIGN.md` 语义 tokens、真实状态、可访问性和反通用 AI 风格要求。

## ADR-008：腾讯云香港作为最终部署目标

**Context**
用户无法使用 Fly.io；AutoDL 普通个人实例不适合第三方可访问的课程 WebUI。

**Options**
1. Fly.io；2. AutoDL；3. 腾讯云 Lighthouse 香港；4. 自有 VPS。

**Decision**
腾讯云 Lighthouse 中国香港 2 vCPU/4 GB，购买低价域名，Caddy HTTPS，Docker Compose 部署。

**Reason**
用户明确排除 Fly.io，最终选择腾讯云；腾讯云中国站付款可用且预算约 90 元/月。

**Consequences**
无需大陆 ICP 备案，但跨境上传质量需三网实测；云账户、域名和付款仍是 human-owned 授权步骤。

## ADR-009：接受 corrected cold-start 作为 Tasks 1–2 实施基线

**Context**
OpenCode 的原始 cold-start 成功暴露了规约缺口，但其首版代码未通过主 Agent 审查。Codex 随后以测试驱动方式修正全部 Critical/Important 问题，并完成三轮独立复审。

**Options**
1. 仅保留 cold-start 为证据、从头重做 Tasks 1–2；2. 接受经修正与复审的实现；3. 放弃 cold-start 产物。

**Decision**
采用选项 2。用户明确要求把 `validation/opencode-cold-start` 合并到 `main`，合并提交为 `a2d7af5`；后续从任务 3 开始。

**Reason**
修正提交 `07d135e` 已满足 PLAN 对 Tasks 1–2 的增强合同，合并前后均有最新验证，独立复审无剩余 Critical、Important 或 Minor。重新实现只会伪造或重复已经真实完成的 RED→GREEN 历史。

**Consequences**
保留原始失败和直接合并（无 PR）的真实记录；Tasks 3–24 必须恢复独立分支、PR、TDD、规格审查和代码质量审查，不得把 Tasks 1–2 的证据外推为完整产品完成。

## ADR-010：Engineering Audit 使用固定 finding/evidence 合约与 compact security manifest

**Context**
Task 23 必须允许人工阅读审计，同时拒绝通过删除 finding、降低 severity、重写 scan 命令或仅声称文件存在来清零。完整 Trivy raw、tar 和 DB 体积较大，且正式 Dockerfile 依赖层在本机离线 cache 中不可用。

**Options**
1. 只提交 Markdown 结论；2. 跟踪全部 raw/tar/DB；3. 固定 audit schema、finding/evidence 命令和 deterministic compact manifest，同时保留 ignored 原始证据用于本轮复核。

**Decision**
采用选项 3。Checker 固定 15 域、9 finding、34 evidence ID，解析 compact manifest 的 normalized SHA-256，并交叉当前 vulnerability policy/runtime boundary。Manifest 固定 Trivy image/DB、current audit image、tar/config、raw/package/inventory/VEX/tuple digest、181/67 severity 统计与所有 gate exit。正式 Dockerfile build 失败和受控 current-source 派生身份均作为边界事实记录，派生镜像禁止被描述或推广为 release artifact。

**Reason**
该方案能在小型 tracked 证据中阻止 audit-only 虚假改写，又不会把 366MB tar、1.2GB DB 或 1.8MB raw 混入仓库；逐 CVE statement、raw tuple 与当前 source/policy 的真实复核仍在本轮离线链中完成。

**Consequences**
任何 source、policy、scanner DB、image/tar/config、raw tuple 或 VEX 变化都必须重新运行安全链并更新固定 manifest/checker。Compact manifest 不能替代 retained raw 的取证价值；正式发布仍需在具有完整 locked cache 的环境执行 Dockerfile build 和远程 CI。

## ADR-011: Review evidence is identity-bound and current-only

**Context**
The first Task 23 audit could be made internally coherent by replacing a
finding's RED/GREEN commands with unrelated commands. Its no-build path also
trusted any local SHA identity, and the Functional audit still described a
Task 22 frontend build as current although it was not run in Task 23.

**Decision**
Each FIXED finding uses an exact per-finding evidence contract; E020-E025 and
the complete compact security manifest are fixed and current runtime boundary
is rebuilt by the real policy builder. No-build requires distinct trusted
app/gateway daemon and config identities, verifies Compose configuration and
both running containers after both starts, and uses `--no-build` every time.
Unrun frontend type/build evidence is `EXTERNAL_NOT_RUN`, yielding the current
matrix `28 PASS / 12 PARTIAL / 0 FAIL`.

**Consequences**
Coherent audit-only mutations fail. A source, image, raw, VEX, policy,
inventory, release, DB, or tool identity change requires fresh offline
evidence. Historical green output cannot make a current acceptance item pass.
