# MuseEcho V1 产品与工程规格

状态：用户已批准书面规格；当前进入 PLAN 审阅门禁，尚未批准正式实现

日期：2026-08-08

项目类型：AI4SE B 类非 harness Web 应用

## 1. 问题陈述

多数音乐产品能告诉用户正在播放什么，却不能帮助没有系统乐理背景的用户理解一段音乐发生了什么、为什么会产生特定听感。专业制作与分析工具又常以演奏、制作或研究者为目标，学习门槛较高。

MuseEcho V1 面向普通音乐爱好者、乐器初学者和轻度创作者，将真实音频分析转化为可交互的音乐结构、和声与动态证据，再用确定性乐理规则和可选 LLM 解释这些证据。核心原则是 Evidence First：LLM 不创造音乐事实，只解释 DSP、音乐信息检索算法或专用模型已经产出的结构化证据。

## 2. 目标用户

1. 希望理解喜欢歌曲结构和听感来源的普通音乐爱好者。
2. 正在学习和弦、调性和曲式的钢琴、吉他等乐器初学者。
3. 需要快速观察参考曲目结构、能量与和声走向的轻度创作者。
4. 需要审查项目工程过程、测试与交付证据的课程教师或助教。

## 3. V1 目标与成功定义

V1 必须形成以下闭环：

```text
合法音频上传
→ 真实、带置信度的分析
→ Music DNA 总览
→ 同步结构地图
→ 和弦解构
→ 选定片段的 Evidence Q&A
→ 主动删除或 24 小时自动清理
```

只有所有 Definition of Done 条件经最新证据验证后，项目才能声明 `MUSEECHO V1 READY`。否则必须准确声明 `MUSEECHO V1 PARTIALLY READY` 并列明原因。

## 4. 用户故事

### US-01 上传并分析

作为拥有合法音频使用权的用户，我希望上传 WAV 或 MP3 并看到真实分析进度，以便知道系统正在处理什么以及何时可以查看结果。

验收要点：文件限制和隐私规则在上传前可见；失败原因可理解；任务可在刷新后恢复。

### US-02 查看 Music DNA

作为音乐爱好者，我希望查看来自真实分析的调性、速度、节拍、能量、和声和结构摘要，以便快速形成对整首音乐的认识。

验收要点：每项事实有来源和置信度；低置信度信息明确标记为 `unknown`。

### US-03 探索同步结构地图

作为乐器初学者，我希望在统一时间轴上操作波形、段落、和弦和能量曲线，以便观察不同音乐事件如何同时发生。

验收要点：点击、拖动播放头和选择片段时，各轨道与播放器同步。

### US-04 学习和弦

作为初学者，我希望点击一个和弦后看到组成音、音程、性质、调内级数和可能功能，以便理解它在当前语境中的意义。

验收要点：基础乐理事实由确定性引擎计算，并具有可复现单元测试。

### US-05 追问片段

作为用户，我希望针对选定时间片段提问，并看到引用真实证据的通俗解释，以便理解听感而不被虚构事实误导。

验收要点：回答列出证据；无 LLM Key 或调用失败时仍能返回确定性解释。

### US-06 管理隐私

作为上传者，我希望知道音频何时到期并能立即删除，以便控制自己的数据。

验收要点：界面显示剩余保留时间；删除后访问立即失效；加密密钥和密文被清理。

### US-07 安全配置 LLM

作为部署者，我希望通过本地 CLI 设置、查看状态、更新和清除 API Key，以便不把凭据暴露在代码、前端或日志中。

验收要点：状态不回显明文；原生运行使用系统凭据库；容器部署使用仓库外 Secret 文件。

## 5. V1 功能模块

### 5.1 音频上传与任务管理

输入：单个 WAV 或 MP3 文件。

限制：最多 30 MB、10 分钟。

行为：流式接收、文件签名校验、真实解码校验、随机内部命名、创建异步任务、显示实际阶段状态。

