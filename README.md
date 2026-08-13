# MuseEcho

<!-- TASK24-CURRENT-STATUS:START -->
## Task 24 current status

Current delivery status is `MUSEECHO V1 PARTIALLY READY`. Task 24 now provides
the Product Audit, 17-section delivery report, strict validator, and a blank
student-owned reflection template; Task 24 itself is no longer a blocker.
Task 23 PR #1 is merged with GitHub quality, E2E, and distribution green.
Task 24 GitHub quality, E2E, and distribution passed at its recorded
implementation boundary. Remaining gates are GitLab, Tencent
Cloud/public/target-server smoke and rollback, formal offline build ENG-010,
controller browser observation behind trusted TLS, and student acceptance.
<!-- TASK24-CURRENT-STATUS:END -->

MuseEcho V1 是一款 Evidence First（证据优先）的交互式音乐理解应用。它用确定性的
DSP/MIR 管线分析用户上传的 WAV、MP3、FLAC、M4A、AAC、OGG 或 OPUS，生成节拍、能量、调性、结构、和弦、波形和确定性
乐理证据；可选 LLM 只能解释已经通过置信度门的结构化证据，不能生成或改写音乐事实。

## 核心功能

- 最大 30 MiB、最长 10 分钟的 WAV/MP3/FLAC/M4A/AAC/OGG/OPUS 上传、格式探测和受限解码。
- 单工作线程的可恢复分析队列，失败返回稳定错误码。
- 节拍/能量、调性、结构与大小三和弦分析；低置信结果统一为 `unknown`。
- 时间轴、波形、证据面板、确定性乐理说明和可选证据约束式 LLM 解释。
- 24 小时 capability cookie、CSRF/同源保护、加密音频存储和到期密码学删除。
- 中文桌面/移动界面、真实 HTTPS E2E、300 秒性能基准。

浏览器选择器仅列出 `.wav,.mp3,.flac,.m4a,.aac,.ogg,.opus` 这七个精确后缀。M4A
仅支持 AAC/ALAC；OGG/Ogg 系列仅支持 Vorbis/Opus（`.ogg` 对应 Vorbis，`.opus`
对应 Opus）。浏览器的 MIME 类型或文件名后缀预检不能代替服务器对容器、编解码器和
实际内容的验证。DRM 或专有加密下载明确不受支持。

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
- `DELIVERY_REPORT.md`：Task 24 的固定 17 节交付结论、证据、精确阻因和学生保留检查表。
- `docs/audits/PRODUCT_AUDIT.md`：机器可读的产品审计矩阵；控制器已真实到达健康 HTTPS 边界，但因内部 CA 未受信而保持 `CERT_TRUST_BLOCKED`。
- `REFLECTION.md`：仅供学生本人填写的空白模板，Agent 不代写或勾选。

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
的 Base64；它与可选模型 API Key 绝不能复用。Windows 开发机先创建仓库外 Secret：

```powershell
$secretDir = 'D:\MuseEchoSecrets'
New-Item -ItemType Directory -Force $secretDir | Out-Null
$bytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
[IO.File]::WriteAllText("$secretDir\audio-kek", [Convert]::ToBase64String($bytes))
Set-ItemProperty "$secretDir\audio-kek" -Name IsReadOnly -Value $true

```

浏览器开发必须使用下文 Docker development profile 的同源 HTTPS 网关；不要把 Secure cookie
降级为明文 HTTP，也不要把 FastAPI 端口直接当作浏览器入口。直接使用
`museecho.app:create_app` 只适合依赖注入测试；完整服务使用 `museecho.runtime:app`。

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
uv run python scripts/check_delivery_report.py DELIVERY_REPORT.md
```

## Docker

在仓库外创建 Secret 目录，至少包含 `audio-kek`；可选模型凭据命名为 `provider-key`。
生产 Compose 合约把宿主机固定路径 `/etc/museecho/secrets` 直接只读挂载到
`/run/secrets`，不接受环境变量改成仓库相对路径，也不会复制到 Docker 卷。应用和网关均以
UID 10001 非 root 运行，根文件系统只读。

Linux 冷启动使用下面的精确所有者和模式。目录由 `root:10001` 持有且为 `0750`，让容器 UID
10001 可遍历；两个文件由 `10001:10001` 持有且为 `0400`，没有任何写位。可选
`provider-key` 必须与 `audio-kek` 分开生成；交互读取避免把 API Key 放进 shell 历史：

```bash
sudo install -d -o root -g 10001 -m 0750 /etc/museecho/secrets

audio_tmp="$(mktemp)"
trap 'rm -f "$audio_tmp"' EXIT
umask 077
openssl rand -base64 32 | tr -d '\n' > "$audio_tmp"
sudo install -o 10001 -g 10001 -m 0400 "$audio_tmp" /etc/museecho/secrets/audio-kek

# 默认 KEK-only 启动到此为止；不创建 `provider-key`，也不要设置任何
# `MUSEECHO_PROVIDER_*` 变量。仅在启用第三方模型时执行以下命令：
provider_tmp="$(mktemp)"
trap 'rm -f "$audio_tmp" "$provider_tmp"' EXIT
IFS= read -r -s -p 'Provider API key: ' provider_key; printf '\n'
printf '%s' "$provider_key" > "$provider_tmp"
unset provider_key
sudo install -o 10001 -g 10001 -m 0400 "$provider_tmp" /etc/museecho/secrets/provider-key

# 默认诊断只检查 KEK；provider 模式才检查第二个文件。
stat -c '%u:%g %a %n' /etc/museecho/secrets /etc/museecho/secrets/audio-kek
# 期望：目录 0:10001 750；KEK 为 10001:10001 400。
if [ -f /etc/museecho/secrets/provider-key ]; then
  stat -c '%u:%g %a %n' /etc/museecho/secrets/provider-key
  # 期望：provider-key 为 10001:10001 400。
