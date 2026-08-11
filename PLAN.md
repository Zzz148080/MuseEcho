# MuseEcho V1 实施计划

> **执行者必读：** 实施本计划时必须使用 `superpowers:executing-plans`；每个功能或缺陷修复必须先使用 `superpowers:test-driven-development`，完成前必须使用 `superpowers:verification-before-completion`。独立任务使用隔离 worktree、独立分支和 PR；每个任务依次通过规格符合性审查与代码质量审查。

**目标：** 构建一个可在腾讯云 Lighthouse 单机部署的 MuseEcho V1：用户上传合法 WAV/MP3 后，系统用真实 CPU DSP/MIR 生成带置信度的节奏、能量、调性、结构和和弦事实，并通过同步可视化、确定性乐理引擎和 Evidence-first 问答帮助用户理解音乐。

**架构：** React/Vite/TypeScript 前端与 FastAPI/Python 后端组成模块化单体；SQLite 保存任务和结构化结果，单进程队列串行执行分析；音频以逐分析密钥的分块 AEAD 密文保存最多 24 小时。LLM 只解释通过白名单和置信度门槛的证据，无 Key 或调用失败时使用确定性回退。

**技术栈：** Python 3.12、FastAPI、Pydantic、SQLAlchemy 2、Alembic、NumPy、SciPy、librosa、FFmpeg、cryptography、keyring、Typer、pytest、Ruff、mypy；Node 22、React、Vite、TypeScript、TanStack Query、Vitest、Testing Library、Playwright；Docker Compose、Caddy、GitHub Actions、GitLab CI。

## 0. 当前门禁与真实性约束

- `SPEC.md` 已由用户在 2026-08-08 以原话“好，批准书面SPEC，进行下一步”批准。
- 本 `PLAN.md` 已由用户在 2026-08-08 以原话“批准 PLAN”批准进入 cold-start；在 corrected cold-start 完成后，用户又以原话“合并到主分支，最后审查修订SPEC和PLAN，批准生成HUMAN_APPROVAL.md”批准最终修订和正式实施。
- `HUMAN_APPROVAL.md` 仅在下列门禁完成后生成，并引用本次最终 SPEC/PLAN 修订提交：
  1. 用户批准当前 `PLAN.md`（已完成）；
  2. 使用与 Codex 不同类型的全新 Agent，仅凭已批准的 SPEC、PLAN 和必要文件冷启动尝试任务 1–2（已完成）；
  3. 在 `SPEC_PROCESS.md`、`AGENT_LOG.md` 中如实记录结果、误解和修订（已完成）；
  4. 用户明确确认合并、最终审查修订并授权生成 `HUMAN_APPROVAL.md`（已完成；批准文件在本次修订提交后生成并锚定该提交）。
- 不伪造测试、CI、PR、审查、人工参与、部署或公网可用性证据。
- `ai4coding-agentos-lab/` 与 `docs/input/` 是未跟踪的课程/旧项目资料，不纳入 MuseEcho 提交。

### 0.1 Cold-start 审查结论

- OpenCode 使用 `njusehub/deepseek-v4-flash` 在隔离分支 `validation/opencode-cold-start` 尝试任务 1–2，并生成 `COLD_START_REPORT.md`。原始提交 `1a3545d` 因全量 lint、仓储端口、SQLite 外键、领域不变量、UTC 和交付卫生缺陷被拒绝。
- Codex 按 RED→GREEN 修正上述问题，并补齐 `access_grants`、`encrypted_audio`、原子 `AnalysisResult` 事务、回滚、WAL、状态一致性、有限数/JSON/时长边界、工具锁定和 README；修正提交为 `07d135e`。
- 三轮独立复审最终确认 Critical、Important、Minor 均为 0；合并前与合并后的主分支验证均为 39 个 Python 测试通过，Ruff、mypy、全新 Alembic upgrade/check 通过，Node 22 容器内前端测试、类型检查与构建通过，npm audit 为 0 漏洞。
- 用户明确选择把 corrected cold-start 合并到 `main`；合并提交为 `a2d7af5`。这是真实、经审查的 Tasks 1–2 实施，不再要求从头重演；后续实现从任务 3 开始，并继续遵守分支、PR、TDD 和两阶段审查协议。
- 原始失败、修正过程和命令证据继续保留，不把被拒绝的 13-test 结果冒充最终证据，也不声称尚未发生的 CI、部署或产品验收已经完成。

## 1. 全局工程合同

### 1.1 目录与模块边界

```text
src/museecho/
  api/            # HTTP 路由、DTO、访问门禁；不包含 DSP
  application/    # 用例、任务编排、清理服务
  domain/         # 状态机、实体、值对象、领域接口
  infrastructure/ # SQLite、加密存储、FFmpeg、Secret、LLM 适配器
  analysis/       # 纯函数式 DSP/MIR 与置信度评估
  theory/         # 确定性乐理规则
frontend/src/
  api/ components/ features/ pages/ styles/ test/
tests/
  unit/ integration/ api/ fixtures/
deploy/ scripts/ docs/evidence/
```

依赖方向固定为 `api -> application -> domain`，`infrastructure` 实现 domain 端口，`analysis` 和 `theory` 不依赖 FastAPI、SQLite 或 LLM。前后端只通过 OpenAPI 合同通信。

### 1.2 核心接口（名称在实现中保持稳定）

```python
class AnalysisRepository(Protocol):
    def add(self, job: AnalysisJob) -> None: ...
    def get(self, analysis_id: UUID) -> AnalysisJob | None: ...
    def save_result(self, result: AnalysisResult) -> None: ...
    def delete_cascade(self, analysis_id: UUID) -> None: ...

class AccessService(Protocol):
    def issue(self, analysis_id: UUID, expires_at: datetime) -> IssuedAccess: ...
    def authorize(self, analysis_id: UUID, raw_token: str) -> bool: ...

class EncryptedAudioStore(Protocol):
    def write(self, analysis_id: UUID, source: BinaryIO, media_type: str) -> EncryptedAudioMetadata: ...
    def read_range(self, metadata: EncryptedAudioMetadata, start: int, end: int) -> bytes: ...
    def delete(self, metadata: EncryptedAudioMetadata) -> None: ...

class Analyzer(Protocol):
    def analyze(self, pcm: DecodedAudio) -> AnalysisResult: ...

class ExplanationProvider(Protocol):
    def explain(self, question: str, evidence: tuple[Evidence, ...]) -> ExplanationDraft: ...
```

共享时间单位一律为秒、区间为左闭右开 `[start_seconds, end_seconds)`；置信度为 `0.0..1.0`，低于模块阈值时公开值必须为 `unknown` 且 `eligible_for_llm=False`。

### 1.3 每个任务的执行协议

1. 从最新 `main` 创建命名分支和隔离 worktree。
2. 只写该任务列出的首个失败测试，运行 RED 命令并保存真实失败摘要。
3. 写满足测试的最小实现，运行 GREEN 命令。
4. 在全绿保护下重构，再运行任务最终命令。
5. 更新 `PLAN.md` 对应任务的真实提交哈希和 `AGENT_LOG.md`；不得预填哈希。
6. 推送并建 PR；先做规格符合性审查，再做代码质量审查。修复后重新验证。
7. 合并后删除 worktree；后继任务从更新后的 `main` 开始。

## 2. 依赖与并行图

```text
T1 基础工程
 ├─ T2 领域模型/数据库 ─┬─ T3 访问控制 ───────┐
 │                     ├─ T5 加密音频存储 ───┤
 │                     └─ T6 上传/任务队列 ───┤
 ├─ T4 Secret CLI ────────────────────────────┤
 └─ T7 音频解码/夹具 ─┬─ T8 节奏/能量/波形 ──┤
                      ├─ T9 调性 ─────────────┤
                      └─ T10 结构/和弦 ───────┤
T9 + T10 ── T11 乐理引擎 ─────────────────────┤
T8 + T9 + T10 + T11 ── T12 Evidence ─ T13 问答┤
上述后端任务 ── T14 编排/API/清理 ────────────┤
T1 ── T15 前端设计基础 ─ T16 上传/进度 ────────┤
T14 + T15 ─ T17 DNA/同步地图/播放器 ─ T18 问答/隐私
全部功能 ─ T19 E2E/安全/性能 ─ T20 容器/CI ─ T21 腾讯云交付
T1–T21 完成 ─ T22 Functional Audit ─ T23 Engineering Audit ─ T24 Product Audit/最终验证
```