输出：不可猜测的任务 ID、HttpOnly 访问 Cookie、任务状态和真实阶段进度。

任务阶段固定为：`queued`、`validating`、`decoding`、`rhythm`、`tonality`、`structure`、`chords`、`evidence`、`complete`，以及终态 `failed`、`deleted`、`expired`。进度来自阶段完成情况，不伪造连续增长。

单实例只运行一个 CPU 分析任务，其余任务按创建时间排队。应用重启时，未完成任务转为可安全重试状态，不假装已完成。

### 5.2 真实音频分析

基线管线采用 CPU 优先、可解释、可测试的 DSP/MIR 方法：

1. FFmpeg 解码为受控 PCM，并验证时长、通道、采样率和可解码性。
2. 生成用于 UI 的降采样波形桶。
3. 使用节拍和 onset 特征估计 BPM 与 beat positions。
4. 使用 RMS 生成能量时间序列和显著变化事件。
5. 使用 chroma 特征与调性模板估计 key/mode。
6. 使用 recurrence/self-similarity 与 novelty/聚类方法生成结构候选边界。
7. 使用大/小三和弦模板、序列平滑和稳定性评分生成和弦事件。
8. 将所有结果映射到同一秒级时间轴，并附算法来源和置信度。

V1 不承诺对所有曲风可靠识别和弦或结构。高置信度正常显示，中置信度显示谨慎标记，低置信度输出 `unknown` 且不进入 LLM 的事实输入。

### 5.3 Music DNA

展示：时长、调性/调式、BPM、可可靠获得的节拍、整体能量摘要、和声摘要、结构摘要及音乐指纹式可视化。

情绪、风格、核心乐器、领奏乐器等无法由当前管线可靠确定的字段不伪造、不用固定数据填充。页面明确区分 `real`、`demo`、`synthetic_test` 三种数据来源。

### 5.4 同步结构地图

结构地图至少包含：

- waveform；
- section timeline；
- chord timeline；
- energy curve；
- 重要音乐事件；
- 播放头与片段选择。

播放器、时间点、拖选片段和所有轨道共享同一时间坐标。点击和弦会跳转到事件起点并打开详情；拖选片段会限定 Evidence Q&A 的证据窗口。

### 5.5 和弦解构与音乐理论引擎

输入：和弦符号、当前 key/mode、前后和弦与时间语境。

输出：组成音、音程、和弦性质、可能的调内级数、可能的调内功能和明确的不确定性说明。

该模块以纯函数和不可变值对象为核心，不调用 LLM。无法唯一判断的 enharmonic spelling 或功能必须返回候选及理由，而非单一伪确定答案。

### 5.6 Evidence-Grounded Explanation

输入：用户问题、选定时间片段、达到置信度门槛的 Evidence ID 及其结构化内容。

行为：先构造受限证据包，再调用可选 LLM 适配器；超时、缺 Key、供应商错误或输出校验失败时使用确定性模板。

输出：通俗解释、引用证据列表、解释模式 `llm` 或 `fallback`。

LLM 不得创建或修改 chord、timestamp、instrument、modulation、structure、key、energy change 等事实。专用 MIR 模型可以参与事实分析，但其结果必须结构化、可追溯并带置信度。

### 5.7 数据生命周期与删除

原始音频在服务端加密保存最多 24 小时，以支持刷新后的播放、跳转和复查。结果和访问 Cookie 同期到期。用户可以提前删除全部数据。

每个音频使用独立数据密钥和分块 AEAD 加密，以支持受控 Range 播放。数据密钥由部署 Secret 中的主密钥封装。删除时先销毁封装密钥，再删除密文、结构化结果、解释和访问记录，实现加密擦除。

## 6. 输入、输出、边界与错误处理

