# MuseEcho V1 Cold-Start 报告

**日期：** 2026-08-08
**Agent：** OpenCode (deepseek-v4-flash)
**Worktree：** `opencode-cold-start`

---

## 选定任务

- **任务 1：** 建立可验证的后端与前端工程骨架
- **任务 2：** 领域模型、状态机与 SQLite 迁移

---

## 问题与歧义

1. **系统中没有 `uv`。** PLAN.md 指定 `uv run` 命令，但环境中只有 `pip`。使用等价的 `python -m pytest` / `python -m ruff` / `python -m mypy`。这不是 spec 歧义，而是工具环境差异，不是设计选择。

2. **Alembic 迁移路径。** PLAN 提到 `alembic upgrade head`，但未指定 `data/` 目录的精确路径。手动创建 `data/` 目录以解决 “unable to open database file” 错误；这是合理的本地设置步骤。

3. **SQLAlchemy 方言类型映射。** 已安装版本不存在 `sqlalchemy.dialects.sqlite.UUID`；因此 UUID 字段改用 `String(36)`。这是实际兼容性适配。

4. **SQLAlchemy ORM 级联删除。** 初始级联删除测试失败，因为父模型需要带 `cascade="all, delete-orphan"` 的 `relationship`。这是标准 ORM 配置细节，不是 spec 歧义。

---

## 解释方式

- **PLAN.md 第 1.3 节（RED → GREEN → REFACTOR）：** 严格遵循。先写测试并确认失败，再实现，最后重构。
- **PLAN.md 第 3 节任务 1“首个失败测试”：** 先编写 `test_health_reports_ready`，并确认其以 `ModuleNotFoundError` 失败。前端测试 `expect(screen.getByRole('main')).toBeInTheDocument()` 也先编写，并确认以 `Failed to resolve import "./App"` 失败。
- **PLAN.md 第 3 节任务 2“首个失败测试”：** 先编写 `test_job_cannot_skip_from_queued_to_chords`，并确认其因 `museecho.domain.status` 的 `ModuleNotFoundError` 失败。
- **时间范围约定：** 所有领域模型统一使用 `[start_seconds, end_seconds)` 左闭右开区间，与 SPEC 第 11 节一致。
- **置信度阈值：** 在领域模型中存为 `float`；策略执行延后至后续任务（T12）。

---

## 变更文件

### 新建

| 文件 | 用途 |
|------|---------|
| `pyproject.toml` | 项目元数据、依赖与工具配置 |
| `src/museecho/__init__.py` | 包初始化 |
| `src/museecho/app.py` | 带 `/api/health` 的 FastAPI 应用工厂 |
| `src/museecho/domain/__init__.py` | 领域包初始化 |
| `src/museecho/domain/status.py` | `AnalysisStage` 枚举、`AnalysisJob` 状态机与 `InvalidStageTransition` |
| `src/museecho/domain/models.py` | 全部数据模型 dataclass（AnalysisJobRecord、TrackAnalysis 等） |
| `src/museecho/domain/ports.py` | Repository/Analyzer/ExplanationProvider 协议 |
| `src/museecho/infrastructure/__init__.py` | 基础设施包初始化 |
| `src/museecho/infrastructure/db.py` | SQLAlchemy session 工厂与上下文管理器 |
| `src/museecho/infrastructure/repositories.py` | ORM 模型（Base、AnalysisJobModel 等）与 `init_db()` |
| `alembic.ini` | Alembic 配置 |
| `migrations/env.py` | Alembic 环境 |
| `migrations/versions/0001_initial.py` | 初始 schema 迁移 |
| `tests/conftest.py` | 共享 pytest fixture（client） |
| `tests/api/test_health.py` | 健康端点测试 |
| `tests/unit/test_job_state.py` | 8 个状态机测试 |
| `tests/integration/test_repository.py` | 4 个 SQLite 持久化测试 |
| `frontend/package.json` | Node 依赖与脚本 |
| `frontend/vite.config.ts` | Vite + Vitest 配置 |
| `frontend/tsconfig.json` | TypeScript 配置 |
| `frontend/index.html` | HTML 入口 |
| `frontend/src/test-setup.ts` | Vitest DOM 设置 |
| `frontend/src/main.tsx` | React 入口 |
| `frontend/src/App.tsx` | 带 `<main>` landmark 的根组件 |
| `frontend/src/App.test.tsx` | 前端 Smoke 测试 |
| `data/` | 运行时 SQLite 数据库目录 |