- T3、T4、T5 在 T2 后可并行；T8、T9、T10 在 T7 后可并行。
- T15 可在 T1 后与后端任务并行；T16 可用契约 stub 开发。
- T14、T17–T21 是汇合任务，不与其未完成依赖并行。

## 3. 任务明细

### 任务 1：建立可验证的后端与前端工程骨架

**目标：** 锁定工具链，提供真实 `/api/health` 与可运行的空前端壳，不引入业务假数据。

**文件：** 新建 `pyproject.toml`、`uv.lock`、`src/museecho/__init__.py`、`src/museecho/app.py`、`tests/api/test_health.py`、`frontend/package.json`、`frontend/package-lock.json`、`frontend/vite.config.ts`、`frontend/tsconfig.json`、`frontend/src/main.tsx`、`frontend/src/App.tsx`、`frontend/src/App.test.tsx`；修改 `.gitignore`、`README.md`。

**首个失败测试：**

```python
def test_health_reports_ready(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
```

**RED：** `uv run pytest tests/api/test_health.py -q`，预期因 `museecho.app` 不存在而失败。随后为前端写 `expect(screen.getByRole('main')).toBeInTheDocument()`，执行 `npm --prefix frontend test -- --run`，预期入口不存在。

**实现：** 创建应用工厂 `create_app() -> FastAPI`；健康路由只报告进程就绪。配置 pytest、Ruff、mypy、Vitest、Testing Library；前端只渲染语义化 `<main>` 和产品名。正式实施先安装/固定 `uv` 并提交 `uv.lock`；`.gitignore` 必须排除 `*.egg-info/`、`*.tsbuildinfo` 等生成物；README 必须包含从干净 checkout 启动所需步骤。

**GREEN 条件：** 两个首测通过；后端可导入，前端可构建。

**重构：** 把测试 client 和前端测试环境移到公共 setup，不增加业务抽象。

**最终命令：** `uv run pytest -q && uv run ruff check . && uv run mypy src && npm --prefix frontend test -- --run && npm --prefix frontend run build`

**并行：** 否，所有后续任务依赖它。**对应验收标准：** AC-F 工程可构建与测试基线。**分支：** `validation/opencode-cold-start`。**计划提交：** `build: bootstrap MuseEcho application`。**实际提交：** `07d135e`（随 `a2d7af5` 合并，已完成）。

### 任务 2：领域模型、状态机与 SQLite 迁移

**目标：** 实现 SPEC 中的数据实体、区间不变量、真实阶段流转和可替换仓储。

**文件：** 新建 `src/museecho/domain/models.py`、`src/museecho/domain/status.py`、`src/museecho/domain/ports.py`、`src/museecho/infrastructure/db.py`、`src/museecho/infrastructure/repositories.py`、`alembic.ini`、`migrations/env.py`、`migrations/versions/0001_initial.py`、`tests/unit/test_job_state.py`、`tests/integration/test_repository.py`。

**首个失败测试：**

```python
def test_job_cannot_skip_from_queued_to_chords(job):
    with pytest.raises(InvalidStageTransition):
        job.advance_to(AnalysisStage.CHORDS)
```

**RED：** `uv run pytest tests/unit/test_job_state.py -q`，预期领域模块不存在。

**实现：** 建立 `AnalysisJob`、`AccessGrant`、`EncryptedAudio`、`TrackAnalysis`、`SectionEvent`、`ChordEvent`、`TimeSeries`、`Evidence`、`Explanation`；状态序列严格遵循 SPEC，终态不可回退；迁移包含外键、级联、索引和 UTC 时间；实现 `SqliteAnalysisRepository`。SQLite engine 在每个连接上启用 `PRAGMA foreign_keys=ON`；应用负责安全创建忽略的运行时数据目录；领域构造边界验证区间、置信度、来源类型和 UTC 时间；失败、删除、过期使用显式合法转换。

**GREEN 条件：** 非法跃迁失败，合法阶段进度单调；区间越界、置信度越界、非 UTC 时间和非法来源被拒；`SqliteAnalysisRepository` 经端口完成往返；新 SQLite 连接确认外键开启；删除任务后所有已实现子表均无孤儿；全新临时数据库可从零迁移到 head。

**重构：** 用领域枚举与值对象消除字符串散落，事务边界留在仓储。

**最终命令：** `uv run pytest tests/unit/test_job_state.py tests/unit/test_domain_models.py tests/integration/test_repository.py -q && uv run alembic upgrade head && uv run alembic check && uv run ruff check . && uv run mypy src`

**并行：** 否。**依赖：** T1。**对应验收标准：** AC-A 真实阶段、AC-E 级联删除与 AC-F 可维护持久化。**分支：** `validation/opencode-cold-start`。**计划提交：** `feat: add analysis domain and sqlite persistence`。**实际提交：** `07d135e`（随 `a2d7af5` 合并，已完成）。

### 任务 3：能力令牌、Cookie 与请求边界防护

**目标：** 无登录条件下让只有持有分析专属能力令牌的浏览器可以访问资源，并防止 CSRF/跨源滥用。

**文件：** 新建 `src/museecho/application/access.py`、`src/museecho/api/dependencies.py`、`src/museecho/api/security.py`、`tests/unit/test_access_service.py`、`tests/api/test_access_control.py`。

**首个失败测试：**

```python
def test_authorize_compares_hash_not_raw_token(repo, access_service):
    issued = access_service.issue(ANALYSIS_ID, EXPIRES_AT)
    assert repo.get_access(ANALYSIS_ID).token_hash != issued.raw_token
    assert access_service.authorize(ANALYSIS_ID, issued.raw_token)
```

**RED：** `uv run pytest tests/unit/test_access_service.py -q`，预期服务不存在。

**实现：** 使用 `secrets.token_urlsafe(32)`、带版本的 Argon2id 哈希和常量时间验证；Cookie 设 `Secure`、`HttpOnly`、`SameSite=Strict`、路径限定和 24h 上限；修改请求要求受信 Origin 与双提交 CSRF token；不存在、无权和过期统一返回 404。

**GREEN 条件：** 原始 token 永不持久化；错误 token、跨分析 token、过期 token、缺 CSRF 的修改请求均失败且不泄漏存在性。

**重构：** 将安全响应和 Cookie 配置集中，日志过滤 token/Cookie。

**最终命令：** `uv run pytest tests/unit/test_access_service.py tests/api/test_access_control.py -q`

**并行：** 是，可与 T4/T5 并行。**依赖：** T2。**对应验收标准：** AC-E 未授权访问不可区分且修改请求受保护。**分支：** `feat/03-capability-access`。**计划提交：** `feat: secure analysis capability access`。**实际提交：** `4cc4c88`、`36a0729`、`66b0ed0`（实现与审查修复，已完成）。

### 任务 4：本地 Secret CLI 与提供方配置

**目标：** 支持 Key 的 set/status/update/clear，原生使用 OS keyring，容器只读 Secret 文件；任何输出和日志不泄露明文。

**文件：** 新建 `src/museecho/infrastructure/secrets.py`、`src/museecho/cli.py`、`tests/unit/test_secret_store.py`、`tests/cli/test_secret_cli.py`、`.env.example`；修改 `pyproject.toml`、`.gitignore`。

**首个失败测试：**

```python
def test_status_never_prints_secret(runner, memory_store):
    memory_store.set("sk-test-value")
    result = runner.invoke(app, ["secret", "status"])
    assert result.exit_code == 0
    assert "configured" in result.stdout
    assert "sk-test-value" not in result.stdout
```

**RED：** `uv run pytest tests/cli/test_secret_cli.py -q`，预期 CLI 不存在。

