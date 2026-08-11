# MuseEcho

MuseEcho V1 是一款 Evidence First（证据优先）的交互式音乐理解应用。它用确定性的
DSP/MIR 管线分析用户上传的 WAV/MP3，生成节拍、能量、调性、结构、和弦、波形和确定性
乐理证据；可选 LLM 只能解释已经通过置信度门的结构化证据，不能生成或改写音乐事实。

## 核心功能

- 最大 30 MiB、最长 10 分钟的 WAV/MP3 上传、格式探测和受限解码。
- 单工作线程的可恢复分析队列，失败返回稳定错误码。
- 节拍/能量、调性、结构与大小三和弦分析；低置信结果统一为 `unknown`。
- 时间轴、波形、证据面板、确定性乐理说明和可选证据约束式 LLM 解释。
- 24 小时 capability cookie、CSRF/同源保护、加密音频存储和到期密码学删除。
- 中文桌面/移动界面、真实 HTTPS E2E、300 秒性能基准。

## 架构

```text
浏览器 ──HTTPS──> Caddy（静态前端 + 同源 /api 代理）
                         │
                         v
                   FastAPI 生产运行时
                    │      │       │
              上传/权限  单工作队列  证据约束解释
                    │      │       │
                    └──> DSP/MIR ──┘
                           │
                 SQLite + AES-GCM 分块音频
                           │
                     持久卷 /data
```

后端遵循 domain/application/infrastructure/api 分层。LLM 位于事实管线之后，只接收
`eligible_for_llm=true` 的证据及其 ID；响应若越界、无引用、格式错误或请求失败，就回退到
确定性解释。

## 技术栈

- Python 3.12.13、FastAPI、SQLAlchemy/SQLite、librosa、NumPy、SciPy、FFmpeg。
- React 19、TypeScript、Vite、TanStack Query、Vitest、Playwright。
- Caddy 2.11、Docker Compose、GitHub Actions、GitLab CI。
- uv 0.11.29、Node.js 22.23.x、npm 10。

## 目录

- `src/museecho/`：后端、DSP/MIR、乐理与生产运行时。
- `frontend/`：React 产品界面。
- `tests/`：单元、API、集成、安全、性能测试。
- `e2e/`：真实 HTTPS 浏览器测试。
- `migrations/`：Alembic 迁移。
- `scripts/`：统一验证、Secret 审计、容器 smoke 与性能基准。
- `docs/`：设计与验证资料；`SPEC.md`、`PLAN.md` 是批准的产品和实施基线。

## 环境要求

- Python 3.12、uv 0.11.29。
- Node.js `>=22.22.2 <23`、npm 10。
- FFmpeg/FFprobe 9 或兼容版本。
- 浏览器 E2E 需要 Playwright Chromium 或本机 Chrome。
- 容器运行需要 Docker Desktop/Engine 与 Compose v2。

## 安装

```powershell
py -3.12 -m pip install --user uv==0.11.29
uv sync --frozen --extra dev
npm.cmd ci
npm.cmd --prefix frontend ci
npx.cmd playwright install chromium
```

Linux/macOS 将 `npm.cmd`/`npx.cmd` 改为 `npm`/`npx`。依赖必须来自已提交的
`uv.lock` 和两个 `package-lock.json`；更新依赖后应重新运行所有审计。

## 本地运行

生产运行时要求把音频 KEK 放在仓库之外的绝对只读文件中。该文件内容是 32 个随机字节
的 Base64；它与可选模型 API Key 绝不能复用。

```powershell
$secretDir = 'D:\MuseEchoSecrets'
New-Item -ItemType Directory -Force $secretDir | Out-Null
$bytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
[IO.File]::WriteAllText("$secretDir\audio-kek", [Convert]::ToBase64String($bytes))
Set-ItemProperty "$secretDir\audio-kek" -Name IsReadOnly -Value $true

$env:MUSEECHO_DATA_ROOT = 'D:\MuseEchoData'
$env:MUSEECHO_AUDIO_KEK_FILE = "$secretDir\audio-kek"
$env:MUSEECHO_TRUSTED_ORIGINS = 'https://localhost:4173'
uv run uvicorn museecho.runtime:app --factory --host 127.0.0.1 --port 8000
```

