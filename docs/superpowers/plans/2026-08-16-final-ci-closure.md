# 最终 CI 闭环实施计划

> **供自主执行者使用：** 必需子技能：使用 superpowers:executing-plans 逐项实施本计划。步骤使用复选框（`- [ ]`）语法跟踪。

**目标：** 安全整合有意保留的课程交付文档、更新其失败关闭契约、刷新当前源代码安全边界、修复 Ruff 失败、推送现有 PR 分支，并为最终分支 SHA 获得 GREEN GitHub CI 结果。

**架构：** 保持 `7f8412b` 的产品行为不变。将工作分为三个可复审单元：课程/过程文档及其验证器契约、当前源代码安全边界同步，以及 GitHub Actions 报告的精确格式化修复；推送前先在本地验证，并以实时 PR 检查作为最终权威。

**技术栈：** Git、GitHub Actions/CLI、Markdown、Python 3.12、uv、Ruff、mypy、pytest、Node.js/npm、Vitest、Playwright、Docker/OCI CI。

## 全局约束

- 保留所有用户拥有的变更，只暂存本任务已复审的文件；绝不盲目使用 `git add -A`。
- 如实记录学生报告的规则：列出的 9 项交付物中至少完成 6 项才算通过；不得声称其余 3 项已完成。
- 不重写学生反思，也不声称已完成仅限学生执行的验收工作。
- 保留当前 PR #3 失败日志和最近成功的分支/main 证据，只清理可重新生成的 Actions 制品/缓存。
- 仓库工作期间不得触碰 `D:\智软工程师大项目\MuseEcho` 之外的文件。
- 完成条件包括全新的本地验证，以及最终推送 SHA 上 `quality`、`e2e` 和 `distribution` 全部成功。

---

### 任务 1：对账课程与维护记录

**文件：**
- 修改：`COURSE_REQUIREMENT_UPDATE.md`
- 修改：`COURSE_DELIVERY_CHECKLIST.md`
- 修改：`PLAN.md`
- 修改：`AGENT_LOG.md`
- 如内容真实则复审并保留：`README.md`、`SPEC.md`、`BLOCKERS.md`、`DELIVERY_REPORT.md`、`DEPLOYMENT_EVIDENCE.md`、`REFLECTION.md`、`REFLECTION_NOTES.md`
- 确认已被取代时删除：`TASK20_HANDOFF.md`
- 修改：`tests/unit/test_delivery_report.py`
- 修改：`scripts/check_delivery_report.py`

**接口：**
- 输入：学生提供的教师要求和现有任务 24+ 仓库历史。
- 输出：9 项交付物、报告的 6/9 通过门槛，以及音频格式/播放器/节奏工作的维护来源的真实映射。

- [ ] **步骤 1：复审每项已跟踪和未跟踪文档差异**

运行：`git status --short && git diff --check && git diff -- <each changed path>`

预期：只有有意的课程状态、音频支持和已被取代的交接变更；没有空白字符错误。

- [ ] **步骤 2：补充缺失的教师规则和维护来源事实**

记录学生报告的最低要求为 9 项中完成 6 项，同时保留逐项真实状态，不把延期项标记为完成。向 `PLAN.md` 和 `AGENT_LOG.md` 增加实际任务 24+ 维护范围和验证状态。

- [ ] **步骤 3：编写并验证更新后的交付契约 RED 测试**

更新聚焦测试，使当前报告严格要求三个仍未关闭的课程阻塞项，要求 GitLab/云证据保持 `NOT_RUN` 但为 `DEFERRED`，允许学生撰写的反思草稿存在而不把学生验收清单视为完成，并拒绝回退到虚假完成声明。修改验证器前先运行聚焦测试。

修复验证器前的预期：聚焦失败证明旧的五阻塞项/空白反思契约。

- [ ] **步骤 4：实施并验证最小交付契约更新**

更新 `scripts/check_delivery_report.py` 以及新测试所需的精确 `DELIVERY_REPORT.md` 证据字段/标题。保留学生清单的预留项，并明确记录延期的外部工作尚未执行。运行 `tests/unit/test_delivery_report.py`、检查器 CLI 和 `git diff --check`。

预期：聚焦交付测试和检查器通过；虚假 READY、缺少开放阻塞项、虚假外部执行或虚假学生验收仍会以失败关闭。

