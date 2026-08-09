# Task 20 暂停交接记录

更新时间：2026-08-09（Asia/Shanghai）

## Git 状态

- 分支：`feat/20-production-delivery`
- worktree：`D:\智软工程师大项目\.worktrees\feat-20-production-delivery`
- 基线：`main@7920a513eeb4b896eac849c2d5870e6051cf8631`
- Task 20 尚未完成、尚未审查为 READY、尚未推送、尚未合并 `main`。
- 主工作树受保护的未跟踪目录 `ai4coding-agentos-lab/` 与 `docs/input/` 未读取、未修改、未提交。

## 已完成的实现

- 新增非 root 多阶段 `Dockerfile`、`compose.yaml`、Caddy HTTPS 同源网关、只读 Secret 准备容器、持久化数据卷和容器健康检查。
- 新增生产运行时装配 `src/museecho/runtime.py`，连接真实仓储、加密音频、单工作队列、上传、分析、解释、到期清理与安全关闭。
- 新增 GitHub Actions、GitLab CI、一键验证脚本、Secret 扫描、容器冒烟、第三方声明、`.dockerignore`，并更新中文 README 与 `.env.example`。
- 容器冒烟使用动态端口和独立 `COMPOSE_PROJECT_NAME`，只清理本次 smoke 的容器与卷；覆盖 HTTPS 健康、真实 WAV 上传、完成轮询、重启持久化、明文音频不落盘和镜像历史不含密钥。
- 前端清洁 Docker 构建暴露 `node:fs` 类型依赖缺失；已在 `frontend/package.json` 直接声明 `@types/node ^22.0.0` 并更新锁文件到 `22.20.1`。网关镜像随后成功构建。
- 删除未使用的 `# syntax=docker/dockerfile:1.7`，避免每次构建额外访问 Docker Hub frontend 授权端点。
- `scripts/container-smoke.ps1` 已从每次强制 `build --pull` 改为普通 `build`：清洁主机仍会拉取缺失镜像，已有缓存不会被强制重复拉取。
- Debian FFmpeg 安装已加入 `Acquire::Retries=5` 的有限重试；此项在暂停前尚未重新验证成功。

## 已通过的验证证据

暂停前、在最后几项 Docker/前端依赖修订之前，统一非容器验证曾完整 exit 0：

- `uv lock --check`：通过。
- Ruff format/check：通过（76 个 Python 文件）。
- mypy：45 个源文件通过。
- 后端：`516 passed, 2 skipped`。
- 前端 Vitest：`66 passed`；typecheck 与 production build 通过。
- Playwright：真实 HTTPS Chrome `4 passed`。
- 根目录与前端 `npm audit --audit-level=high`：均为 `0 vulnerabilities`。
- Secret 扫描：164 个 tracked 文件通过。
- 生产运行时定向测试：`9 passed`。
- Compose 配置、YAML 与 PowerShell 语法解析通过。
- `museecho-gateway:local` 已真实构建；镜像用户为 `10001:10001`。
- `python-builder` 目标已真实构建；基础镜像 digest 为 `sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2`。

注意：因为随后修改了前端锁文件、Dockerfile 与冒烟脚本，以上全套验证必须在恢复后重新执行，不能直接作为最终交付结论。

## 当前未解决问题

1. `museecho-app:local` 尚未成功生成。最后一次无重试的 app 构建在安装 Debian FFmpeg 时下载 193 个包（131 MB，安装后约 473 MB），耗时约 14 分 45 秒，多个包从 `deb.debian.org` 返回 `502 Bad Gateway`，最终 apt exit 100。
2. 已为 apt 加入 `Acquire::Retries=5`，但用户要求暂停时，重建尚未形成有效日志或通过证据；必须从这里继续验证。
3. 完整容器 smoke 尚未通过。首次执行确认网关镜像成功，但 app 构建未完成。
4. 两个最终镜像的 Trivy HIGH/CRITICAL 扫描尚未运行。
5. 依赖修订后的完整 `scripts/verify.ps1 -SkipInstall` 尚未重跑。
6. Task 20 尚未做最终聚焦审查、READY 判定、正式提交整理、推送、合并与 main 合并态复验。

## 已确认的坑与原因

