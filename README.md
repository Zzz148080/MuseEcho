# MuseEcho

MuseEcho V1 是一个 Evidence First 音乐理解应用。当前已完成工程/持久化骨架、
分析能力访问控制和本地供应商 Secret 管理；完整产品继续按 `PLAN.md` 实施。

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

健康检查为 `GET http://127.0.0.1:8000/api/health`。上传、真实音频分析、前端产品界面
及部署等后续能力仍按 `PLAN.md` 的任务 5–24 实施。

## 供应商 Secret

本机 API Key 只写入操作系统凭据库，CLI 通过隐藏提示读取，不接收命令行明文参数：

```powershell
uv run museecho secret set
uv run museecho secret status
uv run museecho secret update
uv run museecho secret clear
```

`status` 只显示来源和是否已配置。`MUSEECHO_PROVIDER_BASE_URL` 与
`MUSEECHO_PROVIDER_MODEL` 是非秘密配置；容器可设置
`MUSEECHO_PROVIDER_SECRET_FILE`，指向仓库外的绝对只读挂载文件。不要把 API Key
写入 `.env`、仓库文件、命令行参数或日志。