- [ ] **步骤 5：提交已复审的文档单元**

只暂存已复审文档路径，检查 `git diff --cached` 后，将其作为一个课程/过程维护单元提交。

预期：提交不包含产品代码变更、凭据、生成的大宗数据或未经复审的文件。

### 任务 2：修复精确 CI 格式化失败

**文件：**
- 修改：`src/museecho/analysis/decode.py`
- 修改：`src/museecho/analysis/rhythm.py`
- 修改：`tests/api/test_analysis_api.py`

**接口：**
- 输入：GitHub Actions run `31813100956`，其 `quality` 作业只报告这三个 Ruff 格式违规。
- 输出：经过 Ruff 格式化的源代码，不改变行为或断言。

- [ ] **步骤 1：复现 RED 格式门禁**

运行：`uv run ruff format --check src tests`

修复前预期：退出码 1，且严格列出上述三个文件。

- [ ] **步骤 2：应用最小格式化修复**

运行：`uv run ruff format src/museecho/analysis/decode.py src/museecho/analysis/rhythm.py tests/api/test_analysis_api.py`

预期：恰好重新格式化三个文件。

- [ ] **步骤 3：重新运行聚焦门禁与静态门禁**

运行：`uv lock --check`、`uv run ruff format --check src tests`、`uv run ruff check .`、`uv run mypy src`，以及从已修改文件中选出的聚焦解码/节奏/API 测试。

预期：每条命令均以 0 退出。

- [ ] **步骤 4：提交仅格式化修复**

严格暂存 `src/museecho/analysis/decode.py`、`src/museecho/analysis/rhythm.py` 和 `tests/api/test_analysis_api.py`，检查 `git diff --cached`，然后提交 CI 格式化修复。

预期：提交只改变布局，不包含行为或断言变更。

### 任务 3：同步当前源代码安全边界

**文件：**
- 修改：`scripts/image-vulnerability-policy.json`
- 为保持不可变任务 23 可重算性，在需要时创建：`docs/audits/evidence/task23-image-vulnerability-policy.json`
- 仅在固定证据 schema 要求时修改：`docs/audits/evidence/task23-security-manifest.json`
- 仅在固定证据 schema 要求时修改：`scripts/check_engineering_audit.py`
- 修改：`tests/unit/test_image_vulnerability_audit.py` 和/或 `tests/unit/test_engineering_audit.py`
- 仅为澄清历史证据与当前源代码证据而修改：`docs/audits/ENGINEERING_AUDIT.md`；绝不把保留的历史扫描重新标记为当前扫描。

**接口：**
- 输入：现有失败的策略/运行时边界测试、格式化提交，以及五个源文件中的任务 24+ 运行时变更。
- 输出：运行时边界摘要与当前源代码匹配的策略，同时任务 23 保留的制品事实保持不可变且明确标记为历史。

- [ ] **步骤 1：捕获 RED 安全边界测试**

使用仓库内 pytest 基础临时目录，运行已提交策略边界测试和工程审计验证器测试。

修复前预期：当前源代码与策略边界不同；不得把历史清单验证悄悄重写为当前镜像证据。

- [ ] **步骤 2：增加狭窄的历史/当前边界回归测试**

编写最小测试，证明保留的任务 23 制品事实保持固定，而策略测试和最终 distribution 作业会独立检测当前源代码策略漂移。

预期：新测试因预期的旧耦合失败，而不是因夹具或临时目录错误失败。

- [ ] **步骤 3：只刷新当前源代码策略，并显式版本化历史验证**

在格式化修复后重新生成精确的当前运行时文件摘要。如果保留的任务 23 审计需要旧策略才能复现，则把该精确策略保存为名称清晰的历史快照，使历史检查器依据该快照验证/重算，但不声称它与当前源代码匹配。不要削弱 `image_vulnerability_audit.py` 为当前 distribution 构建强制执行的运行时边界相等性。

预期：当前策略与当前源代码匹配；保留的清单/tar/扫描事实保持不变并标记为历史。

- [ ] **步骤 4：验证并提交安全边界单元**

使用仓库内临时路径运行聚焦镜像漏洞和工程审计测试/检查器，然后检查并只提交已复审的安全策略、检查器、测试和审计文档路径。