**实现：** `SecretStore` 端口与 `KeyringSecretStore`、`FileSecretStore`、测试内存实现；文件必须非仓库路径、只读装载；CLI 从隐藏提示读取；provider base URL/model 为非秘密配置，Key 不进入环境诊断输出。

**GREEN 条件：** 四个命令行为正确，更新覆盖旧值，clear 后回退；测试捕获 stdout/stderr/log 均无秘密。

**重构：** 把选择策略封装为 `resolve_secret_store(settings)`，拒绝模糊优先级。

**最终命令：** `uv run pytest tests/unit/test_secret_store.py tests/cli/test_secret_cli.py -q && uv run ruff check src tests`

**并行：** 是。**依赖：** T1。**对应验收标准：** AC-D 无 Key 回退前提与 AC-E/AC-F Secret 安全交付。**分支：** `feat/04-secret-cli`。**计划提交：** `feat: add secure provider secret management`。**实际提交：** `b826810`、`3267e86`、`48d5d0f`（实现与安全审查修复，已完成）。

### 任务 5：分块 AEAD 音频存储与密码擦除

**目标：** 持久卷中只出现认证密文，支持 HTTP Range 所需的精确解密，篡改即失败，删除时先销毁密钥再删密文。

**文件：** 新建 `src/museecho/infrastructure/crypto.py`、`src/museecho/infrastructure/audio_store.py`、`tests/unit/test_encrypted_audio_store.py`、`tests/integration/test_audio_range.py`。

**首个失败测试：**

```python
def test_ciphertext_does_not_contain_plaintext(store, tmp_path):
    metadata = store.write(ANALYSIS_ID, BytesIO(b"RIFF" + b"music" * 1000), "audio/wav")
    assert b"music" not in Path(metadata.cipher_path).read_bytes()
```

**RED：** `uv run pytest tests/unit/test_encrypted_audio_store.py -q`，预期存储实现不存在。

**实现：** 每个分析随机 256-bit DEK；AES-256-GCM 逐块独立 nonce，AAD 包含格式版本、分析 ID、块号和明文长度；KEK 只来自 Secret；元数据保存 wrapped DEK 和块索引；Range 只解密覆盖块并裁剪。删除顺序为事务性标记不可访问、删除 wrapped DEK、删除密文。

**GREEN 条件：** 全文和跨块 Range 字节一致；交换/截断/篡改单块均失败；删密钥后无法恢复。

**重构：** 格式头与 nonce 派生集中并版本化，敏感 bytearray 尽可能清零。

**最终命令：** `uv run pytest tests/unit/test_encrypted_audio_store.py tests/integration/test_audio_range.py -q`

**并行：** 是。**依赖：** T2/T4。**对应验收标准：** AC-E 持久卷无明文、Range 认证解密和密码擦除。**分支：** `feat/05-encrypted-audio`。**计划提交：** `feat: add chunked encrypted audio storage`。**实际提交：** `ad2f0b7`、`db9898d`、`ffa0fe4`（实现、生命周期加固与跨实例擦除串行化，已完成）。

### 任务 6：流式上传、真实校验与单并发任务队列

**目标：** 限制 30 MB/10 分钟，拒绝伪扩展名、损坏和不支持文件，并以真实阶段状态提交串行分析任务。

**文件：** 新建 `src/museecho/application/uploads.py`、`src/museecho/application/queue.py`、`src/museecho/api/analyses.py`、`tests/api/test_upload.py`、`tests/unit/test_queue.py`。

**首个失败测试：**

```python
def test_rejects_mp3_name_with_non_audio_bytes(client):
    response = client.post("/api/analyses", files={"file": ("fake.mp3", b"not audio", "audio/mpeg")})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_audio"
```

**RED：** `uv run pytest tests/api/test_upload.py -q`，预期路由 404。

**实现：** 流式计数和临时隔离文件；FFprobe/FFmpeg 验证真实格式和时长；随机内部名；只有验证完成后写入加密存储。`SingleWorkerQueue` 同时只执行一项，启动时把非终态任务恢复到安全重试队列；阶段由工作实际完成事件推进。

**GREEN 条件：** 大小、时长、损坏、扩展名欺骗被拒；有效上传返回 202、不可猜 ID 和访问 Cookie；重复上传分别创建隔离任务且不会串用结果；两个任务不会并行分析；重启恢复不伪造完成。

**重构：** 统一错误码和临时文件清理上下文，队列依赖注入 fake analyzer。

**最终命令：** `uv run pytest tests/api/test_upload.py tests/unit/test_queue.py -q`

**并行：** 否。**依赖：** T2/T3/T5/T7。**对应验收标准：** AC-A 有效/无效上传、真实任务与资源边界。**分支：** `feat/06-upload-queue`。**计划提交：** `feat: validate uploads and queue analyses`。**实际提交：** `8217cb4`、`c1da09e`、`76a642c`、`622ebe4`（上传与队列、资源边界、所有权与异常隔离、仓储故障重排，已完成）。

### 任务 7：FFmpeg 解码与合成音频夹具

**目标：** 把合法音频解码为受控单声道浮点 PCM，并用程序生成、可复现、无版权风险的测试夹具。

**文件：** 新建 `src/museecho/analysis/decode.py`、`tests/fixtures/audio_factory.py`、`tests/integration/test_decode.py`、`tests/fixtures/README.md`。

**首个失败测试：**

```python
def test_decode_normalizes_to_target_rate(sine_wav):
    decoded = decode_audio(sine_wav, target_sample_rate=22050)
    assert decoded.sample_rate == 22050
    assert decoded.samples.ndim == 1
    assert decoded.duration_seconds == pytest.approx(2.0, abs=0.03)
```

**RED：** `uv run pytest tests/integration/test_decode.py -q`，预期函数不存在。

**实现：** FFprobe 先检查，FFmpeg 限制通道、采样率和输出时长；捕获超时与退出码并映射领域错误；factory 生成正弦、节拍器、大/小三和弦、和弦进行、分段能量、静音、极短和损坏样本。

**GREEN 条件：** WAV/MP3 均解码到目标形状；坏文件、超时、超限明确失败；夹具哈希稳定。

**重构：** 子进程运行器可注入，stderr 经过长度限制和路径脱敏。

**最终命令：** `uv run pytest tests/integration/test_decode.py -q`

**并行：** 是，可与 T3–T5 并行。**依赖：** T1。**对应验收标准：** AC-A 真实可解码性校验与无版权合成基准。**分支：** `feat/07-audio-decoding`。**计划提交：** `feat: decode audio and generate test fixtures`。**实际提交：** `7daa96d`、`823d8cb`、`1a692f7`（解码与夹具、资源边界、输入与进程树隔离，已完成）。

### 任务 8：波形、节奏和能量事实

**目标：** 从 PCM 计算波形桶、BPM/beat positions、RMS 能量和显著变化事件，全部携带算法与置信度。

**文件：** 新建 `src/museecho/analysis/waveform.py`、`src/museecho/analysis/rhythm.py`、`src/museecho/analysis/energy.py`、`tests/unit/analysis/test_signal_features.py`。

**首个失败测试：**

```python
def test_metronome_estimates_120_bpm(metronome_120_pcm):
    result = extract_signal_features(metronome_120_pcm)
    assert result.bpm == pytest.approx(120, abs=3)
    assert result.bpm_confidence >= 0.7
```

**RED：** `uv run pytest tests/unit/analysis/test_signal_features.py -q`，预期模块不存在。

**实现：** 固定 hop/window；波形保存每桶 min/max；librosa onset/beat 输出 BPM 和拍点；RMS 归一化并以稳健 z-score 找变化；静音和弱节拍返回 unknown。入口为 `extract_signal_features(samples, sample_rate) -> SignalFeatures`。

**GREEN 条件：** 120 BPM 容差、分段能量边界、波形峰值、静音 unknown 全通过；时间均合法。

**重构：** 将窗口配置和阈值做成版本化 dataclass，输出只含 JSON 可序列化数值。

**最终命令：** `uv run pytest tests/unit/analysis/test_signal_features.py -q`

