# 腾讯云 Lighthouse 交付说明

这些脚本用于准备和运维一台 Linux Lighthouse 实例。它们仅作为本地控制面工具：不会创建腾讯云资源、修改 DNS、上传凭据，也不会声称公网端点已经存在。

## 前置条件

- 一台至少配备 2 vCPU、4 GiB 内存，并在操作系统占用之外预留 20 GiB 部署空间的 Linux Lighthouse；
- 已安装 Docker Engine、Docker Compose v2、`curl` 和 systemd；
- 域名已经指向该实例，云厂商防火墙和主机防火墙仅放行 TCP 22、80、443；
- 在 `sshd_config` 中设置 `PasswordAuthentication no` 前，已验证基于密钥的 SSH 登录，并保留经过测试的控制台恢复路径；
- `/etc/museecho/secrets/audio-kek` 的所有者为 `10001:10001`、权限为 `0400`。可选的 `/etc/museecho/secrets/provider-key` 遵循相同约束，且仅在启用第三方提供方配置时需要。不得把任一密钥值传给这些脚本，也不得写入 shell 历史、日志、`.env` 或发行文件。

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

安装器以 `root:10001`、`0750` 创建 `/srv/museecho/data`、`releases` 和 `config`，并以相同的目录穿越边界创建 `/etc/museecho/secrets`。如果已有 systemd 文件不归本项目所有，安装器会拒绝覆盖。执行任何安装写入前，脚本要求 UFW 已启用且入站默认策略为拒绝，并拒绝 TCP 22/80/443 之外的已有入站 ALLOW 规则；之后只会幂等添加这三个 TCP 放行项。Lighthouse 安全组也必须使用同一允许列表；没有云端授权时，脚本无法检查或修改云厂商防火墙。

## 部署与回滚

只接受带固定 OCI 摘要的镜像仓库引用：

```bash
sudo bash deploy/tencent-cloud/deploy.sh \
  --app-image registry.example/museecho-app@sha256:<64-lowercase-hex> \
  --gateway-image registry.example/museecho-gateway@sha256:<64-lowercase-hex>
```

脚本会拉取两个精确镜像身份、写入不可变发行目录、原子切换 `/srv/museecho/current`、重启本项目的 systemd 单元，并检查 `https://$MUSEECHO_DOMAIN/api/health`。健康检查失败时会自动恢复到上一个已验证发行版本。若要手动选择最近一个已验证的旧发行版本并运行相同健康门禁，请执行：

```bash
sudo bash deploy/tencent-cloud/rollback.sh
```

任务 20 记录的是镜像 ID 和 tar 摘要，而不是已推送的仓库摘要。使用这些脚本前，发行操作人员必须发布或通过其他方式取得带精确摘要的引用；`:latest` 等标签会被拒绝。

## 备份与恢复边界

```bash
sudo bash deploy/tencent-cloud/backup.sh
```

备份通过 SQLite 在线备份 API，在 WAL 写入可能继续进行时生成通过完整性检查的独立数据库快照，并包含非密钥运行时/发行元数据及 `SHA256SUMS`。备份有意排除加密音频密文和封装后的逐分析密钥材料。恢复音频还需要单独受保护的数据备份，以及始终位于归档之外的 KEK；归档不会复制密钥文件。依赖备份前，应定期在隔离环境中测试恢复流程。

## 公网冒烟记录

获得云账号、域名/DNS 和 SSH 授权后，按顺序执行 [`DEPLOYMENT_EVIDENCE.md`](../../DEPLOYMENT_EVIDENCE.md) 中的命令，并记录时间戳、与主机无关的客户端结果和回滚证据。在这些真实操作发生前，不得添加公网 URL 或 `PASS` 结论。