预期：聚焦门禁通过，且没有虚假的当前镜像或正式 Release 声明。

### 任务 4：验证、发布并关闭 CI

**文件：**
- 验证并发布任务 1–3 的已复审提交；不引入无关产品变更。
- 如果推送前完整套件为 RED，则按需修改：`scripts/check_acceptance_matrix.py`、`tests/unit/test_acceptance_matrix.py`、`tests/unit/test_task20_final_delivery_contract.py`，以及它们验证的精确当前审计/过程记录。

**接口：**
- 输入：已复审的文档/契约、当前源代码安全边界及仅格式化源代码变更。
- 输出：`codex/expand-common-audio-formats` 上一个或多个有意提交、已推送的 PR #3，以及一个 GREEN 最终 SHA。

- [ ] **步骤 1：运行与 CI 风险相称的完整本地验证**

运行仓库记录的验证命令，包括后端测试、前端类型/测试/构建、E2E 或其仓库封装、Secret 扫描，以及本地环境可用的 distribution/容器契约门禁。

预期：所有可运行门禁均以 0 退出；任何纯环境限制均记录而不隐藏。

- [x] **步骤 2：以 TDD 关闭非环境完整套件契约漂移**

将缺少 ffmpeg/ffprobe 和 Docker 暂停导致的失败与确定性仓库失败分离。对于确定性失败，先捕获聚焦 RED 测试，然后以最小改动更新当前仅 GitHub 课程契约和历史证据查找，使历史提交证据绝不与可变当前文件比较。用持久的当前记录替换已废弃的 `TASK20_HANDOFF.md` 过程文档依赖；不要仅为满足测试而恢复过时状态文案。

预期：聚焦验收矩阵和过程文档测试通过，同时历史证据保持提交绑定，当前课程要求保持仅 GitHub。

本地已完成：聚焦 RED（`5 failed, 1 passed`）和确定性 GREEN（`51 passed`）。E004 绑定精确提交 `1047ce242884b6ba83a525524e88dcc44ab76a69`、tree `835981d848f42b1dfda147d25aed606c4d249f35` 和历史边界摘要；已删除的任务 20 暂停交接文档由持久当前记录替代。

- [ ] **步骤 3：复审已完成的提交范围**

运行 `git diff --check`，检查已复审的任务 1–4 提交范围，并确认任何剩余工作区路径都是有意且已明确识别的。

预期：提交不包含凭据、生成的大宗数据或无关文件；工作树没有无法解释的变更。

- [ ] **步骤 4：推送并监控 PR #3**

运行 `git push origin codex/expand-common-audio-formats`，然后使用 `gh pr checks 3 --watch --repo Zzz148080/MuseEcho`；任何作业失败时，先检查其日志再进行新修复。

预期：同一最终 head SHA 上的 `quality`、`e2e` 和 `distribution` 全部通过。

- [ ] **步骤 5：执行全新完成度审计**

运行：比较本地 `HEAD`、`origin/codex/expand-common-audio-formats`、PR head SHA 和成功工作流 head SHA；运行 `git status --short --branch`。

预期：所有 SHA 值一致，GitHub CI 为 GREEN；任何剩余工作树文件均明确识别，而不是被悄悄遗漏。

### 任务 5：关闭最终 distribution 漂移

**文件：**
- 修改：`scripts/image-vulnerability-policy.json`
- 修改：`scripts/image_vulnerability_audit.py`
- 修改：`.github/workflows/ci.yml`
- 修改：`tests/unit/test_image_vulnerability_audit.py`
- 修改：`tests/unit/test_task20_final_delivery_contract.py`
- 不修改：`docs/audits/evidence/task23-image-vulnerability-policy.json`

**接口：**
- 输入：GitHub Actions run `31962866791`；其 `distribution` 作业发现一个新的 Debian cJSON 发现项、过时的当前源代码控制行引用，以及 GitHub 制品配额上传失败。
- 输出：精确的当前镜像 VEX 清单、当前控制引用，以及一个仅证据保留为非阻断、同时每项镜像审计和漏洞门禁仍以失败关闭的工作流。

- [ ] **步骤 1：为当前策略/控制漂移及上传隔离捕获聚焦 RED 测试**