**并行：** 是。**依赖：** T7。**对应验收标准：** AC-A 真实分析、AC-B Music DNA 与 AC-C 同步波形/能量证据。**分支：** `feat/08-signal-features`。**计划提交：** `feat: extract waveform rhythm and energy evidence`。**实际提交：** `f941d53`（波形、节奏与能量事实）、`3de45a1`（置信度与长音频资源边界）、`d0af694`（弱细分与宏观能量趋势分离）、`80bda00`（早期能量边界与实际 FFT 输入保护），已完成。

### 任务 9：调性与调式估计

**目标：** 用 chroma 与调性模板产生 tonic/mode、稳定性分数和可解释置信度；不确定时返回 unknown。

**文件：** 新建 `src/museecho/analysis/tonality.py`、`tests/unit/analysis/test_tonality.py`。

**首个失败测试：**

```python
def test_c_major_progression_is_classified(c_major_progression_pcm):
    estimate = estimate_tonality(c_major_progression_pcm)
    assert (estimate.tonic, estimate.mode) == ("C", "major")
    assert estimate.confidence >= 0.7
```

**RED：** `uv run pytest tests/unit/analysis/test_tonality.py -q`，预期模块不存在。

**实现：** 计算调谐感知 chroma，按 Krumhansl 风格大小调模板相关性排名；置信度结合第一/第二候选差距、时间稳定性和有效能量；频繁转调/静音/无调性样本低于阈值时公开 unknown。

**GREEN 条件：** 合成 C 大调、A 小调正确；静音和模糊半音集合 unknown；enharmonic 规范一致。

**重构：** 模板和拼写策略独立纯函数，保留 top candidates 仅供诊断而非向 LLM 泄漏低置信度事实。

**最终命令：** `uv run pytest tests/unit/analysis/test_tonality.py -q`

**并行：** 是。**依赖：** T7。**对应验收标准：** AC-B 调性/调式来源与低置信度 unknown。**分支：** `feat/09-tonality`。**计划提交：** `feat: estimate key mode and confidence`。**实际提交：** `902a5b8`（调性模板、稳定性与 unknown 契约）、`e793097`（持续调性证据、采样率与资源边界），已完成。

### 任务 10：结构分段与和弦时间线

**目标：** 产生 recurrence/self-similarity 结构边界与大/小三和弦事件，并通过平滑、稳定性和 unknown 路径控制过度断言。

**文件：** 新建 `src/museecho/analysis/structure.py`、`src/museecho/analysis/chords.py`、`tests/unit/analysis/test_structure.py`、`tests/unit/analysis/test_chords.py`。

**首个失败测试：**

```python
def test_c_g_am_f_progression_has_timed_chords(c_g_am_f_pcm):
    events = estimate_chords(c_g_am_f_pcm)
    assert [event.symbol for event in events] == ["C", "G", "Am", "F"]
    assert all(event.end_seconds > event.start_seconds for event in events)
```

**RED：** `uv run pytest tests/unit/analysis/test_chords.py -q`，预期模块不存在。

**实现：** 结构使用 chroma recurrence、novelty peak、最短段长和相似段聚类，标签只用 `A/B/C…`；和弦用 24 个大小三和弦模板、key-aware 但不强制调内先验、Viterbi/中值平滑与最短事件时长。入口分别为 `segment_structure(...)`、`estimate_chords(...)`。

**GREEN 条件：** 合成 ABA 边界在容差内；四和弦进行顺序和时间正确；噪声/歧义帧合并为 unknown；结果覆盖但不越过音频时长。

**重构：** 特征计算共享而决策纯函数分离；算法版本写入每个事件。

**最终命令：** `uv run pytest tests/unit/analysis/test_structure.py tests/unit/analysis/test_chords.py -q`

**并行：** 是。**依赖：** T7。**对应验收标准：** AC-B 结构/和声摘要与 AC-C 同时间轴事件。**分支：** `feat/10-structure-chords`。**计划提交：** `feat: detect structure and chord events`。**实际提交：** `30d63c1`（结构/和弦核心实现）、`8e6af06`（最小和弦证据）、`8ca8f35`（和声与结构断言门控）、`31b5388`（平滑事件与复现校验）、`8ac4027`（多段结构边界）、`1099cd3`（一般结构复现）、`bae61b1`（稳定段与循环区分）、`cd5bcb9`（稳定段与循环变奏）、`53f8add`（按段落复现判定循环），已完成。

### 任务 11：确定性乐理引擎

**目标：** 不依赖 LLM 地解释和弦组成音、音程、性质、调内级数、可能功能和上下文限制。

**文件：** 新建 `src/museecho/theory/notes.py`、`src/museecho/theory/chords.py`、`src/museecho/theory/functions.py`、`tests/unit/theory/test_chords.py`。

**首个失败测试：**

```python
def test_g_major_in_c_major_is_dominant():
    theory = explain_chord("G", tonic="C", mode="major")
    assert theory.pitch_classes == ("G", "B", "D")
    assert theory.roman_numeral == "V"
    assert "dominant" in theory.functions
```

**RED：** `uv run pytest tests/unit/theory/test_chords.py -q`，预期模块不存在。

**实现：** 12 音级规范化、大小三和弦解析、调式音阶与级数映射；调外和弦标注 non-diatonic，不假造唯一功能；处理升降号等音异名。公开 `explain_chord(symbol, tonic, mode) -> ChordTheory`。

**GREEN 条件：** 12 调大小调参数化测试、等音边界、调外和 unknown 输入通过；相同输入完全可复现。

**重构：** 数据表与推理分离，返回不可变 DTO，不加入生成式文本。

**最终命令：** `uv run pytest tests/unit/theory/test_chords.py -q`

**并行：** 否。**依赖：** T9/T10。**对应验收标准：** AC-D 无 LLM 仍可复现的乐理事实。**分支：** `feat/11-theory-engine`。**计划提交：** `feat: explain chords with deterministic theory`。**实际提交：** `273b39b`（确定性乐理引擎与参数矩阵）、`46b1cd6`（公共接口与小调属和弦等音上下文），已完成。

### 任务 12：Evidence 构建、置信度门槛与时间窗选择

**目标：** 把分析事实转成可追溯 Evidence，并保证低置信度、窗外或不支持字段绝不进入 LLM。

**文件：** 新建 `src/museecho/application/evidence.py`、`tests/unit/test_evidence_policy.py`。

**首个失败测试：**

```python
def test_low_confidence_chord_is_never_llm_eligible():
    evidence = build_evidence(result_with_chord(confidence=0.39))
    chord = next(item for item in evidence if item.kind == "chord")
    assert chord.public_value == "unknown"
    assert chord.eligible_for_llm is False
```

**RED：** `uv run pytest tests/unit/test_evidence_policy.py -q`，预期策略不存在。

**实现：** 每类事实独立阈值、算法来源、时间范围和稳定 Evidence ID；`select_for_segment(start,end)` 只选相交且 eligible 项并限制总数/大小；白名单仅含 rhythm、energy、tonality、section、chord、deterministic_theory。

**GREEN 条件：** 边界阈值、unknown、时间交集、白名单、数量/字符上限均通过；禁止 emotion/genre/instrument 等字段。

**重构：** 门槛放入版本化 `EvidencePolicy`，序列化器默认拒绝未知 kind。

**最终命令：** `uv run pytest tests/unit/test_evidence_policy.py -q`

**并行：** 否。**依赖：** T8–T11。**对应验收标准：** AC-D LLM 只接收时间窗内合格 Evidence。**分支：** `feat/12-evidence-policy`。**计划提交：** `feat: enforce evidence eligibility policy`。**实际提交：** `c14d87e`（版本化策略、Evidence 构建与安全选择）、`2e8da87`（可变结果与持久化证据信任边界复验），已完成。

### 任务 13：Evidence-first LLM 适配器与确定性回退

**目标：** 回答只引用允许证据；无 Key、超时、HTTP 错误、非法结构或无合格证据时仍给出安全、可解释结果。