| 场景 | 系统行为 | 用户可见结果 |
| --- | --- | --- |
| 扩展名或 MIME 伪造 | 按签名和解码结果拒绝 | “文件不是有效 WAV/MP3” |
| 文件超过 30 MB | 流式接收阶段终止 | 显示大小上限，不创建任务 |
| 时长超过 10 分钟 | 解码元数据后删除临时数据 | 显示时长上限 |
| 损坏音频 | 解码失败并清理 | 稳定错误码和重试建议 |
| 静音或极短音频 | 完成可获得的分析 | 标记证据不足，不伪造结果 |
| 调性/和弦/结构低置信度 | 写入 `unknown` | 显示解释和置信度状态 |
| 队列已满 | 不接收新任务 | 返回可重试的繁忙状态 |
| Worker 崩溃 | 任务转为失败或可重试 | 不显示完成结果 |
| 无 LLM Key | 跳过外部调用 | 使用 fallback 并提示增强解释不可用 |
| LLM 超时/错误 | 熔断并 fallback | 核心产品仍可使用 |
| 无效时间片段 | API 校验失败 | 指明合法范围 |
| Cookie 缺失或不匹配 | 拒绝读取 | 通用 404/403，不泄漏记录存在性 |
| 记录过期 | 清除密钥和数据 | 显示已过期并允许重新上传 |
| 网络中断 | 前端保持可恢复状态 | 重试状态查询，不重复提交上传 |

错误响应使用稳定错误码、用户消息和关联请求 ID。内部堆栈、路径、Secret、原始供应商错误和文件名不返回前端。

## 7. 非功能需求

### 7.1 性能

- 目标环境：2 vCPU、4 GB RAM、单分析并发。
- 5 分钟常规音频的分析目标为 90 秒内完成；最终以目标服务器实测为准。
- 前端只接收降采样波形和必要时间序列，不下载完整分析中间矩阵。
- 结构地图常规交互目标为 60 FPS；数据量过大时先聚合再绘制。
- 上传和播放支持背压与 Range 请求，不将 30 MB 上限以上内容读入内存。

### 7.2 可用性与可访问性

- 支持桌面、平板和移动宽度浏览器。
- 键盘可操作播放器、时间轴和和弦事件。
- 颜色不作为唯一信息编码；图表提供文本摘要。
- 焦点、语义标签和对比度满足 WCAG 2.1 AA 的适用要求。

### 7.3 可观测性

- 结构化日志包含请求 ID、任务 ID、阶段、耗时、错误码和资源摘要。
- 日志不包含 API Key、访问令牌、原始文件名、音频内容或完整问题正文。
- `/api/health` 区分进程存活与依赖就绪状态。
- 记录队列长度、任务耗时、失败计数、清理计数和 fallback 使用量。

### 7.4 可靠性

- SQLite 使用 WAL、事务和外键约束。
- 进程启动时恢复或终止不一致任务，并回收孤儿文件。
- 清理任务幂等；重复执行不会删除未到期或不属于目标任务的数据。
- 单 Machine 设计不宣称高可用；备份用于灾难恢复，不用于保留已按隐私规则删除的数据。

## 8. 安全与凭据威胁模型

### 8.1 访问控制

- Analysis ID 使用密码学安全随机值。
- 独立访问令牌只以哈希形式存储。
- 浏览器通过 `Secure`、`HttpOnly`、`SameSite=Strict` Cookie 访问结果；令牌不进入 URL 或 localStorage。
- 修改和删除请求校验 Origin，并使用 CSRF 防护。
- CORS 默认同源；生产环境强制 HTTPS 和安全响应头。

### 8.2 上传与资源治理

- 不信任扩展名、MIME、文件名或客户端时长。
- 随机内部命名，禁止路径穿越和用户控制的存储路径。
- 限制文件大小、时长、解码时间、队列长度、每 IP 频率和 LLM 超时。
- 分析运行在受限子进程；达到资源或时间限制时终止并清理。

### 8.3 Credential Threat Model