增加聚焦测试：要求当前上传控制为 `src/museecho/application/uploads.py:466` 和 `src/museecho/application/uploads.py:483`；拒绝当前策略和审计常量中过时的 `:464`/`:481` 组合；要求证据保留步骤同时使用 `if: always()` 和 `continue-on-error: true`；并证明之前每个构建/许可证/原始扫描/VEX/网关强制步骤都不使用 `continue-on-error: true`。

实施前预期：聚焦测试因过时控制和阻断性制品上传而失败，同时现有安全门禁仍保持严格。

- [ ] **步骤 2：增加精确的新 cJSON 发现项且不削弱策略**

将当前策略计数更新为 `finding_count=182` 和 `distinct_cve_count=68`。严格增加一条 `CVE-2026-29036` 声明：`libcjson1` 版本 `1.7.15-1+deb12u4`，状态 `affected`，严重性 `HIGH`，修复版本为空，purl 为 `pkg:deb/debian/libcjson1@1.7.15-1%2Bdeb12u4?arch=amd64&distro=debian-12.15`。评估必须指出易受攻击的 `cJSON_Utils.c` JSON Patch 函数，并根据精确软件包清单和 MuseEcho 执行边界解释为何这些函数不存在/未执行；不得复制与此无关的 `CVE-2026-67216` 的 `cJSON_Compare` 描述。

预期：声明中的 CVE 与原始扫描 CVE 严格一致；没有发现项被悄悄忽略。

- [ ] **步骤 3：只刷新当前控制并隔离配额失败**

将 `AUDIO_BOUNDARY_CONTROLS` 和所有当前策略声明控制从 `uploads.py:464`/`:481` 更新为 `uploads.py:466`/`:483`。不要修改不可变任务 23 快照。仅为 `Retain image vulnerability evidence` 设置 `continue-on-error: true`；原始扫描、许可证审计、精确 VEX 审计、Release identity 检查和最终强制门禁继续阻断。

预期：精确的当前控制存在，历史快照逐字节不变；GitHub 制品存储配额延迟不会让原本成功的 Release 安全作业变为 RED。

- [ ] **步骤 4：验证、复审、提交、推送并监控**

运行聚焦镜像漏洞/工作流契约测试、针对保留的当前扫描夹具或全新生成等效物的审计 CLI、已修改 Python 文件的 Ruff，以及相关 distribution 契约套件。复审并只提交预期路径，推送现有分支，然后监控同一 SHA 上的 `quality`、`e2e` 和 `distribution`。

预期：所有聚焦本地门禁通过，且三个 GitHub 作业在同一最终 head SHA 上成功。

### 任务 6：对账最终交付记录并移除已确认的本地中间产物

**文件：**
- 复审每份已跟踪交付/过程文档及其验证器契约。
- 只修改 CI 状态、阶段措辞或进度事实已过时的文档。
- 删除任何已忽略/未跟踪的仓库内临时文件前，先完成清点。

**接口：**
- 输入：最终成功的 GitHub Actions run 和完整分支历史。
- 输出：真实的最终交付记录，以及不含已确认任务本地一次性中间产物的仓库。

- [ ] **步骤 1：依据最终证据审计所有交付文档**

同步已完成工作、最终分支 SHA、PR 和工作流证据。保留教师报告的 6/9 门槛、所有真正延期的项目、当前 GitHub 必需/GitLab 补充措辞，以及学生拥有的反思/验收边界。

- [ ] **步骤 2：替换过时阶段措辞，不捏造完成状态**

只有最终证据已取代旧状态时，才移除或更新“等待 CI”“计划验证”或“Release 前”等措辞。不得声称已完成 GitLab、云部署、Release 发布或仅限学生执行的验收。

- [ ] **步骤 3：清点并安全清理仓库内中间产物**

列出每个候选项的解析后路径和来源。只删除经证明可重新生成且位于 `D:\智软工程师大项目\MuseEcho` 下的本任务产物；不得使用宽泛递归清理，也不得触碰 D 盘其他位置。

- [ ] **步骤 4：验证并发布对账变更**

运行文档/验收/审计验证器，检查最终差异，提交并推送任何真实文档变更，然后要求最终 SHA CI 为 GREEN，并重复本地/origin/PR/工作流 SHA 相等性审计。
