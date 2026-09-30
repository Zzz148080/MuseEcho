# Linux 云服务器交付说明

这些脚本用于准备和运维一台 Linux 云服务器；目录名保留了最初的腾讯云交付名称，当前也已在华为云 Flexus 上验证。脚本不会创建云资源、修改 DNS 或上传凭据，公网状态以 [`DEPLOYMENT_EVIDENCE.md`](../../DEPLOYMENT_EVIDENCE.md) 的实际记录为准。

## 前置条件

- 一台至少配备 2 vCPU、标称 4 GiB 内存，并在操作系统占用之外预留 20 GiB 部署空间的 Linux 云服务器；容量检查允许云平台预留内存后的 3.75 GiB guest-visible `MemTotal`；
- 已安装 Docker Engine、Docker Compose v2、`curl` 和 systemd；
- 域名已经指向该实例，云厂商防火墙和主机防火墙仅放行 TCP 22、80、443；
- 在 `sshd_config` 中设置 `PasswordAuthentication no` 前，已验证基于密钥的 SSH 登录，并保留经过测试的控制台恢复路径；
- `/etc/museecho/secrets/audio-kek` 的所有者为 `10001:10001`、权限为 `0400`。可选的 `/etc/museecho/secrets/provider-key`、`tencent-ses-secret-id`、`tencent-ses-secret-key` 和 `smtp-password` 遵循相同约束，且仅在对应功能启用时需要。不得把任一密钥值传给这些脚本，也不得写入 shell 历史、日志、`.env` 或发行文件。

## 安装与检查

先运行不会修改系统的前置条件门禁：

```bash
sudo bash deploy/tencent-cloud/install.sh --check-only
```

检查通过后，安装项目目录、systemd 单元和 UFW 规则：

```bash
sudo bash deploy/tencent-cloud/install.sh
sudoedit /srv/museecho/config/runtime.env
# 设置 MUSEECHO_DOMAIN=music.example.com（这不是密钥）。
```

大陆云主机若无法完成公网 ACME 验证，可使用 Cloudflare Tunnel 承载公网 TLS。先在 Cloudflare Zero Trust 创建 `cloudflared` Tunnel，并把 Public Hostname 设置为 `museecho.toolgate.cloud`，Service 设置为 `https://127.0.0.1:443`。在 Origin TLS 设置中**开启 `No TLS Verify`（关闭 Origin TLS 验证）**，并将 Origin Server Name / HTTP Host Header（界面提供时）设为 `museecho.toolgate.cloud`，让 Caddy 的站点匹配稳定。创建 Public Hostname 后使用 Tunnel 自动生成的 CNAME，删除同名的旧 A 记录，避免两条入口并存。然后在本机配置：

```ini
MUSEECHO_TUNNEL_MODE=1
```

Tunnel 模式下 Caddy 使用内部 CA，部署脚本会用 `curl --insecure` 做本机健康检查；Cloudflare 负责公网证书和浏览器信任。Tunnel 服务应由 Cloudflare 控制台提供的安装命令注册为 systemd 服务，Tunnel token 不要写入仓库或发送给助手。未配置 Tunnel 时保持 `MUSEECHO_TUNNEL_MODE=0`，由 Caddy 直接申请公网证书。

个人实名账号优先使用腾讯云 SES API。在 `runtime.env` 中配置非密钥字段，并让 API 凭据保持在两个独立的密钥文件中：

```ini
MUSEECHO_TENCENT_SES_REGION=ap-hongkong
MUSEECHO_TENCENT_SES_SENDER=MuseEcho <no-reply@mail.toolgate.cloud>
MUSEECHO_TENCENT_SES_SECRET_ID_FILE=/run/secrets/tencent-ses-secret-id
MUSEECHO_TENCENT_SES_SECRET_KEY_FILE=/run/secrets/tencent-ses-secret-key
MUSEECHO_TENCENT_SES_VERIFY_TEMPLATE_ID=腾讯云审核通过的邮箱验证模板 ID
MUSEECHO_TENCENT_SES_RESET_TEMPLATE_ID=腾讯云审核通过的密码重置模板 ID
```

腾讯云未开通自定义发送权限时，`SendEmail` 必须使用已审核通过的模板。邮箱验证模板变量为 `verify_token` 和 `expire_hours`，密码重置模板变量为 `reset_token` 和 `expire_minutes`。模板正文位于仓库 `deploy/tencent-cloud/templates/`。

企业认证账号也可以选择 SMTP 备用模式：

```ini
MUSEECHO_SMTP_HOST=smtp.qcloudmail.com
MUSEECHO_SMTP_PORT=587
MUSEECHO_SMTP_USER=no-reply@mail.toolgate.cloud
MUSEECHO_SMTP_PASSWORD_FILE=/run/secrets/smtp-password
MUSEECHO_SMTP_SENDER=MuseEcho <no-reply@mail.toolgate.cloud>
```

