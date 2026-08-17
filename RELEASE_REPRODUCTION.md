# MuseEcho v0.1.0 Release 复现说明

本说明面向从 GitHub Release 接收 MuseEcho 的教师或复核者。正式 Release 地址固定为：

<https://github.com/Zzz148080/MuseEcho/releases/tag/v0.1.0>

只有当该页面显示为已发布、非 Draft、非 Prerelease，并同时提供下列四个资产时，才构成完整的
离线运行发行物：

- `museecho-app.tar`
- `museecho-gateway.tar`
- `museecho-offline-runtime-v0.1.0.zip`
- `SHA256SUMS.txt`

## 接收方需要准备什么

- Windows 10/11；
- 已安装并启动的 Docker Desktop，且包含 Docker Compose v2；
- Windows PowerShell 5.1 或 PowerShell 7；
- 足够保存两个镜像 tar、Docker 镜像和运行数据的磁盘空间；
- 第三方模型 Key **不需要**，缺省使用确定性解释。

首次获取资产需要网络。四个资产下载完成后，校验、导入、自动 smoke 和运行过程不会构建或
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

`Verify` 会在 Docker 导入前核对两个 tar 的 SHA-256 和 release identity。`Smoke` 会导入同一批
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

该 Release 是“离线运行包”：镜像由发布方在线构建并完成身份、许可证、漏洞/VEX 和真实 HTTPS
流程检查，接收方下载后可断网导入和运行。它不是“断网从源码重建”；当前 Dockerfile 的正式
`--network none` 源码重建仍记录为 `ENG-010 BLOCKED`。Release 也不代表腾讯云部署、受信公网
TLS、目标服务器验证、24 小时观察、备份恢复或真实回滚已经完成。