前端开发服务器另开终端运行 `npm.cmd --prefix frontend run dev`。直接使用
`museecho.app:create_app` 只适合依赖注入测试；完整服务必须使用 `museecho.runtime:app`。

## 测试与质量门

一键入口（默认会同步锁定依赖并运行真实浏览器 E2E）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\verify.ps1
```

已安装依赖时可加 `-SkipInstall`；仅在没有浏览器的受限环境中可加 `-SkipE2E`，但这不构成
完整交付证据。单独命令包括：

```powershell
uv run pytest -q --basetemp tmp/pytest-local
uv run ruff format --check src tests
uv run ruff check .
uv run mypy src
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run typecheck
npm.cmd --prefix frontend run build
npm.cmd run typecheck
npm.cmd run e2e
```

## Docker

在仓库外创建 Secret 目录，至少包含 `audio-kek`；可选模型凭据命名为 `provider-key`。
生产 Compose 合约把宿主机固定路径 `/etc/museecho/secrets` 直接只读挂载到
`/run/secrets`，不接受环境变量改成仓库相对路径，也不会复制到 Docker 卷。应用和网关均以
UID 10001 非 root 运行，根文件系统只读。

```powershell
docker compose --profile production config --quiet
docker compose --profile production build --pull
docker compose --profile production up -d --wait
# 仅限本机内部 CA smoke；公网不得跳过证书校验。
curl.exe --fail --silent --show-error --insecure https://localhost:8443/api/health
```

浏览器使用 `https://localhost:8443`。本地发行物采用 Caddy 内部 CA，第一次访问会显示本地
证书警告；上述 `--insecure` 只用于本机健康探针。需要严格验证时，应从 Caddy 数据目录导出
本地根 CA、导入 Windows“受信任的根证书颁发机构”，再用不带 `--insecure` 的
`curl.exe`。公网部署必须使用受信任域名证书。数据保存在 `museecho_data` 卷，普通重启不会
丢失；`docker compose --profile production down --volumes` 会删除数据库和密文音频，但
不会删除外部 Secret 目录。

开发 profile 只启动绑定到回环地址的后端、只读挂载当前 `src/` 并启用 reload；前端仍按
“本地运行”章节用 Vite 启动。它使用独立的 `museecho_dev_data` 卷，不能当作生产部署：

```powershell
$env:MUSEECHO_SECRETS_DIR = 'D:\MuseEchoSecrets'
docker compose --profile development up --build app-dev
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

完整容器 smoke 会在 OS task-temp 中创建 Secret 和 Compose override（仅覆盖 smoke 的固定
Secret bind）、构建镜像、上传真实 WAV、等待分析、重启验证持久性并检查持久卷无明文音频；
成功或失败都会校验容器、卷与精确临时目录的清理：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\container-smoke.ps1
```

## 第三方模型凭据

模型完全可选；未配置时所有解释走确定性 fallback。启用时必须同时设置：

```text
MUSEECHO_PROVIDER_BASE_URL=https://provider.example/v1
MUSEECHO_PROVIDER_MODEL=<模型 ID>
MUSEECHO_PROVIDER_SECRET_FILE=/run/secrets/provider-key
```

容器外本地运行时，Secret 路径必须是仓库外的绝对只读文件。不得把 API Key 写入 `.env`、
Compose、命令行、截图、日志、Git 历史或前端变量。`scripts/secret-scan.ps1` 扫描 tracked
与未忽略的 untracked 文件、高置信凭据模式、凭据赋值中的高熵值和禁止路径，读取失败会
关闭门禁；但它不能代替平台侧密钥轮换与使用日志审计。

## 安全边界

- 原始音频只在有界临时目录短暂出现，持久化为每文件随机数据密钥的 AES-GCM 分块密文。
- 音频 KEK 和模型 API Key 分离；启动时验证 Secret 路径与只读属性。
- 访问 token 只存 Argon2id 哈希，cookie 为 Secure/HttpOnly/SameSite；写操作还需同源与
  CSRF token。
- 上传体、解码时间、时长、响应大小、LLM 超时和引用集合均有硬限制。
- 上传解码只接受 MP3，或 RIFF/WAVE 中的无压缩 PCM：无符号 8 位、little-endian 有符号
  16/24/32 位、IEEE float 32/64 位（含匹配的 WAVE_FORMAT_EXTENSIBLE 子格式）。压缩或
  歧义 RIFF codec 会在启动媒体工具前失败关闭；`ffprobe` 与 `ffmpeg` 均在输入前应用完全
  相同的 `wav,mp3` format、`file,pipe` protocol 和上述 PCM/MP3 decoder allowlist。