| 威胁 | 对策 |
| --- | --- |
| Git 泄漏 | `.gitignore`、`.env.example` 无真实值、提交前和 CI Secret 扫描 |
| 日志泄漏 | 统一脱敏过滤器；禁止记录请求头、Key、Cookie 和供应商原始载荷 |
| 前端 bundle 泄漏 | 所有长期 Key 只存在服务端；构建扫描敏感变量前缀 |
| 错误信息泄漏 | 稳定错误码替代内部异常；堆栈只进入受限服务端日志 |
| 部署环境泄漏 | Secret 文件位于仓库外、权限最小化、仅运行账户可读 |
| 测试数据泄漏 | 测试使用占位 Key 与合成音频；截图不包含真实凭据 |
| 运维人员误读 | `status` 只显示名称、来源和是否配置，不回显明文 |
| LLM 供应商泄漏 | 不发送原始音频、令牌、文件名或用户身份；仅发送最小证据包 |

本地 CLI 支持 `set`、`status`、`update`、`clear`。原生运行优先使用操作系统凭据库；Docker/腾讯云部署使用 `/etc/museecho/secrets` 下的只读 Secret 文件。应用不提供远程 Secret 管理 API。

### 8.4 音频隐私

- 音频按分析独立密钥加密；持久卷中不出现明文原始音频。
- Range 播放只解密请求所需块，并验证每块 AEAD 标签。
- LLM 永不接收音频字节。
- 到期和主动删除销毁数据密钥与密文；界面显示剩余时间。

## 9. 系统架构

MuseEcho 是模块化单体：

```text
Browser: React + Vite + TypeScript
        │ same-origin HTTPS
        ▼
Caddy reverse proxy
        ▼
FastAPI application
├─ REST API and static frontend
├─ upload/access/security services
├─ bounded analysis process pool (concurrency = 1)
├─ deterministic music-theory engine
├─ optional LLM adapter + deterministic fallback
├─ SQLite repositories
└─ expiry/orphan cleanup scheduler
        │
        ▼
/srv/museecho/data
├─ SQLite database
└─ encrypted audio chunks
```

边界原则：UI 不依赖分析实现细节；分析模块只输出版本化结构；乐理引擎不依赖 Web 或 LLM；LLM 适配器不能写入音乐事实；存储通过 repository 接口隔离，允许未来替换 SQLite。

## 10. 数据流

1. 浏览器上传文件；服务端流式校验并加密落盘。
2. API 写入 `AnalysisJob` 并返回 ID 与访问 Cookie。
3. Worker 解密受控数据流，按阶段产出特征与证据。
4. 结果写入事务；任务变为 `complete`。
5. 浏览器读取结果并构建统一时间轴。
6. 用户点击和弦时，前端显示已计算的理论结果。
7. 用户选择片段并提问；后端只选取时间相交且达到门槛的证据。
8. LLM 或 fallback 生成解释，并附 Evidence ID。
9. 用户删除或 24 小时到期；系统销毁密钥并级联删除记录与密文。

## 11. 数据模型

### AnalysisJob

`id`、`status`、`stage`、`progress`、`created_at`、`updated_at`、`expires_at`、`error_code`、`retry_count`、`pipeline_version`、`source_kind`。

### AccessGrant

`analysis_id`、`token_hash`、`created_at`、`expires_at`、`revoked_at`。

### EncryptedAudio

`analysis_id`、`cipher_path`、`wrapped_data_key`、`chunk_size`、`chunk_count`、`plaintext_size`、`media_type`、`sha256`。

### TrackAnalysis

`analysis_id`、`duration_seconds`、`sample_rate`、`channels`、`bpm`、`bpm_confidence`、`key_tonic`、`mode`、`key_confidence`、`time_signature`、`time_signature_confidence`、`summary_json`。

### SectionEvent

`id`、`analysis_id`、`start_seconds`、`end_seconds`、`label`、`confidence`、`algorithm`。

### ChordEvent

`id`、`analysis_id`、`start_seconds`、`end_seconds`、`symbol`、`confidence`、`algorithm`、`theory_json`。