**文件：** 新建 `src/museecho/application/explanations.py`、`src/museecho/infrastructure/llm.py`、`tests/unit/test_explanation_service.py`、`tests/integration/test_llm_adapter.py`。

**首个失败测试：**

```python
def test_missing_key_uses_deterministic_fallback(evidence):
    answer = ExplanationService(provider=None).explain("为什么有张力？", evidence)
    assert answer.mode == "fallback"
    assert answer.evidence_ids == tuple(item.id for item in evidence)
```

**RED：** `uv run pytest tests/unit/test_explanation_service.py -q`，预期服务不存在。

**实现：** provider 接口只接收经选择的结构化 Evidence；提示词禁止补充未给事实并要求 JSON schema；适配 OpenAI-compatible HTTP；设置连接/总超时、响应上限、一次受控重试；解析失败回退。fallback 用模板组合事实、限制和教学解释，不声称因果唯一性。

**GREEN 条件：** stub provider 只能观察白名单证据；缺 Key、超时、500、非 JSON、未知 evidence ID 全回退；响应始终列出实际 Evidence ID 与 mode。

**重构：** provider 与 fallback 完全分离；问题只存摘要，日志不存 Key 或完整用户音频信息。

**最终命令：** `uv run pytest tests/unit/test_explanation_service.py tests/integration/test_llm_adapter.py -q`

**并行：** 否。**依赖：** T4/T12。**对应验收标准：** AC-D 引证、模式标记和所有失败路径回退。**分支：** `feat/13-evidence-explanations`。**计划提交：** `feat: explain evidence with safe fallback`。**实际提交：** `a59db06`（安全解释服务、OpenAI-compatible 适配器与失败回退）、`20ecd8a`（provider 隔离与教学型 fallback），已完成。

### 任务 14：分析编排、完整 API、Range 播放与到期清理

**目标：** 串起上传到结果的真实闭环，实现 SPEC 的全部 API、原子删除和 24h 清理。

**文件：** 新建 `src/museecho/application/coordinator.py`、`src/museecho/application/cleanup.py`、`src/museecho/api/results.py`、`src/museecho/api/audio.py`、`src/museecho/api/explanations.py`、`tests/integration/test_analysis_pipeline.py`、`tests/api/test_analysis_api.py`、`tests/integration/test_cleanup.py`；修改 `src/museecho/app.py`。

**首个失败测试：**

```python
def test_pipeline_persists_real_result_for_uploaded_fixture(client, valid_fixture):
    created = upload_and_wait(client, valid_fixture)
    result = client.get(f"/api/analyses/{created.id}")
    assert result.status_code == 200
    assert result.json()["source_kind"] == "real"
    assert result.json()["pipeline_version"]
```

**RED：** `uv run pytest tests/integration/test_analysis_pipeline.py -q`，预期结果路由/编排不存在。

**实现：** `AnalysisCoordinator` 逐阶段调用 decode、signal、tonality、structure、chords、theory、evidence 并在每阶段提交真实状态；失败保存稳定错误码。实现 status/result/audio/explanation/delete；Range 支持 206、Content-Range 和非法范围 416。清理器扫描到期项，先撤销访问和密钥，再级联结果/密文，幂等重试。

**GREEN 条件：** 合成上传完整闭环；刷新可恢复状态；播放器 Range 正确；非法时间戳和畸形分析结果被拒且错误稳定；问答与删除正确；到期后所有端点统一不可见且密文/密钥/行被清理。

**重构：** 用用例服务保持路由薄；阶段计时写指标但不记录原始内容。

**最终命令：** `uv run pytest tests/api tests/integration -q`

**并行：** 否。**依赖：** T3/T5/T6/T8–T13。**对应验收标准：** AC-A 至 AC-E 的后端纵向闭环。**分支：** `feat/14-analysis-api`。**计划提交：** `feat: complete analysis lifecycle API`。**实际提交：** `0b5342e`（真实分析编排、完整生命周期 API、Range 播放、原子加密擦除与幂等到期清理），已完成。

### 任务 15：Open Design 前端基础与可访问组件

**目标：** 按 `DESIGN.md` 和 Open Design `Warm Editorial` 实现品牌 tokens、响应式单画布壳和基础组件，不使用通用 AI dashboard 风格。

**文件：** 新建 `frontend/src/styles/tokens.css`、`frontend/src/styles/global.css`、`frontend/src/components/Button.tsx`、`Panel.tsx`、`ConfidenceBadge.tsx`、`ErrorNotice.tsx`、`frontend/src/pages/AnalysisPage.tsx`、`frontend/src/pages/AnalysisPage.test.tsx`；修改 `frontend/src/App.tsx`。

**首个失败测试：**

```tsx
it('provides a single labelled analysis workspace', () => {
  render(<AnalysisPage />)
  expect(screen.getByRole('main', {name: /museecho 音乐解析工作区/i})).toBeVisible()
})
```

**RED：** `npm --prefix frontend test -- --run src/pages/AnalysisPage.test.tsx`，预期页面不存在。

**实现：** 使用暖纸色/近黑/森林绿/陶土/琥珀语义 tokens；字体、间距、焦点、状态、运动降级遵循 `DESIGN.md`；桌面横向组织关联信息，移动端单列；组件覆盖键盘和屏幕阅读器语义。

**GREEN 条件：** 语义结构、可见 focus、颜色对比和 reduced-motion 组件测试通过；无业务硬编码数据。

**重构：** 只提取重复样式与行为，避免过度组件化。

**最终命令：** `npm --prefix frontend test -- --run && npm --prefix frontend run typecheck && npm --prefix frontend run build`

**并行：** 是。**依赖：** T1。**对应验收标准：** AC-F Open Design 契约、响应式与可访问性基础。**分支：** `feat/15-design-system`。**计划提交：** `feat: establish Warm Editorial interface`。**实际提交：** `b035b05`（Warm Editorial tokens、响应式单画布、可访问基础组件、真实空状态与 pytest 隔离收集配置），已完成。

### 任务 16：上传、隐私同意与真实进度界面

**目标：** 用户上传前看见限制/隐私规则，能处理验证错误并在刷新后继续观察真实阶段。

**文件：** 新建 `frontend/src/api/client.ts`、`frontend/src/api/types.ts`、`frontend/src/features/upload/UploadForm.tsx`、`frontend/src/features/jobs/AnalysisProgress.tsx`、对应测试；修改 `AnalysisPage.tsx`。

**首个失败测试：**

```tsx
it('does not upload until legal-use and retention consent is checked', async () => {
  render(<UploadForm onUpload={onUpload} />)
  await user.upload(screen.getByLabelText(/音频文件/), validFile)
  expect(screen.getByRole('button', {name: /开始分析/})).toBeDisabled()
})
```

**RED：** `npm --prefix frontend test -- --run src/features/upload`，预期组件不存在。

**实现：** WAV/MP3、30MB 客户端预检但以后端为准；明确合法使用确认、24h 加密保留与删除说明；上传进度和后端阶段分开；TanStack Query 轮询真实 status，刷新用 Cookie+URL ID 恢复；失败显示稳定错误码的友好文本。

**GREEN 条件：** 未同意不可上传；错误与重试可访问；进度不会用计时器伪造；终态停止轮询。

**重构：** API 状态机集中到 hook，组件只负责呈现。

**最终命令：** `npm --prefix frontend test -- --run src/features/upload src/features/jobs && npm --prefix frontend run typecheck`

**并行：** 是，可基于 OpenAPI mock。**依赖：** T15，集成验收依赖 T14。**对应验收标准：** AC-A 上传/真实阶段与 AC-E 隐私告知。**分支：** `feat/16-upload-progress-ui`。**计划提交：** `feat: add honest upload and progress flow`。**实际提交：** `93ba4f6`（真实上传进度、隐私同意、状态轮询与保守错误恢复），已完成。

### 任务 17：播放器、Music DNA 与同步结构地图

**目标：** 用同一时间坐标同步音频、波形、段落、和弦、能量、播放头和拖选，并展示真实 Music DNA 与置信度。

