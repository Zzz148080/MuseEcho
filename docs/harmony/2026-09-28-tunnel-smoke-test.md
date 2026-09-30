# HarmonyOS 临时 HTTPS 联调记录

日期：2026-09-28。此记录仅涵盖本次 Docker、临时隧道与 API 20 模拟器测试，不代表正式公网部署、真机验收或可发布签名。

## 本机环境修复

- Docker Desktop 4.86.0 初次启动失败，日志与弹窗均指向不可访问的旧 Unix socket 重解析点。未执行“恢复出厂设置”。在确认仅含临时 socket 且 Docker 引擎未启动后，将 `C:\Users\P\AppData\Local\Docker\run` 和 `C:\Users\P\AppData\Local\docker-secrets-engine` 的故障实例改名备份；一次中断启动新产生的单 socket `run` 目录也改名备份。Docker 随后重建运行时目录，Linux 引擎 29.7.2 正常响应。
- 曾尝试关闭 Docker AI，但无效；`settings-store.json` 已从备份恢复，`EnableDockerAI` 最终仍为 `true`。镜像、已有卷与配置数据没有重置。
- Docker CLI 原先未识别 Buildx；把 Docker Desktop 自带、Windows 签名有效的 `docker-buildx.exe` 注册到当前用户的 Docker CLI 插件目录，SHA-256 与安装包内原件一致。Compose 使用已安装的独立版 v5.3.1。

## 服务与 API

- 以当前前端工作树重建 `museecho-gateway:local`，Docker development profile 的 `app-dev` 和 `gateway-dev` 均达到 healthy。网关仅绑定 `127.0.0.1:4173`，本地 HTTPS 前端返回 200，`/api/health` 返回 ready。
- 从 Cloudflare 官方 GitHub Release 下载 `cloudflared` 2026.9.3 Windows x64，Windows 签名为 `Cloudflare, Inc.` 且有效；SHA-256 为 `F096265EC2FCBE9BB6E2D64268DB167CED3FCBB83D894BDB9E2FCDB26F2EA7E2`。
- Quick Tunnel 仅代理本机 HTTPS 网关。公网端点的标准证书校验通过，前端返回 200，`/api/health` 返回 ready；服务端仅将本次生成的精确 HTTPS origin 加入受信同源列表。临时 URL 不是访问控制，不应用于敏感音频或正式部署。
- 使用项目自带的 4 秒合成 WAV，经公网端点完成上传、分析、结果读取、16 字节 Range 音频读取、带 `Origin` 与 CSRF 令牌的删除，以及删除后 404。第一次测试脚本误把接口终态 `complete` 写成 `completed`，造成误报超时；修正后整套检查通过。第一次生成的合成测试数据已随专用测试卷清除。

## HarmonyOS 模拟器

- 构建脚本可用 `-TemporaryServiceOrigin` 仅在隔离构建快照里注入本次 `trycloudflare.com` 地址；仓库中的 `ServiceConfig.ets` 仍为空。临时未签名 HAP 为 `harmony/artifacts/MuseEchoHarmony-1767e00838e54aad8e5a294568a49874/entry-default-unsigned.hap`，SHA-256 `E554C6ED9EA0357D641FF0F8A0A2A9FF6FCEC7C47582D451C44C52794C619B1B`。
- 在已获用户许可的 `MuseEcho_API20` 手机模拟器安装、启动成功。ArkWeb 实际加载远端 React 工作台，非原生空页；见 [工作台截图](evidence/api20-tunnel-workbench.png)。系统文件选择器可打开、取消并再次打开，见 [首次打开](evidence/api20-picker-empty.png)、[取消后页面](evidence/api20-picker-cancelled.png) 和 [再次打开](evidence/api20-picker-reopened.png)。未接受或绕过“小艺输入法”的独立隐私协议。
- 模拟器文件库为空，未完成设备内选中文件、经 ArkWeb 上传、分析、播放、删除的全链路验证。尝试向候选公共 Download 路径发送合成 WAV 返回路径不存在，未提升模拟器权限或修改安全设置。

## 收尾与剩余工作

- 已关闭 Quick Tunnel；停止并移除本次 `app-dev`、`gateway-dev` 容器和网络；核实后删除仅在本次创建的 `museecho_museecho_dev_data` 卷及专用临时加密密钥。该卷中的合成测试数据不可恢复。其他 Docker 卷与镜像保留。
- 模拟器重新安装先前 SHA-256 为 `BC15C105A928A9864361731BB27E2B4D0AA359CBAF4F256002EDED61A1D3F1A7` 的空地址 HAP，随后停止模拟器。临时 HAP 仅留作可复核测试产物，不能用于分发；其中地址已失效。
- 后续仍需真机/平板与横屏、大字号、后台播放测试；设备内真实文件选择及上传链路；稳定受信 HTTPS 服务、正式签名、隐私审核和赛事细则核对。短时 Quick Tunnel 的成功不等于这些工作完成。