### TimeSeries

`analysis_id`、`kind`、`resolution_seconds`、`points_json`、`algorithm`。

### Evidence

`id`、`analysis_id`、`kind`、`start_seconds`、`end_seconds`、`value_json`、`confidence`、`algorithm`、`eligible_for_llm`。

### Explanation

`id`、`analysis_id`、`segment_start`、`segment_end`、`question_digest`、`evidence_ids_json`、`mode`、`text`、`created_at`。

所有时间范围满足 `0 <= start < end <= duration`。所有真实、演示和测试数据通过 `source_kind` 强制区分。

## 12. API 设计

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/analyses` | 上传并创建任务 |
| GET | `/api/analyses/{id}/status` | 获取任务阶段和错误 |
| GET | `/api/analyses/{id}` | 获取结构化分析结果 |
| GET | `/api/analyses/{id}/audio` | 受控 Range 播放 |
| POST | `/api/analyses/{id}/explanations` | 对选定片段提问 |
| DELETE | `/api/analyses/{id}` | 删除音频、结果和访问授权 |
| GET | `/api/health` | 存活与就绪检查 |

上传接口成功只返回任务，不保持连接等待分析。Explanation API 对问题长度、片段长度、证据数量和调用频率设上限。删除接口幂等。

## 13. 技术选型及理由

| 领域 | 选择 | 理由 |
| --- | --- | --- |
| 前端 | React、Vite、TypeScript | 适合复杂同步交互、组件测试和静态构建 |
| 后端 | Python、FastAPI、Pydantic | 与科学计算生态兼容，类型化 API 清晰 |
| 音频 | FFmpeg、librosa、NumPy、SciPy | 成熟、CPU 可运行、算法可解释且易于合成测试 |
| 数据库 | SQLite | 单实例 V1 足够，事务与迁移成本低 |
| 加密 | `cryptography` 的 AEAD 原语 | 成熟实现，避免自行设计密码算法 |
| 前端测试 | Vitest、Testing Library | 快速组件与交互测试 |
| 后端测试 | pytest | 适配 Python 单元、集成与参数化测试 |
| E2E | Playwright | 真实浏览器、多视口和网络故障测试 |
| 容器 | Docker、Docker Compose | 一键分发，开发与部署一致 |
| 反向代理 | Caddy | 自动 HTTPS、配置小、适合单机部署 |

LLM 通过窄接口适配，首版只要求一个服务端可配置的 OpenAI-compatible provider；核心测试使用 stub，且产品在没有任何供应商 Key 时完整运行。

## 14. 前端设计系统

产品采用经过批准的“温暖共鸣·引导式单画布”方向，并正式绑定 Open Design：

- 设计系统：Open Design `Warm Editorial`；
- 实现 Skill：Open Design `frontend-design`；
- 暖纸色背景与近黑正文；
- 森林绿表示可用分析事实；
- 陶土色表示主要操作与当前重点；
- 琥珀色表示乐理知识；
- 克制圆角、清晰层级和较少装饰。

项目级品牌契约位于 `DESIGN.md`，其颜色、字体、布局、组件、状态、动效和可访问性规则是实现阶段的设计输入。建立语义 Design Tokens，不在组件中散落颜色和间距常量。页面顺序为上传/状态、播放器与 Music DNA、结构地图、和弦详情、Evidence Q&A、隐私删除。桌面横向组织关联信息，平板减少并排，手机纵向重排并保持播放器易达。

`frontend-design` 已从课程指定的 `nexu-io/open-design` 仓库安装到本地 Codex Skills；选型与复核基于仓库提交 `f580271`。实现时以 `DESIGN.md` 和产品原始设计为品牌约束，以该 Skill 的真实状态、响应式、可访问性和反通用 AI 风格检查为工艺补充。Open Design 桌面应用与云服务不是 V1 运行依赖。

## 15. 外部依赖

- FFmpeg 可执行程序；
- Python 音频与科学计算库；
- 浏览器 Web Audio/HTMLMediaElement；
- 可选 LLM API；
- Docker 与 Docker Compose；
- Open Design `Warm Editorial` 与 `frontend-design`（仅设计/实现阶段使用，不是产品运行时依赖）；
- 腾讯云 Lighthouse、域名/DNS 和 HTTPS 证书服务；
- GitHub 与 NJU Git/GitLab（以实际凭据和 remote 为准）。

所有第三方依赖必须锁定版本、审查许可证并记录到 README。不得提交商业版权音乐。

## 16. 分发方案

提供多阶段 Dockerfile 和 Docker Compose：

1. Node 阶段构建前端。
2. Python 阶段安装锁定的运行依赖和 FFmpeg。
3. 生产镜像复制前端产物，以非 root 用户运行 FastAPI。
4. Compose 挂载 `/data` 和只读 Secret 文件，并启动 Caddy。

陌生用户按 README 配置 Secret 后，应能用少量命令完成 build、启动、健康检查和停止。`.env` 只作为明确标注风险的开发来源，生产不依赖仓库内 `.env`。

## 17. 部署方案

最终目标为腾讯云 Lighthouse 中国香港地域：Linux、2 vCPU、4 GB RAM、约 70 GB SSD、30 Mbps 套餐。用户已选择购买低价域名并解析到公网 IP。

部署要求：

- Caddy 负责 HTTPS 与反向代理；
- 仅开放 22、80、443；
- SSH 使用密钥认证并关闭密码登录；
- 应用数据位于 `/srv/museecho/data`；
- Secret 位于 `/etc/museecho/secrets`，不进入仓库；
- 提供部署、健康检查、备份和回滚脚本；
- 上线后执行真实上传、分析、播放、问答、删除 smoke test；
- 尽可能从不同大陆运营商测试 30 MB 以内上传。

AutoDL 只适合作为可选私有算力环境，不作为最终 WebUI 托管。Fly.io 已因用户无法使用而排除。

## 18. 测试策略

所有适合测试的功能严格执行 RED → GREEN → REFACTOR，并保留真实命令证据。

### 后端单元测试

- 乐理引擎与 enharmonic 边界；
- 置信度门槛；
- 任务状态机；
- 访问令牌哈希与授权；
- 分块加密、Range 解密和密钥销毁；
- 过期清理与孤儿恢复；
- LLM 证据白名单和 fallback。

### 音频集成测试

程序生成单音、大小三和弦、节拍器、简单和弦进行、静音、极短和损坏音频。验证时长、BPM、能量、chroma、调性、和弦事件、结构输出及低置信度路径。

### 前端测试

覆盖上传校验、真实阶段状态、Music DNA、时间轴同步、键盘操作、和弦详情、证据引用、低置信度、过期和网络错误。

### E2E

使用 Playwright 完成上传 → 分析 → Music DNA → 结构地图 → 播放/拖选 → 和弦 → fallback Q&A → 删除，并检查浏览器 console、网络失败与桌面/平板/移动视口。

### CI

GitHub Actions 运行 backend tests、frontend tests、integration tests、lint、typecheck、production build、E2E、Secret scan 和 Docker build。`.gitlab-ci.yml` 提供核心等价流程并包含名为 `unit-test` 的 job。

## 19. 客观验收标准

### AC-A 上传与分析

- 有效 WAV/MP3 创建真实任务并运行分析。
- 超限、损坏、静音和极短文件走规定路径。
- 任意非 demo 上传都不出现固定演示数据。
- 5 分钟基准音频在目标服务器的实测结果被记录；超过 90 秒不得标记该性能项通过。

### AC-B Music DNA

- 页面字段全部来自当前 `TrackAnalysis`。
- 低置信度字段显示 unknown/谨慎标记。
- 数据来源类型始终可辨认。

### AC-C 结构地图

- 波形、段落、和弦、能量和播放头使用同一时间轴。
- 点击、拖动和片段选择产生可观察同步。
- 移动端不退化为静态图片。

### AC-D 和弦与解释

- 理论事实在无 LLM 环境下仍正确输出。
- LLM 输入只含许可 Evidence。
- 无 Key、超时和格式错误均自动 fallback。
- 回答列出引用证据和模式。

### AC-E 隐私与安全

- 持久卷中无明文音频。
- 未授权请求不能区分记录不存在与无权访问。
- 删除和过期后音频、密钥、结果和访问权均消失。
- Secret 扫描未发现真实凭据。

### AC-F 工程交付

- 后端、前端、集成、E2E、lint、typecheck、build 和 Docker 验证均有最新成功证据。
- GitHub Actions 和 `.gitlab-ci.yml` 存在，后者含 `unit-test`。
- README 支持陌生用户本地与 Docker 启动。
- `DESIGN.md`、语义 tokens 与前端实现符合选定的 Open Design 契约。
- 公网 URL 通过完整 smoke test。
- Functional、Engineering、Product 三轮 Audit 完成。

## 20. 风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 任意混音的和弦/结构识别不可靠 | 核心页面证据稀疏 | 置信度、unknown、合成基准、明确限制 |
| Python 音频分析内存高 | 任务 OOM | 单并发、受控采样率、聚合中间矩阵、资源测试 |
| 香港跨境上传波动 | 上传中断 | 30 MB 限制、超时与重试、三网 smoke test |
| 加密 Range 实现复杂 | 播放错误或数据泄漏 | 分块格式版本化、认证加密测试、拒绝损坏块 |
| SQLite 与单机限制 | 无法水平扩展 | V1 明确单机；repository 边界支持未来迁移 |
| LLM 费用或不可用 | 解释失败 | 可选配置、速率限制、缓存、确定性 fallback |
| 域名/云账号需要人工授权 | 无法自动部署 | 所有配置先完成；真实外部步骤记录为 blocker |
| 第二类 Agent 不可用 | 无法完成课程 cold-start | 在实施前检测 Gemini/Claude/Copilot/OpenCode；如无则如实记录 blocker |

## 21. 已知限制

- V1 对复杂爵士和声、无调性音乐、强噪声、现场录音和频繁转调的结果可能为 unknown。
- 不提供 stem separation 或乐器识别。
- 单实例同时只分析一个任务，繁忙时需要排队。
- 结果与加密音频最多保留 24 小时，不是长期音乐库。
- 无账户体系；丢失浏览器访问 Cookie 后无法恢复结果。
- 香港跨境网络质量不作 SLA 承诺。
- 单 Machine 和 SQLite 不构成高可用部署。
- LLM 解释是辅助性自然语言，不替代音乐教师或专业制作分析。

## 22. V1 明确不做

- 用户注册、登录与多用户音乐库；
- 相似音乐、推荐流和长期历史；
- 社交、好友、私信、动态和音乐知音；
- 分轨、声源分离、乐器识别和旋律转录；
- 生产级推荐系统；
- HarmonyOS 原生客户端；
- 多区域、多实例、Redis 和独立 Worker 服务；
- 自主 Agent、工具调用循环或 agent framework；
- 把演示数据伪装成真实上传分析。

## 23. Definition of Done

项目必须逐项满足用户总要求中的 V1 Definition of Done，包括：A–D 模块端到端运行、真实上传分析、交互时间轴、确定性理论测试、Evidence Explanation、无 Key fallback、全套测试与构建、Docker runtime、Secret audit、合理 Git/PR 历史、双 CI 配置、全过程文档、三轮 Audit、无已知 Critical bug 和 High security issue，以及没有伪造测试、CI、人工参与或部署证据。

学生最终仍须亲自完成 README 冷启动、真实音乐上传、核心交互、PR/CI/Secret 检查和 `REFLECTION.md` 正文。