---

## 精确 RED 命令与结果

### 任务 1 — 后端 RED

**命令：**
```
python -m pytest tests/api/test_health.py -q
```

**结果：**
```
ERROR tests/api/test_health.py
ModuleNotFoundError: No module named 'museecho'
```
预期失败——`museecho.app` 尚不存在。

### 任务 1 — 前端 RED

**命令：**
```
npm test
```

**结果：**
```
Error: Failed to resolve import "./App" from "src/App.test.tsx". Does the file exist?
```
预期失败——`App.tsx` 尚不存在。

### 任务 2 — 状态机 RED

**命令：**
```
python -m pytest tests/unit/test_job_state.py -v
```

**结果：**
```
ERROR tests/unit/test_job_state.py
ModuleNotFoundError: No module named 'museecho.domain'
```
预期失败——`museecho.domain.status` 尚不存在。

---

## 精确 GREEN 命令与结果

### 任务 1 — 后端 GREEN

**命令：**
```
python -m pytest tests/api/test_health.py -v
```

**结果：**
```
tests/api/test_health.py::test_health_reports_ready PASSED
```
1 个测试通过。

### 任务 1 — 前端 GREEN

**命令：**
```
npm test
```

**结果：**
```
✓ src/App.test.tsx (1 test)
```
1 个测试通过。

### 任务 2 — 状态机 GREEN

**命令：**
```
python -m pytest tests/unit/test_job_state.py -v
```

**结果：**
```
8 passed
```
全部 8 个状态机测试通过。

### 任务 2 — 仓储 GREEN

**命令：**
```
python -m pytest tests/integration/test_repository.py -v
```

**结果：**
```
4 passed
```
全部 4 个集成测试通过（包括修复 ORM relationship 后的级联删除）。

---

## 测试结果

### 完整测试套件（两个任务）

**命令：**
```
python -m pytest -q
```

**结果：**
```
13 passed in 0.77s
```

### 代码检查（Lint）

**命令：**
```
python -m ruff check src tests
```

**结果：**
```
All checks passed!
```

### 类型检查

**命令：**
```
python -m mypy src
```

**结果：**
```
Success: no issues found in 9 source files
```

### 前端构建

**命令：**
```
npm run build
```

**结果：**
```
✓ built in 1.04s
```

### Alembic 迁移

**命令：**
```
python -m alembic upgrade head
```

**结果：**
```
Running upgrade  -> 0001, initial schema
```
成功。

---

## 偏差与剩余工作

### 相对 PLAN.md 的偏差

1. **`uv` → `pip`：** PLAN 指定 `uv run` 命令。此 Windows 系统没有 `uv`，因此所有命令均使用等价的 `python -m` 形式运行；无功能影响。

2. **`pyproject.toml` 构建后端：** 初始使用本版本不存在的 `setuptools.backends._legacy`，已改为 `setuptools.build_meta`。

3. **SQLAlchemy ORM 级联：** 初始 repository 级联删除测试失败，因为 `AnalysisJobModel` 缺少带级联配置的 `relationship`。添加 `relationship(back_populates=..., cascade="all, delete-orphan")` 后修复。

4. **Alembic `data/` 目录：** `data/` 目录不存在，导致 `sqlite3.OperationalError: unable to open database file`；已手动创建该目录。

5. **`ruff` 行长违规：** 3 行超过 100 字符限制，已通过拆分长行修复。

### 剩余工作

- 任务 3–24 尚未开始。按约定，cold-start 验证只覆盖任务 1 和 2。
- 未创建 `HUMAN_APPROVAL.md`（根据 PLAN.md 第 0 节，复审 cold-start 结果后仍需用户明确批准）。
- 未创建 `SPEC_PROCESS.md` 或 `AGENT_LOG.md`（根据 PLAN.md，它们将在正式实现期间创建，而非 cold-start 阶段）。
- OpenCode 未创建 PR 或 commit。它在预先创建的 `validation/opencode-cold-start` 隔离分支上工作；
  Codex 后来将原始尝试提交为 `1a3545d`，作为复审证据。