**文件：** 新建 `frontend/src/features/player/AudioPlayer.tsx`、`frontend/src/features/dna/MusicDNA.tsx`、`frontend/src/features/timeline/Timeline.tsx`、`useTimeline.ts`、`frontend/src/features/chords/ChordDetails.tsx`、对应测试；修改 `AnalysisPage.tsx`。

**首个失败测试：**

```tsx
it('seeking a chord moves the shared playhead to its start', async () => {
  render(<Timeline result={fixtureResult} />)
  await user.click(screen.getByRole('button', {name: /和弦 G/}))
  expect(mockMedia.currentTime).toBe(8)
  expect(screen.getByTestId('playhead')).toHaveAttribute('data-seconds', '8')
})
```

**RED：** `npm --prefix frontend test -- --run src/features/timeline`，预期组件不存在。

**实现：** `useTimeline` 持有 duration/currentTime/selection；所有轨道以比例坐标渲染；HTMLMediaElement 通过受权 Range URL 播放；拖选生成合法片段；和弦点击 seek 并显示确定性乐理；unknown 和 source_kind 明示。Canvas/SVG 保留可访问替代列表。

**GREEN 条件：** 点击、键盘 seek、拖选、播放事件同步；DNA 不显示不存在字段；桌面/平板/手机仍可操作。

**重构：** 坐标换算和裁剪成为纯函数并参数化测试，渲染层不复制时间状态。

**最终命令：** `npm --prefix frontend test -- --run src/features/player src/features/dna src/features/timeline src/features/chords && npm --prefix frontend run build`

**并行：** 否。**依赖：** T14/T15。**对应验收标准：** AC-B、AC-C 与 AC-D 和弦详情。**分支：** `feat/17-music-workspace`。**计划提交：** `feat: visualize synchronized music evidence`。**实际提交：** `13a6346`（播放器、真实 Music DNA、同步结构地图、和弦详情与严格结果解析），已完成。

### 任务 18：片段问答、保留期限和主动删除体验

**目标：** 让用户对选定片段提问、查看证据/模式，并清晰控制 24h 数据生命周期。

**文件：** 新建 `frontend/src/features/explanations/QuestionPanel.tsx`、`EvidenceList.tsx`、`frontend/src/features/privacy/RetentionPanel.tsx`、对应测试；修改 `AnalysisPage.tsx`。

**首个失败测试：**

```tsx
it('renders fallback mode and cited evidence', async () => {
  server.use(mockFallbackExplanation())
  render(<QuestionPanel selection={{start: 8, end: 16}} />)
  await user.type(screen.getByLabelText(/问题/), '为什么这里有张力？')
  await user.click(screen.getByRole('button', {name: /解释片段/}))
  expect(await screen.findByText(/确定性回退/)).toBeVisible()
  expect(screen.getAllByRole('link', {name: /证据/})).not.toHaveLength(0)
})
```

**RED：** `npm --prefix frontend test -- --run src/features/explanations`，预期组件不存在。

**实现：** 问题和片段长度前置限制；答案显示 provider/fallback mode、证据列表和 unknown 限制；证据链接定位时间轴。倒计时基于服务端 expires_at；删除需明确确认，成功后清空本地状态并导航到不可恢复说明。

**GREEN 条件：** 有/无 Key 模式可区分；证据可定位；超时/限流/过期可恢复；删除后不会继续请求或保留结果在 UI。

**重构：** 网络状态用共享错误组件，避免复制敏感错误详情。

**最终命令：** `npm --prefix frontend test -- --run src/features/explanations src/features/privacy && npm --prefix frontend run typecheck`

**并行：** 否。**依赖：** T14/T17。**对应验收标准：** AC-D Evidence Explanation 与 AC-E 到期/主动删除。**分支：** `feat/18-explanation-privacy-ui`。**计划提交：** `feat: add evidence questions and privacy controls`。**实际提交：** `b1c55ec`（Evidence 问答、引用定位、服务端保留期限、CSRF 主动删除与本地不可恢复状态），已完成。

### 任务 19：端到端、安全、可访问性与性能验证

**目标：** 用真实服务和合成音频验证完整闭环，建立 2vCPU/4GB、5 分钟音频不超过 90 秒的可重复基准。

**文件：** 新建 `e2e/museecho.spec.ts`、`e2e/responsive.spec.ts`、`e2e/security.spec.ts`、`playwright.config.ts`、`tests/performance/test_five_minute_budget.py`、`scripts/benchmark.py`、`docs/evidence/README.md`。

**首个失败测试：**

```ts
test('upload to delete completes without console errors', async ({page}) => {
  await uploadFixture(page, 'tests/fixtures/generated/c-g-am-f.wav')
  await expect(page.getByText(/分析完成/)).toBeVisible()
  await expect(page.getByRole('heading', {name: /Music DNA/})).toBeVisible()
  await deleteAnalysis(page)
  await expect(page.getByText(/已永久删除/)).toBeVisible()
})
```

**RED：** `npm --prefix frontend exec playwright test e2e/museecho.spec.ts`，预期在未完成闭环处失败。

**实现：** E2E 覆盖上传→分析→DNA→地图→播放/拖选→和弦→fallback Q&A→删除；捕获 console/page/network errors；桌面/平板/手机视口；安全用例覆盖越权、CSRF、Range、文件炸弹和日志泄漏。benchmark 生成 5 分钟代表样本，记录 CPU、峰值 RSS、各阶段耗时与环境。

**GREEN 条件：** E2E 全绿且无未解释 console error；安全用例全绿；目标规格机器或等效限额下实测 ≤90s 才标记性能通过，否则如实登记 blocker/优化任务。

**重构：** 共享 E2E 操作封装但不隐藏断言；证据文件只保存命令、版本、摘要和非敏感日志。

**最终命令：** `uv run pytest -q && npm --prefix frontend test -- --run && npm run typecheck && npm run e2e && uv run python scripts/benchmark.py --duration 300 --json docs/evidence/performance.json`

**并行：** 否。**依赖：** T14/T16–T18。**对应验收标准：** AC-A 至 AC-F 的真实浏览器、安全与性能证据。**分支：** `feat/19-system-verification`（按后续统一 `feat/*` 分支规则执行）。**计划提交：** `test: verify MuseEcho end to end`。**实际提交：** `9ad408c5b51e7d5ff15e3123d72d012df824e6df`（真实 HTTPS E2E、安全/响应式矩阵、独立 TypeScript 门禁、300 秒完整性能基准与非敏感证据）；证据记录提交为 `1047ce242884b6ba83a525524e88dcc44ab76a69`，已完成。

### 任务 20：生产容器、双 CI 与依赖/Secret 审计

**目标：** 提供非 root、可复现的单机发行物，并在 GitHub/GitLab 运行等价核心质量门禁。

**文件：** 新建 `Dockerfile`、`compose.yaml`、`Caddyfile`、`.dockerignore`、`.github/workflows/ci.yml`、`.gitlab-ci.yml`、`scripts/container-smoke.ps1`、`scripts/secret-scan.ps1`、`scripts/verify.ps1`、`THIRD_PARTY_NOTICES.md`；修改 `README.md`。

**首个失败测试：**

```powershell
docker compose build
docker compose up -d
Invoke-RestMethod http://localhost/api/health | Should -BeLike '*ready*'
```

先把上述行为写成 `scripts/container-smoke.ps1` 并使其在镜像文件不存在时失败。

**RED：** `pwsh -File scripts/container-smoke.ps1`，预期因 Dockerfile/Compose 不存在失败。

**实现：** 多阶段构建前端与锁定 Python 依赖；运行镜像含 FFmpeg、非 root 用户和健康检查；`/data` 持久卷、Secret 只读挂载；Caddy 同源代理。`scripts/verify.ps1` 提供后端、前端、集成、lint、typecheck、build 和 E2E 的一键失败即停入口。GitHub Actions 与 GitLab 均执行 lint/type/test/build/E2E/Docker/secret scan，GitLab 明确包含 `unit-test` job；审计依赖许可证和镜像高危漏洞。README 必须包含项目介绍、核心功能、架构、技术栈、目录、环境、安装、本地运行、测试、Docker、凭据、安全、分发、部署、限制和许可证章节。

