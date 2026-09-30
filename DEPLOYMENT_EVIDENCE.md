# 公网部署证据

## 状态

2026-09-28 UTC，MuseEcho 已部署到华为云 Flexus（华北-北京四）的 Ubuntu 24.04.4
实例。公网入口为 `https://museecho.toolgate.cloud`，Cloudflare DNS-only A 记录解析到
`114.116.237.72`。本文件只记录脱敏结果，不记录 SWR Token、腾讯云 SES 凭据、SSH 私钥或密码。

本次发布的服务器内 HTTPS 健康门禁通过，部署脚本输出：

```text
Deployment activated: 20260928T180424Z-e7da257e49894df
```

精确镜像身份：

```text
swr.cn-north-4.myhuaweicloud.com/museecho/museecho-app@sha256:e7da257e49894df8c7993364bb5f5a71a4dc1c95524da0bb55bf01f5ec29f3d7
swr.cn-north-4.myhuaweicloud.com/museecho/museecho-gateway@sha256:c23121730730b636cf5eaf53649c22586cd8cd3f277bfd0ede09050a5a7f4414
```

已确认 Docker 29.8.1、Docker Compose v2、UFW 默认拒绝入站；TCP 22 只允许管理地址
`58.192.68.49`，TCP 80/443 对公网开放。Alembic 从空库依次执行 `0001` 和 `0002`，
发布前在线备份已生成，激活门禁使用受信域名证书且未使用 `--insecure`。

2026-09-29 从当前 Windows 客户端复查时，公网 TCP 80/443 均可建立连接，但 TLS 握手被
远端重置；因此这里只认定服务器内健康门禁通过，不认定独立公网浏览器验收完成。该现象需结合
华为云大陆节点的备案要求排查，或改用 Cloudflare Named Tunnel 后复验。

2026-09-29 已在工作区加入 Cloudflare Tunnel 兼容模式：`MUSEECHO_TUNNEL_MODE=1` 时 Caddy
使用内部 CA，部署健康门禁仅对本机源站使用 `curl --insecure`；默认值 `0` 仍走公网 ACME。
该改动已通过隔离 Docker 交付合同测试和 ShellCheck，但尚未上传到服务器，也未替代公网线上验收。

## 本地证据

- 交付脚本在一次性文件系统根目录中使用命令替身完成合同测试。这些测试覆盖摘要拒绝、
  不产生修改的 check-only 模式、受控路径幂等安装、防火墙/systemd 调用、健康失败原子回滚、
  备份排除和完整性元数据。
- `install.sh --check-only` 用于检查 Linux、容量、磁盘预算、Docker/Compose、curl、systemd
  和部署包假设，且不会创建路径、Secret、防火墙规则、unit 文件或容器。
- 本地证据未使用任何 Secret 值或云提供商凭据。

### 容器迁移复验（本地，2026-09-29）

从当前工作区重新构建应用镜像后，以无网络容器执行
`python -m museecho.infrastructure.migrate`。空数据库依次完成 `0001` 和 `0002`；镜像运行用户为
`10001:10001`，工作目录为 `/app`，并通过
`MUSEECHO_ALEMBIC_CONFIG=/app/alembic.ini` 加载镜像内迁移配置。用于本次复验的本地镜像 ID 为：

```text
sha256:c8ca335c5e300f4dd6cc1519f759c66333a8c281c3bcf178ff1d09a7ed3e600b
```

该 ID 只标识当前工作区的本地复验镜像，不替代上文已经部署的 SWR 镜像摘要。

### 浏览器全流程回归（本地，2026-09-29）

使用系统 Edge 作为 Playwright 浏览器，在本机 HTTPS 同源入口完成 24 项端到端回归，结果为
`24 passed`。覆盖 WAV、MP3、FLAC、M4A、AAC、OGG、Opus 的真实上传、分析、播放与跳转，
并覆盖蓝紫和弦星系、钢琴、桌面/平板/手机布局、注册与登录弹窗、忘记密码、本地测试邮件链接、
保存及复看分析、权限边界和删除流程。回归期间未出现页面控制台错误。

该回归使用本地测试邮件器和本地受信任测试入口，只证明当前工作区的浏览器流程；它不替代下文的
独立公网浏览器和真实腾讯云 SES 验收。

### 必需的 ShellCheck 门禁（本地，2026-09-29 复验）

使用本地已有的官方镜像运行，未拉取镜像、未访问网络，也未安装宿主工具。精确镜像身份如下：

```text
koalaman/shellcheck-alpine:v0.10.0@sha256:7c6a5115899d99323b22fc84b29e924aef5b6fa985612e450a8c356969ebb577
```

离线 `shellcheck --version` 原始命令与输出（exit 0）：

版本命令以 exit 0 结束，原始输出记录如下。

```powershell
docker run --pull=never --rm --network none --entrypoint shellcheck koalaman/shellcheck-alpine:v0.10.0@sha256:7c6a5115899d99323b22fc84b29e924aef5b6fa985612e450a8c356969ebb577 --version
```

```text
ShellCheck - shell script analysis tool
version: 0.10.0
license: GNU General Public License, version 3
website: https://www.shellcheck.net
```

离线 lint 命令与结果：

```powershell
docker run --pull=never --rm --network none --entrypoint shellcheck -v "$PWD:/work:ro" -w /work koalaman/shellcheck-alpine:v0.10.0@sha256:7c6a5115899d99323b22fc84b29e924aef5b6fa985612e450a8c356969ebb577 deploy/tencent-cloud/lib.sh deploy/tencent-cloud/install.sh deploy/tencent-cloud/deploy.sh deploy/tencent-cloud/rollback.sh deploy/tencent-cloud/backup.sh
```

lint 命令以 exit 0 结束，stdout/stderr 均为空。

## 尚待完成的线上验收

以下项目仍需要真实账号、浏览器或隔离恢复环境，完成前不得声称对应流程已验收：

1. 配置腾讯云 SES SecretId/SecretKey 文件，验证注册邮件、邮箱验证、忘记密码和重置密码。
2. 从独立公网浏览器完成注册、登录、上传真实音频、分析、播放、保存记录和退出登录全流程。
3. 验证备份 `SHA256SUMS`，在隔离环境执行 `restore.sh --confirm-restore`，再记录手动回滚结果。
4. 确认 SSH 密钥登录和云控制台恢复路径后，再决定是否禁用密码登录。
