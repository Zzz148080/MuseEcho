# MuseEcho v0.1.0 正式发行复现说明

本说明面向从 GitHub Release 接收 MuseEcho 的教师或复核者。正式发行地址固定为：

<https://github.com/Zzz148080/MuseEcho/releases/tag/v0.1.0>

只有当该页面显示为已发布、非草稿、非预发布，并同时提供下列四个资产时，才构成完整的
离线运行发行物：

- `museecho-app.tar`
- `museecho-gateway.tar`
- `museecho-offline-runtime-v0.1.0.zip`
- `SHA256SUMS.txt`

## 已验证发行事实（2026-08-17）

- Release 于 `2026-08-17T05:54:50Z` 正式发布，非草稿、非预发布；标签 `v0.1.0`
  精确指向 `main` SHA `d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1`。
- `museecho-app.tar`：366,037,504 字节，SHA-256
  `f8aaf8369f76bd70304e2770e21e1bfc5f5a45979b63d9eb512e39d58d2fff95`。
- `museecho-gateway.tar`：59,211,776 字节，SHA-256
  `765a0b089f174ce57e92ffdac8aada6fa24475f0a445a361850e27764f3320a3`。
- `museecho-offline-runtime-v0.1.0.zip`：9,293 字节，SHA-256
  `e85248bbee5dd2e4b406f830db02e6547649cc948dbae01b04685882d827f80c`。
- `SHA256SUMS.txt`：275 字节，SHA-256
  `058ae2c2f641fea7b311bf996c4d51d04fbd6d4b84955ae3dc501b98bf3b8d46`。

发布后四项资产均从 GitHub 实际回下载并重新计算 SHA-256；解压后的工具包完成 `Verify`、镜像导入、
清单身份检查、`--no-build` Compose、HTTPS 健康检查、WAV 上传分析、应用重启后结果持久化、无
持久化明文音频和临时资源清理。

主分支运行 `31997390847` 的 `quality`、E2E、`distribution` 均通过，但 Actions 配额跳过了制品留存，
所以 GitHub 没有保留可供事后下载并与 Release tar 逐字节对比的 CI 制品。为完成用户授权的自动
正式发行，发布资产采用来源回退：从精确 `main` SHA 本地重建，并针对已发布字节重新执行
镜像身份、打包、回下载校验和与真实 no-build Smoke。这里不声称与 CI 内未留存
tar 字节相同；能证明的是源提交相同、CI 构建/审计链通过，以及已发布字节自身重新通过上述
发行身份、校验和与 no-build Smoke 门。
该边界同时固化在 `release/v0.1.0-manifest.json`。

## 一键重放 GitHub Release 证据

在仓库根目录先完成 `gh auth login`，并选择一个尚不存在或不含四项资产的新目录。下面的真实命令会
读取 GitHub Release、把附注标签解引用到最终提交、核对发布时间和四项远端资产的名称/大小/
摘要、下载四项资产、校验校验和文件自身摘要与其中三个载荷的校验和，解压 zip，然后
从明确的临时目录依次执行离线工具的 `-Action Verify` 和 `-Action Smoke`；任一步不一致都会非零退出：

```powershell
$releaseDir = Join-Path (Get-Location) 'tmp\release-v0.1.0-verification'
.\.venv\Scripts\python.exe scripts/verify_github_release.py --action Smoke --manifest release/v0.1.0-manifest.json --assets-directory $releaseDir --download
```

验证器只在启动接收脚本的子进程中移除继承的 `PSModulePath`，避免 PowerShell 7 的同名模块在
Windows PowerShell 5.1 前被错误加载并遮蔽 `Get-FileHash`；它不会修改用户或系统的 PowerShell
配置。`--gh-command` 与 `--powershell-command` 也接受不经过 shell 的命令参数前缀，便于在明确的
运行时路径下重放，同时避免临时脚本执行权限差异。

如果四项资产已经位于一个明确目录，去掉 `--download` 并把 `$releaseDir` 指向该目录即可。验证器使用
`release/v0.1.0-manifest.json` 的固定事实，文档校验器也逐字段绑定同一组文件名、大小、SHA-256、
发布时间和最终目标 SHA，不能通过同时改写说明文字来伪造另一组 Release。

## 接收方需要准备什么

- Windows 10/11；
- 已安装并启动的 Docker Desktop，且包含 Docker Compose v2；
- Windows PowerShell 5.1 或 PowerShell 7；
- 足够保存两个镜像 tar、Docker 镜像和运行数据的磁盘空间；
- 第三方模型 Key **不需要**，缺省使用确定性解释。

首次获取资产需要网络。四个资产下载完成后，校验、导入、自动 Smoke 和运行过程不会构建或
拉取镜像，可以断网执行。

## 下载和解压

将四个资产放入同一个新目录，然后把
`museecho-offline-runtime-v0.1.0.zip` 直接解压到该目录。完成后，目录顶层应同时出现：

```text
compose.yaml
museecho-app.tar
museecho-gateway.tar
offline-runtime.ps1
release-images.json
release-version.txt
SHA256SUMS.txt
scripts/container-smoke.ps1
```

## 自动验收

在资产目录打开 PowerShell：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\offline-runtime.ps1 -Action Verify
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\offline-runtime.ps1 -Action Smoke
```

`Verify` 会在 Docker 导入前核对两个 tar 的 SHA-256 和发行身份。`Smoke` 会导入同一批
镜像，以 `--no-build` 启动隔离实例，生成测试 WAV，完成上传与分析，验证重启持久化、持久卷无
明文音频、镜像身份及清理。Smoke 使用独立临时 Secret、容器、网络和卷，成功或失败都会清理。

## 网页人工体验

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\offline-runtime.ps1 -Action Start
```

浏览器访问 `https://localhost:4173`，上传自己有权使用的 WAV、MP3、FLAC、M4A、AAC、OGG 或
OPUS 文件并等待结果页。Caddy 使用本地内部 CA，浏览器可能显示证书警告；只为当前 localhost
实例继续访问，不要把该临时 CA 当成公网证书。

如果端口 4173 被占用，向 Smoke、Start 和 Stop 传入同一个可用端口，例如
`-HttpsPort 4273`。默认 KEK 位于用户目录下的 `MuseEchoSecrets`，分析数据库与密文音频位于
Docker 卷。

停止服务但保留分析数据：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\offline-runtime.ps1 -Action Stop
```

## 证据边界

该 Release 是“离线运行包”：`main` 源提交的 CI 构建、许可证、漏洞/VEX 和真实 HTTPS 流程均通过；
由于该 CI 制品未留存，这些安全门不被冒充为发布 tar 的直接逐字节证据。发布 tar 自身完成
发行身份、校验和、真实 no-build HTTPS/WAV Smoke，接收方下载后可断网导入和运行。它
不是“断网从源码重建”；当前 Dockerfile 的正式
`--network none` 源码重建仍记录为 `ENG-010 BLOCKED`。Release 也不代表腾讯云部署、受信公网
TLS、目标服务器验证、24 小时观察、备份恢复或真实回滚已经完成。