**GREEN 条件：** 全新构建、健康、上传 smoke、重启持久性和关闭通过；镜像中无源码 Secret/明文音频；两套 CI 配置通过本地 lint，远端状态只在真实运行后记录。

**重构：** Compose 开发/生产差异显式 profile 化；脚本失败即非零退出。

**最终命令：** `pwsh -File scripts/secret-scan.ps1; if ($LASTEXITCODE) { exit $LASTEXITCODE }; pwsh -File scripts/container-smoke.ps1`

**并行：** 否。**依赖：** T19。**对应验收标准：** AC-E Secret audit 与 AC-F Docker、双 CI、README、许可证。**分支：** `feat/20-production-delivery`。**计划提交：** `build: package and verify production distribution`。**实际状态：** `70dde35` 为初始实现；审查修复轮 2/3 移除 suppression 并补齐生产合约。安全轮 4 提交 `f6ad867` 并引入 schema-v2 精确 181 tuple/67 CVE OpenVEX 门禁。轮 5 保留安全 PCM/IEEE-float WAVEFORMATEXTENSIBLE（`cbSize >= 22`、有界声明扩展、`0 < valid_bits <= container_bits`），但产品明确仅支持可计算帧大小的常规 MPEG Layer III；free-format bitrate index `0000` 因锁定 FFmpeg 5.1.9 端到端拒绝而在工具前失败关闭。GitLab 已改为同一不可变 app tar 的 raw 无 suppression 扫描 → package/probe inventory → 精确 audit/VEX → VEX gate，raw/audit 证据均 `when: always`。最终 app `sha256:5c12e66ae1b5b63f40c32d2e4ddc8a96157abc8f8952d87ff0fd4982b18934ed`、gateway `sha256:ef3c87c9657ca052c02af74271219b36b260a712d0567ed8560410ec37e36317` 均为 `10001:10001`；挂载仓库 `tmp/trivy-cache` 后在 `--network none`/offline/no-update 下 fresh raw app 181（169 HIGH/12 CRITICAL、67 CVE、fixed 0）、gateway 0，精确 audit 181 tuple/38 packages/67 statements/residual 0、app VEX 与 gateway raw gate 均 exit 0、可见 0。远端 CI 未运行，尚未合并。

### 任务 21：腾讯云交付手册与真实部署

**目标：** 把已验证镜像部署到腾讯云 Lighthouse 中国香港，完成公网 smoke 和回滚演练；三轮审计由后续独立任务执行。

**文件：** 新建 `deploy/tencent-cloud/README.md`、`deploy/tencent-cloud/install.sh`、`deploy/tencent-cloud/deploy.sh`、`deploy/tencent-cloud/rollback.sh`、`deploy/tencent-cloud/backup.sh`、`deploy/tencent-cloud/museecho.service`、`DEPLOYMENT_EVIDENCE.md`；修改 `README.md`、`BLOCKERS.md`、`AGENT_LOG.md`、`REFLECTION_NOTES.md`。

**首个失败测试：**

```bash
shellcheck deploy/tencent-cloud/*.sh
bash deploy/tencent-cloud/install.sh --check-only
```

**RED：** 上述命令预期因脚本不存在失败。

**实现：** 脚本检查 Linux/2vCPU/4GB/磁盘，创建 `/srv/museecho/data` 与 `/etc/museecho/secrets`，只开放 22/80/443，说明 SSH 密钥与禁用密码登录，部署固定镜像 digest，健康失败自动回滚；备份只含必要数据库/元数据并记录加密边界。由用户提供真实云账号、域名、DNS 和 SSH 授权后才执行外部变更。

**GREEN 条件：** 本地 shellcheck/check-only 通过；真实服务器上 HTTPS、健康、上传、分析、播放、Q&A、删除、24h 清理与回滚演练有时间戳证据；至少尝试不同大陆网络。未获得云授权时准确记录 blocker，不伪造公网完成或阻止可继续的审计工作。

**重构：** 部署参数集中、幂等、秘密不作为参数或日志输出。

**最终命令：** `shellcheck deploy/tencent-cloud/*.sh && bash deploy/tencent-cloud/install.sh --check-only`；公网 smoke 命令在获得真实域名后写入 `DEPLOYMENT_EVIDENCE.md` 并逐条执行。

**并行：** 否。**依赖：** T20 和用户云端授权。**对应验收标准：** AC-F 公网 URL 与完整 smoke。**分支：** `ops/21-tencent-delivery`。**计划提交：** `ops: deploy verified Tencent Cloud release`。**实际提交：** `1bc9f72`（本地交付脚本、证据与合约测试已完成；公网 URL/完整 smoke 仍受真实云端授权约束，未声称完成）。

### 任务 22：Functional Audit 与验收缺口闭环

**目标：** 在 T1–T21 完成后逐条以最新客观证据审计 SPEC 验收标准，所有 FAIL 和重要 PARTIAL 转成修复任务并重验。

**文件：** 新建 `docs/audits/FUNCTIONAL_AUDIT.md`、`scripts/check_acceptance_matrix.py`、`tests/unit/test_acceptance_matrix.py`；按真实发现修改相关实现/测试、`PLAN.md`、`AGENT_LOG.md`、`REFLECTION_NOTES.md`。

**首个失败测试：**

```python
def test_every_spec_acceptance_item_has_a_verdict_and_evidence(audit):
    assert audit.missing_items == ()
    assert all(item.verdict in {"PASS", "PARTIAL", "FAIL"} for item in audit.items)
    assert all(item.evidence for item in audit.items if item.verdict == "PASS")
```

**RED：** `uv run pytest tests/unit/test_acceptance_matrix.py -q`，预期因审计矩阵/解析器不存在或验收项未覆盖而失败。

**实现：** 从 SPEC AC-A 至 AC-F 和 Definition of Done 建立可追溯矩阵；每项记录 PASS/PARTIAL/FAIL、证据路径/命令/时间、责任任务和备注。FAIL/重要 PARTIAL 不直接改低标准，而是追加边界明确的 TDD 修复子任务、走分支/PR/两阶段审查并重新运行对应验证。

**GREEN 条件：** 无未分类条目；每个 PASS 有当前证据；所有 FAIL 和重要 PARTIAL 已修复并重验，或因真实外部条件准确记录为 blocker，不能声称 READY。

**重构：** 去重证据索引，矩阵生成器不自动把“文件存在”视为功能通过。

**最终命令：** `uv run pytest tests/unit/test_acceptance_matrix.py -q && uv run python scripts/check_acceptance_matrix.py SPEC.md docs/audits/FUNCTIONAL_AUDIT.md`

**并行：** 否。**依赖：** T1–T21。**对应验收标准：** SPEC 全部 AC 与 DoD 的 Functional Audit。**分支：** `audit/22-functional`。**计划提交：** `audit: verify functional acceptance criteria`。**实际提交：** `abb33e036965f877a860ad5916f4b23ea7ffa417`（`audit: verify functional acceptance criteria`）；审查修复轮 1 为 `22d587beb68170ab4af79a7665d1942881700499`（`fix: bind functional audit evidence contracts`）；修复轮 2 为 `86be4968ed3b6abf14c3d058f22409a923e33f1f`（`docs: keep functional audit statistics current`）。**实际状态：** 本地实现与验证完成；修复轮 1 将历史浏览器边界漂移相关项降级后，矩阵为 29 PASS / 11 PARTIAL / 0 FAIL，结论保持 `PARTIALLY_READY`；修复轮 2 将所有 current/final 过程文档统计与该矩阵对齐，并将旧 34/6 输出明确标记为已取代的 pre-review 历史。

### 任务 23：Engineering Audit 与高风险缺陷闭环

**目标：** 独立审查架构、类型、依赖、性能、异步、安全、Secret、日志、可观测性、测试隔离、可访问性和可复现构建，清零 Critical 与 High。

**文件：** 新建 `docs/audits/ENGINEERING_AUDIT.md`、`scripts/check_engineering_audit.py`、`tests/unit/test_engineering_audit.py`；按真实发现修改实现/测试、`PLAN.md`、`AGENT_LOG.md`、`DECISIONS.md`、`REFLECTION_NOTES.md`。

