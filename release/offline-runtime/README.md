# MuseEcho v0.1.0 离线运行包

此目录用于在已经下载全部 GitHub Release 资产后断网运行 MuseEcho。它不会从源码构建镜像，
也不会从 registry 拉取镜像；`ENG-010` 所指的断网源码重建不在本运行包范围内。

## 前置条件

- Windows 10/11、PowerShell 和已启动的 Docker Desktop（包含 Docker Compose v2）；
- 将 `museecho-app.tar`、`museecho-gateway.tar` 与解压后的本目录文件放在同一目录；
- 第三方模型 Key 不需要，未配置时使用确定性解释。

## 验证与运行

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\offline-runtime.ps1 -Action Verify
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\offline-runtime.ps1 -Action Smoke
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\offline-runtime.ps1 -Action Start
```

浏览器打开 `https://localhost:4173`。Caddy 使用本地内部 CA，浏览器可能显示证书警告；只对
当前 localhost 实例继续访问，不要把临时 CA 当作公网证书。

默认 Secret 保存在用户目录下的 `MuseEchoSecrets`，加密分析数据保存在 Docker 卷。停止服务
不会删除数据：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\offline-runtime.ps1 -Action Stop
```

如果 4173 被占用，可以在验证、Smoke 和 Start 时都传入同一个 `-HttpsPort` 参数。若使用自定义
Secret 目录，向 Start 与 Stop 同时传入同一个绝对 `-SecretsDirectory`。