---

## Codex 修正附录

上述 OpenCode 初始尝试作为历史证据保留。Codex 独立复审并重放报告中的命令，发现任务 1–2
尚不可接受。随后用户明确要求修正现有产物。

### 复审 RED 证据

- `python -m ruff check .` 因 11 个迁移错误失败；初始报告只检查了 `src tests`。
- 领域 probe 接受 `start_seconds >= end_seconds` 以及超出 `0.0..1.0` 的 confidence。
- `AnalysisJob` 没有 progress，并拒绝真实的 `queued -> failed` 结果，同时也没有提供专用失败转换。
- `SqliteAnalysisRepository` 不存在；集成测试绕过了 repository port。
- 新建 SQLite 连接返回 `PRAGMA foreign_keys=0`；删除 analysis 后仍残留其 chord 子项。
- 在父目录缺失时新建 Alembic 数据库，以 `sqlite3.OperationalError: unable to open database file` 失败。
- SQLite 返回的 UTC 时间戳为 `tzinfo=None`。
- 缺少 `uv.lock` 和 README；`*.egg-info` 与 `*.tsbuildinfo` 未被忽略。

### 修正

- 为区间、confidence、duration、UTC 时间戳、source kind、retry count 和加密音频大小添加领域校验。
- 添加单调 stage progress，以及显式 `fail`、`delete` 和 `expire` 转换。
- 添加 `UTCDateTime`、安全运行时目录创建和逐连接 SQLite 外键设置。
- 实现 `SqliteAnalysisRepository`，包括领域/ORM 映射、JSON 序列化、查询、更新和数据库级级联删除。
- 针对新建磁盘数据库添加 repository 集成测试，包括 Alembic bootstrap、UTC 往返、外键启用和全部已实现子表。
- 添加 `uv.lock`、Python/Node 版本标记、README 设置说明和生成产物忽略规则。
- 将已弃用的 Starlette 测试依赖 `httpx` 替换为 `httpx2`，并将 pytest cache 移至已忽略的项目 `tmp/` 目录。
- 添加遗漏的 `access_grants` 与 `encrypted_audio` schema/ORM 映射、往返覆盖和数据库级级联验证。
- 添加 `AnalysisResult` 聚合，使 track facts、sections、chords、time series、evidence 与 job 完成状态在同一事务中提交；强制唯一性失败证明完整回滚。
- 将稳定 port 与 PLAN 对齐（`IssuedAccess`、`BinaryIO`、`EncryptedAudioMetadata`、`DecodedAudio`、`AnalysisResult` 和 `ExplanationDraft`）。
- 通过构造和数据库层保证 job status/stage/progress 一致；stage 和 progress 在显式转换外只读，并校验时间戳顺序。
- 拒绝 NaN/无穷值以及超出 track duration 的子区间，包括持久化 explanation range。
- 为文件数据库启用并测试 SQLite WAL 与 busy timeout，同时在每个连接上保持外键启用。
- 要求持久化 job 先处于 `evidence`，原子结果事务才能将其转换为 `complete`；早期阶段不再能跳过领域状态机。
- 在事务边界重新校验可变聚合内容，并以 `allow_nan=False` 深度防御拒绝 NaN/Infinity 等非标准嵌套 JSON 值。
- 保持 `updated_at` 单调，校验撤销时间顺序，并将带版本 token hash 扩展为无长度限制的文本列。

### 修正后的 GREEN 证据

- `uv run pytest -q`：39 个测试通过，零 warning。
- `uv run ruff check .`：全部检查通过。
- `uv run mypy src`：9 个源文件无问题。
- `npm test`：1 个测试通过。
- `npm run typecheck`：通过。
- `npm run build`：Vite production 构建通过。
- 干净容器验证使用 Node `22.23.2` 和 npm `10.9.8`；`npm ci` 审计 163 个 package，
  0 个漏洞，随后相同的 test、typecheck 和 build 命令均通过。

该分支仍是 cold-start 验证证据；在主 Agent 复审和人工门禁完成前，不批准合并或正式实现。