- 本机根目录先安装了 `@types/node`，npm hoisting 掩盖了前端自身未声明依赖；只有清洁 Docker `frontend npm ci` 能稳定复现。直接依赖已补齐。
- Dockerfile 的远程 syntax frontend 会在项目层执行前请求 Docker Hub token；本机曾报 TLS handshake timeout。项目没用专属语法，故已删除该声明。
- `docker compose build --pull` 同时处理多个服务时曾长时间无输出；显式 `docker pull python:3.12.13-slim-bookworm` 数秒成功，证明不是固定基础镜像不存在。
- Docker 导出 Python builder 层本身约需 60 秒；不要把短暂无输出误判成死锁。
- 真正最慢的是 Debian FFmpeg 依赖下载；日志显示 CDN 多次 502。已加有限重试，不应通过跳过 FFmpeg、改用不受控镜像源或放宽 smoke 来规避。
- 当前命令执行器常在 Docker 子进程结束后才返回全部文本。需要诊断长构建时，可将 stdout/stderr 重定向到已忽略的 `tmp/docker-debug/` 并轮询日志。
- 在受限会话直接访问 `C:\Users\P\.docker` 会被拒绝，真实 Docker 命令需要既有的受控提升权限。
- 即使只执行 `docker compose build app`，Compose 也会解析 `secret-init` 的卷，因此需要临时设置一个仓库外绝对 `MUSEECHO_SECRETS_DIR`；build 本身不会读取该密钥目录。
- 宿主 Node 是 24，而项目/CI 固定 Node 22.23；宿主 npm 的 `EBADENGINE` 警告不是 Node 22 构建失败，但最终结论以 Docker/CI Node 22 为准。

## 恢复顺序

1. 核对本文件所述分支/worktree，并确认 `git status` 只有 Task 20 文件。
2. 使用当前 Dockerfile 重建 `museecho-app:local`，给 Debian 下载至少 30 分钟有界时间并保留纯文本日志；验证 `Acquire::Retries=5` 是否闭环 502。
3. 检查 app 与 gateway 镜像 `Config.User` 都为 `10001:10001`。
4. 运行 `scripts/container-smoke.ps1`；此时应复用已构建镜像，验证 HTTPS、真实任务、重启持久化和密文边界。
5. 对两个镜像运行 Trivy `HIGH,CRITICAL` 且 `--ignore-unfixed` 的硬门禁；若失败，按具体 CVE 处理，不做 blanket ignore。
6. 重跑完整 `scripts/verify.ps1 -SkipInstall`，包括后端、前端、E2E、审计与 Secret 扫描。
7. 重新暂存所有 Task 20 文件，执行 `git diff --check`、本地聚焦审查并修复到 READY。
8. 更新 `PLAN.md` 实际提交与 `AGENT_LOG.md`，推送功能分支、合并并复验 `main`、推送 `main`，保留分支和 worktree。

## 暂停状态

- 当前没有运行中的 MuseEcho 容器。
- 当前没有遗留的 MuseEcho Docker build 客户端。
- Docker Desktop 仍在运行，但没有继续执行项目工作。
- `tmp/docker-debug/` 与 `tmp/npm-cache/` 都被 `.gitignore` 忽略，不会提交。

## 2026-08-10 完成记录

- **提交：** `70dde35`（`build: package and verify production distribution`）。未推送、未合并，且没有声称 GitHub Actions 或 GitLab CI 已运行。
- **最终容器证据：** `scripts/container-smoke.ps1` 在本机已有 Windows PowerShell 中完成，显式记录 exit code `0`。它重新构建 app/gateway，验证 HTTPS health、真实 WAV 上传与分析、重启后的持久状态、持久卷中无明文 WAV/MP3，以及镜像历史无测试 KEK。烟测资源已由脚本清理。
- **安全证据：** fresh tracked-file Secret scan 通过（165 个文件）；两个最终镜像均为 `10001:10001`。使用现有 Trivy 0.70.0 缓存数据库和 `--ignore-unfixed --severity HIGH,CRITICAL` 重新扫描，app 和 gateway 均为 0 个 HIGH/CRITICAL 发现。
- **主机验证边界：** 主机 PATH 没有 `ffmpeg`/`ffprobe`，而 app 镜像中两者均位于 `/usr/bin`。因此本机 Python 全量结果为 `508 passed, 2 skipped, 8 failed`；八项均为真实音频工具缺失导致，未修改测试或下载工具规避。Ruff format/check、mypy、66 个前端测试、前端/E2E TypeScript、production build 和两次 npm audit 均通过。`uv` 和 `pwsh` 也不在受限主机 PATH，故完整 `verify.ps1 -SkipInstall` 只能在第一步准确报告缺少 uv；CI 将安装锁定 uv 和 FFmpeg。
