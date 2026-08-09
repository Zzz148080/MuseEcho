# MuseEcho 第三方软件通知

本文是发行审计清单，不替代各项目许可证全文或法律意见。版本以 `uv.lock`、
`package-lock.json`、`frontend/package-lock.json` 和 `Dockerfile` 为准；传递发行物时必须
同时保留基础镜像内的许可证目录和上游通知。

## Python 运行时直接依赖

| 组件 | 许可证（上游元数据） |
|---|---|
| FastAPI、Pydantic、SQLAlchemy、argon2-cffi、keyring | MIT |
| Click、httpx、Uvicorn | BSD-3-Clause |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| librosa | ISC |
| NumPy | BSD-3-Clause 及其二进制包所列第三方许可 |
| SciPy | BSD-3-Clause 及其二进制包所列 BLAS/LAPACK/GCC Runtime 许可 |
| python-multipart | Apache-2.0 |
| Alembic | MIT |

间接 Python 依赖以 `uv.lock` 为唯一版本清单，其许可证文件保留在镜像
`/app/.venv/**/dist-info/licenses` 或相应包元数据中。

## 前端、测试与构建工具

| 组件 | 许可证 |
|---|---|
| React、React DOM、TanStack Query、Vite、Vitest、TypeScript | MIT |
| Playwright | Apache-2.0 |
| Testing Library 家族、jsdom 及其他 npm 间接依赖 | 以两个 package-lock 的 `license` 字段及包内 LICENSE 为准 |

## 容器和系统组件

| 组件 | 许可证/注意事项 |
|---|---|
| Python Docker Official Image、Node Docker Official Image | 镜像内各 Debian 软件包许可证；基础镜像说明见 Docker Official Images |
| Alpine Linux | 各 APK 软件包许可证 |
| Caddy | Apache-2.0；发行镜像应保留上游版权和许可证 |
| FFmpeg（Debian 包） | LGPL-2.1-or-later，并可能启用受 GPL 约束的可选组件；以构建配置和 `/usr/share/doc/ffmpeg/copyright` 为准 |
| OpenSSL、CA certificates、系统 C/C++ 运行库 | 以镜像内 `/usr/share/doc/*/copyright` 或 `/usr/share/licenses` 为准 |

FFmpeg 的实际许可证取决于编译选项。分发前应在最终 `app` 镜像执行 `ffmpeg -L` 和
`ffmpeg -buildconf`，保存输出，并按其报告履行 LGPL/GPL 的通知、可替换/重链接条件及对应
源码提供义务。

## 审计与更新要求

1. `npm audit --audit-level=high` 必须对根目录和 `frontend/` 均为零高危失败。
2. `python scripts/license_audit.py` 必须确认 `uv.lock` 名称/版本与
   `scripts/license-policy.json` 精确一致，并拒绝 npm lock 中缺失或未批准的许可证。
3. CI 使用固定 Trivy 版本扫描两个最终镜像，对任何 HIGH/CRITICAL 漏洞失败且不使用
   未修复项豁免参数。
4. 每次修改任一依赖锁或基础镜像版本，都要重新核对本通知、上游 LICENSE 和镜像内通知。
5. MuseEcho 自身尚未声明开源许可证；本文件不授予 MuseEcho 源码的使用或再分发权利。