- WAVEFORMATEXTENSIBLE 仅在 `cbSize >= 22`、声明扩展字节有界、`0 < valid_bits <=
  container_bits`、GUID/速率/通道/block-align/byte-rate 全部一致时接受。MP3 仅支持可由非零
  bitrate index 计算帧大小的常规 MPEG Layer III；V1 明确拒绝 free-format (`0000`) MP3，因为
  锁定 FFmpeg 5.1.9 拒绝了该端到端流，不能将所有 MP3 子类型称为受支持。
- Caddy 是唯一公开入口；FastAPI 不应直接暴露公网。
- 镜像 CI 先保存不带 suppression 的完整 Trivy JSON，再核对每个 finding tuple、PURL、
  package/version/status/severity、完整 dpkg 文件清单、镜像内运行时探针，以及全部 `src/`、
  Docker/Compose、配置和依赖锁文件哈希；随后只应用逐 CVE、逐产品且有代码/测试/权威来源
  支撑的 OpenVEX。任何新增、缺失或变化条目都会关闭门禁，失败时仍保留原始审计证据；不
  使用 `--ignore-unfixed`、status/package 过滤或 blanket ignore。

## 分发与 CI

`Dockerfile` 的 `app` 与 `gateway` target 组成发行物。GitHub Actions 与 GitLab CI 都执行
Python/TypeScript 静态检查、后端/前端测试、构建、真实 HTTPS E2E、确定性许可证策略、
Secret 审计、Docker 构建和镜像漏洞门；GitLab 的后端测试 job 固定名为 `unit-test`。
`uv run python scripts/license_audit.py` 会要求 `uv.lock` 名称/版本、两个 npm lock 的完整
SHA-256 inventory，以及固定容器、构建工具、Go replacement 和 OS 包清单与人工复核策略
精确一致，并拒绝显式审批集合外的许可证。`scripts/container-pytest.ps1` 可用现有 app
镜像的 FFmpeg 运行完整 Python 套件：仓库和现有 pytest 模块只读挂载、网络关闭，不向生产
镜像加入测试工具。本地配置通过不代表远端 CI 已运行，只有对应提交的真实流水线结果才能
作为远端证据。

## 部署

单机部署应把 8080/8443 仅用于初始验证，正式环境使用域名、受信 TLS、主机防火墙、卷备份
与定期恢复演练。腾讯云安装、升级、回滚和备份脚本属于 PLAN Task 21，本任务不会伪造尚未
执行的公网部署结果。

## 已知限制

- V1 仅接受 WAV/MP3，最长 10 分钟；仅输出大小三和弦，其他和声保守为 `unknown`。
- 结构标签是可解释的相似段落标识，不等同于曲式学人工定论。
- 分析队列是单进程单工作线程，不是多租户横向扩展系统。
- 当前锁定的 Debian/FFmpeg 运行时在原始 Trivy 0.70.0 扫描中仍有 181 个无修复版本的
  HIGH/CRITICAL package 条目。发布门禁不会隐藏这份原始 inventory；它仅在精确 package
  文件与执行边界均未漂移时应用 67 条逐 CVE `not_affected` 结论。获得可用上游修复后仍应
  优先升级运行时并删除不再需要的 VEX statement。
- MP3 支持不包括 free-format bitrate index `0000`；仅支持可计算帧长度的常规 MPEG Layer III。
- 内部 CA 只适合本地 smoke；公网证书和腾讯云运行证据在 Task 21 完成。
- LLM 可用性、计费和第三方数据处理由用户选择的平台负责；MuseEcho 不把原始音频发送给
  LLM。

## 许可证

仓库目前未声明 MuseEcho 自身的开源许可证，因此默认保留全部权利，不能据此推定可再分发
或商用。第三方组件仍分别受其许可证约束，详见 `THIRD_PARTY_NOTICES.md`；发行镜像还包含
Debian/Alpine、FFmpeg 与 Caddy，分发者必须履行对应通知及源码提供义务。
