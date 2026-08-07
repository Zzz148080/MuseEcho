# MuseEcho

MuseEcho V1 是一个 Evidence First 音乐理解应用。本分支仅保存任务 1–2 的
cold-start 骨架与验证结果，不代表完整产品已经实现。

## 工具链

- Python 3.12
- uv 0.11.29
- Node.js 22.22.2
- npm 10.9.8

Windows 可使用 Python 安装 uv：

```powershell
py -3.12 -m pip install --user uv==0.11.29
```

## 从干净 checkout 初始化

```powershell
uv sync --extra dev
npm.cmd --prefix frontend ci
uv run alembic upgrade head
```

迁移和应用数据库初始化会自动创建被 Git 忽略的 `data/` 目录，不需要手工创建。

## 验证

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run typecheck
npm.cmd --prefix frontend run build
```

## 本地后端

```powershell
uv run uvicorn museecho.app:create_app --factory --reload
```

健康检查为 `GET http://127.0.0.1:8000/api/health`。当前只实现工程骨架、领域模型和
SQLite 仓储；上传、真实音频分析、前端产品界面及部署仍按 `PLAN.md` 的任务 3–24 实施。