fi
```

`powershell -File scripts/test-linux-secret-contract.ps1` 会在 Linux 容器文件系统中重建这些
所有者/模式，以 UID/GID 10001 读取两个 Secret，并验证只读挂载不能写入。普通 Compose 构建只适合
本地便捷开发，不是可复核的发行物。Linux 上的生产发行与启动必须使用同一批保存的 tar：

```bash
mkdir -p tmp/image-security
export SOURCE_DATE_EPOCH=1785888000
docker buildx build --build-arg SOURCE_DATE_EPOCH="$SOURCE_DATE_EPOCH" --target app \
  --output "type=docker,name=museecho-app:local,dest=tmp/image-security/museecho-app.tar,rewrite-timestamp=true" .
docker buildx build --build-arg SOURCE_DATE_EPOCH="$SOURCE_DATE_EPOCH" --target gateway \
  --output "type=docker,name=museecho-gateway:local,dest=tmp/image-security/museecho-gateway.tar,rewrite-timestamp=true" .
python scripts/verify_release_identity.py record \
  --output tmp/image-security/release-images.json \
  --tar app=tmp/image-security/museecho-app.tar \
  --tar gateway=tmp/image-security/museecho-gateway.tar
docker load --input tmp/image-security/museecho-app.tar
docker load --input tmp/image-security/museecho-gateway.tar
docker compose --profile production config --quiet
docker compose --profile production up -d --wait --no-build
# 仅限本机内部 CA smoke；公网不得跳过证书校验。
curl --fail --silent --show-error --insecure https://localhost:8443/api/health
```

可重现身份来自 digest 锁定的基础镜像、不可变仓库快照/精确包版本、固定时间戳和
`rewrite-timestamp=true`，不来自 pull 策略。重建后必须重新记录 `release-images.json`，并让
同一 tar 身份贯穿原始扫描、inventory、audit、gate 与发行。

浏览器使用 `https://localhost:8443`。本地发行物采用 Caddy 内部 CA，第一次访问会显示本地
证书警告；上述 `--insecure` 只用于本机健康探针。当前 Compose 把 Caddy 数据放在 `/tmp`
tmpfs，因此内部 CA 是容器重建即可能变化的临时 CA；不要把它导出并当作稳定根 CA 永久信任。
本机浏览器例外也只针对当前临时实例。公网部署必须使用受信任域名证书。数据保存在
`museecho_data` 卷，普通重启不会丢失；`docker compose --profile production down --volumes`
会删除数据库和密文音频，但不会删除外部 Secret 目录。

development profile 通过 `https://localhost:4173` 同时提供构建后的前端和同源 `/api` 代理；
FastAPI 不暴露宿主机端口，Secure cookie、Origin 与 CSRF 边界保持不变。后端只读挂载当前
`src/` 并启用 reload；前端修改后重新执行同一条 `up --build`。它使用独立的
`museecho_dev_data` 卷，不能当作生产部署：

```powershell
$env:MUSEECHO_SECRETS_DIR = 'D:\MuseEchoSecrets'
docker compose --profile development up --build --detach --wait app-dev gateway-dev
curl.exe --fail --silent --show-error --insecure https://localhost:4173/api/health
# 浏览器打开 https://localhost:4173
```

`powershell.exe -File scripts\development-smoke.ps1` 会执行同一 development profile，真实访问
HTTPS 前端和同源 API，并在成功或失败后清理其独立容器、网络、卷与 task-temp Secret。

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
- 上传解码只接受严格容器/编解码器配对：WAV 中的受限 PCM/IEEE float、常规 MP3、FLAC、
  M4A 中的 AAC/ALAC、ADTS AAC、Ogg/Vorbis 和 Ogg/Opus。浏览器 MIME 或后缀只是预检，
  服务器会独立核对签名、容器、全部媒体流与 codec；DRM 和专有加密下载均失败关闭。
  `ffprobe` 与 `ffmpeg` 共用从格式注册表派生的精确 format/codec allowlist 和 `file,pipe`
  protocol allowlist。
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
精确一致，并拒绝重复 Python 名称或显式审批集合外的许可证。发行阶段还会从最终 app 镜像
记录全部已安装 Debian/Python 组件，从最终 gateway 镜像记录全部 Alpine 组件，并用
`go version -m` 记录 Caddy 实际链接的全部 Go 模块；`release-license-policy.json` 对每个精确
身份、版本、Go sum、许可证元数据哈希和 Caddy 二进制哈希逐项审批，任何新增、缺失、版本、
许可证或哈希漂移都会失败并保留 inventory 证据。`scripts/container-pytest.ps1` 可用现有 app
镜像的 FFmpeg 运行完整 Python 套件：仓库和现有 pytest 模块只读挂载、网络关闭，不向生产
镜像加入测试工具。本地配置通过不代表远端 CI 已运行，只有对应提交的真实流水线结果才能
作为远端证据。

## 部署

单机部署应把 8080/8443 仅用于初始验证，正式环境使用域名、受信 TLS、主机防火墙、卷备份
与定期恢复演练。腾讯云安装、升级、回滚和备份脚本属于 PLAN Task 21，本任务不会伪造尚未
执行的公网部署结果。

## 已知限制

- V1 仅接受 `.wav,.mp3,.flac,.m4a,.aac,.ogg,.opus` 七个后缀与其严格内容配对，
  最长 10 分钟；`.mp4`、`.oga`、DRM 和专有加密下载不支持；仅输出大小三和弦，
  其他和声保守为 `unknown`。
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