**首个失败测试：**

```python
def test_engineering_audit_has_no_open_critical_or_high(audit):
    assert [finding for finding in audit.open_findings if finding.severity in {"Critical", "High"}] == []
```

**RED：** `uv run pytest tests/unit/test_engineering_audit.py -q`，预期审计记录不存在或开放高风险问题导致失败。

**实现：** 结合静态检查、依赖/镜像漏洞扫描、威胁模型、测试质量和运行指标列出带证据的发现；每个修复用新的 RED 测试复现，按 TDD、独立分支/PR、规格审查和质量审查闭环。重要 Medium 尽量修复，保留未修复理由。

**GREEN 条件：** Critical=0、High=0；重要 Medium 已关闭或有风险接受理由；完整 verify、secret scan、依赖/镜像扫描重新通过。

**重构：** 将重复审计命令纳入一键验证，但保留工具原始版本与时间，避免只写结论。

**最终命令：** `pwsh -File scripts/verify.ps1; if ($LASTEXITCODE) { exit $LASTEXITCODE }; uv run python scripts/check_engineering_audit.py docs/audits/ENGINEERING_AUDIT.md`

**并行：** 否。**依赖：** T22。**对应验收标准：** AC-E、AC-F 与 DoD 中无 Critical/High、全验证、Secret 和构建要求。**分支：** `audit/23-engineering`。**计划提交：** `audit: close engineering risks`。**实际提交：** `31b2351fcf308b4aeb3ce8b1931afafe3350522d`、`07cf82687df5fa4adba9448c1fbaf1a81871a29e`、严格材料门 `a240f64bcd57a34818356805b9a177086668752c`、最终证据绑定 `f697d13`、合并结果污染修复 `acb2cb09e7c62e104ef64331f105514d6ce3016a`。10 个 finding 为 4 High FIXED、2 Medium FIXED、4 Medium BLOCKED、0 OPEN。**实际状态：** Task 23 严格 completion checker 会读取并复算 retained raw/package/VEX/inventory/tar/release/DB/image 材料；Functional Audit 为 `28 PASS / 12 PARTIAL / 0 FAIL`，独立最终复审无 Critical/Important/Minor，锁定 Linux 最终为 `755 passed, 1 skipped`，分支已推送并建立 GitHub 草稿 PR #1。Task 24、正式离线 Dockerfile 重建、远程 CI、公网/目标机、当前浏览器 E2E 与学生人工验收仍待外部或后续阶段。

**Task 23 review round 1:** Review fixes harden independent RED/GREEN evidence,
the complete offline security manifest, trusted no-build runtime identities,
safe 500/background-failure observability, waiting-only queue metrics, and
cleanup-only reporting. Functional truth is now `28 PASS / 12 PARTIAL / 0 FAIL`;
frontend type/build remains NOT_RUN, and the locked Linux/current security
chains must be green before the review follow-up is closed.

**Review closure:** The follow-up remained open through the two truthful
locked-Linux failures. It closed only after the fresh offline security chain,
trusted no-build smoke, `728 passed` locked Linux run, static/type,
Secret/license, lifecycle synthetics, and both audit CLIs were green. External,
browser/frontend-build, remote-CI, and Task 24 work remains open. Review commit:
`07cf82687df5fa4adba9448c1fbaf1a81871a29e` (`fix: harden engineering audit evidence`).

### 任务 24：Product Audit、最终验证与交付报告

**目标：** 以首次使用者身份走完整产品流程，修复严重体验问题，随后运行最新全量验证并如实输出 READY 或 PARTIALLY READY。

**文件：** 新建 `docs/audits/PRODUCT_AUDIT.md`、`DELIVERY_REPORT.md`、`REFLECTION.md`（仅目录与学生写作模板）、`scripts/check_delivery_report.py`、`tests/unit/test_delivery_report.py`；修改 `PLAN.md`、`AGENT_LOG.md`、`BLOCKERS.md`、`REFLECTION_NOTES.md`、`README.md`。

**首个失败测试：**

```python
def test_delivery_status_matches_evidence(report):
    if report.status == "MUSEECHO V1 READY":
        assert report.blocking_reasons == ()
        assert report.all_definition_of_done_items_have_current_pass_evidence
```

**RED：** `uv run pytest tests/unit/test_delivery_report.py -q`，预期报告不存在或状态缺少证据。

**实现：** 用真实浏览器完成首次进入→上传→等待→DNA→结构地图→和弦→片段问答→错误→再次上传，并检查 onboarding/loading/error/empty/hierarchy/readability/interaction/evidence/responsive；严重问题按 TDD 回流修复。然后使用 `verification-before-completion` 从干净状态重跑测试、lint、typecheck、build、Docker、E2E、核心用户流并记录命令/退出码/摘要。`DELIVERY_REPORT.md` 覆盖用户要求的 17 节和学生最终检查表；`REFLECTION.md` 只建模板，不代写学生反思。

**GREEN 条件：** 产品审计严重问题已关闭；报告每项结论有最新证据。只有所有 DoD 均满足才写 `MUSEECHO V1 READY`；任一外部条件或验收未完成则写 `MUSEECHO V1 PARTIALLY READY` 并精确列阻因。

**重构：** 把产品回归步骤固化为 Playwright helper，不把主观“看起来不错”转换成 PASS；交付报告引用证据而不复制敏感日志。

**最终命令：** `pwsh -File scripts/verify.ps1; if ($LASTEXITCODE) { exit $LASTEXITCODE }; pwsh -File scripts/container-smoke.ps1; if ($LASTEXITCODE) { exit $LASTEXITCODE }; uv run python scripts/check_delivery_report.py DELIVERY_REPORT.md`

**并行：** 否。**依赖：** T23。**对应验收标准：** AC-A 至 AC-F、完整 DoD、Product Audit、最终 Verification 与学生保留验收。**分支：** `audit/24-product-delivery`。**计划提交：** `docs: publish verified MuseEcho delivery report`。**实际提交：** 待执行。

## 4. 计划验收清单

- [x] 覆盖 SPEC 的上传、任务、DSP/MIR、Music DNA、同步地图、乐理、Evidence Q&A、隐私、Secret、Docker、双 CI、腾讯云部署与三轮审计。
- [x] 全部 24 个任务都有明确目标、文件、首个失败测试、RED、GREEN、重构、最终命令、依赖、并行判断、对应验收标准、分支和提交意图。
- [x] 关键接口、时间单位、置信度/unknown、证据白名单、数据源标记和删除顺序无占位符。
- [x] 真实外部条件（第二类 Agent、GitHub/GitLab CI、腾讯云账号/域名/SSH、公网实测、人工验收）保持为未来门禁，不声称已发生。
- [x] 用户审阅并批准本计划。
- [x] 第二类全新 Agent 完成真实 cold-start，结果已回写，修正实现通过独立复审并由用户批准合并。
- [x] 用户已明确触发 `HUMAN_APPROVAL.md`；该文件作为本次 SPEC/PLAN 修订提交的直接后续提交生成并引用其哈希。

## 5. 实施记录

### Tasks 1–2：工程骨架与领域/SQLite 基线

- **分支：** `validation/opencode-cold-start`。
- **RED/审查：** 原始提交 `1a3545d` 的全量 Ruff、仓储/外键/级联、领域不变量、UTC 与干净 checkout 探针失败，未被接受。
- **GREEN：** 修正提交 `07d135e`；39 个 Python 测试、Ruff、mypy、fresh Alembic upgrade/check、Node 22 前端测试/typecheck/build 和 npm audit 通过。
- **审查：** 三轮独立复审后 Critical/Important/Minor 均为 0。
- **合并：** 用户明确选择本地合并；`a2d7af5` 合入 `main`。本次 cold-start 特例没有 PR，已如实记录；任务 3 起恢复独立分支和 PR 协议。
- **遗留：** Tasks 3–24 未开始；外部 CI、腾讯云部署和最终学生验收仍是未来证据。