两种模式只能启用一种。API 模式不需要 SMTP 密码；两个凭据文件分别保存权限受限 CAM 用户的 SecretId 和 SecretKey。SMTP 密码文件只保存腾讯云“设置 SMTP 密码”生成的专用密码，不保存腾讯云登录密码。邮件中的验证及重置链接使用 `https://$MUSEECHO_DOMAIN`。

Windows 本地联调时，可运行仓库中的 `scripts/configure-tencent-ses-secrets.ps1`。脚本会在隐藏输入状态下读取两项 CAM 凭据，并保存到 `%LOCALAPPDATA%\MuseEcho\secrets`；只输出文件路径，不输出凭据内容。该步骤可以推迟到真实邮件验收前执行。

安装器以 `10001:10001`、`0700` 创建应用可写的 `/srv/museecho/data`，以 `root:10001`、`0750` 创建 `releases`、`config` 和 `/etc/museecho/secrets`。如果已有 systemd 文件不归本项目所有，安装器会拒绝覆盖。执行任何安装写入前，脚本要求 UFW 已启用且入站默认策略为拒绝，并拒绝 TCP 22/80/443 之外的已有入站 ALLOW 规则；已有的来源受限 SSH 规则会保留，只有完全没有 22/tcp 规则时才添加。云安全组也必须使用同一允许列表；脚本无法检查或修改云厂商防火墙。

## 部署与回滚

只接受带固定 OCI 摘要的镜像仓库引用：

```bash
sudo bash deploy/tencent-cloud/deploy.sh \
  --app-image registry.example/museecho-app@sha256:<64-lowercase-hex> \
  --gateway-image registry.example/museecho-gateway@sha256:<64-lowercase-hex>
```

脚本会拉取两个精确镜像身份、写入不可变发行目录、原子切换 `/srv/museecho/current`、重启本项目的 systemd 单元，并检查 `https://$MUSEECHO_DOMAIN/api/health`。健康检查失败时会自动恢复到上一个已验证发行版本。若要手动选择最近一个已验证的旧发行版本并运行相同健康门禁，请执行：

如果已有数据库，发布会先生成在线快照，再运行 `alembic upgrade head`，迁移成功后才重启到新版本。迁移失败时会恢复已验证的旧发行指针。迁移必须遵守 expand/contract：先发布兼容新旧应用的增量结构，完成数据回填并稳定运行后，才在后续版本移除旧结构；这样旧版本才能在应用健康检查失败时安全接管。

```bash
sudo bash deploy/tencent-cloud/rollback.sh
```

任务 20 记录的是镜像 ID 和 tar 摘要，而不是已推送的仓库摘要。使用这些脚本前，发行操作人员必须发布或通过其他方式取得带精确摘要的引用；`:latest` 等标签会被拒绝。

## 备份与恢复边界

```bash
sudo bash deploy/tencent-cloud/backup.sh
```

备份通过 SQLite 在线备份 API，在 WAL 写入可能继续进行时生成通过完整性检查的独立数据库快照，并包含非密钥运行时/发行元数据及 `SHA256SUMS`。默认保留 30 天，可在 `runtime.env` 用 `MUSEECHO_BACKUP_RETENTION_DAYS` 设置 1–3650 天。

建议安装 `age`，并在 `runtime.env` 设置一个公钥接收者 `MUSEECHO_BACKUP_AGE_RECIPIENT`。此后新备份只保留 `.tar.gz.age` 密文。恢复端将私钥文件放在仓库外，并设置 `MUSEECHO_BACKUP_AGE_IDENTITY_FILE`；私钥内容不会进入命令行、日志或归档。未配置 `age` 时，备份仍以 root 专属 `0600` 文件生成，主机磁盘和异地副本应启用存储加密。

恢复命令要求精确归档路径和显式确认标志。脚本会限制归档位置与成员、校验 SHA-256 和 SQLite 完整性、停止服务并原子替换数据库，然后执行健康检查；失败会恢复原数据库：

```bash
sudo bash deploy/tencent-cloud/restore.sh \
  --archive /srv/museecho/backups/museecho-20260928T120000Z.tar.gz.age \
  --confirm-restore
```

备份有意排除加密音频密文和封装后的逐分析密钥材料。恢复音频还需要单独受保护的数据备份，以及始终位于归档之外的 KEK；归档不会复制密钥文件。应定期在隔离环境中演练上述恢复命令。

## 公网冒烟记录

部署或升级后，按 [`DEPLOYMENT_EVIDENCE.md`](../../DEPLOYMENT_EVIDENCE.md) 的格式记录时间戳、精确镜像摘要、脱敏健康结果和回滚证据。
