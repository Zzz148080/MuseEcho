# 腾讯云部署证据

## 状态

本文件不声称存在公网 URL。任务 21 当时没有可用的腾讯云账号、Lighthouse 实例、
域名/DNS 控制权或 SSH 授权。因此，本文件只记录本地脚本证据和仍待补充的真实服务器证据，
不构成公网部署完成声明。

根据 `COURSE_REQUIREMENT_UPDATE.md`，这些真实服务器事项属于下一阶段部署计划，
不是当前课程提交的阻塞项。它们仍未执行；未来作出任何公网部署声明前，必须取得新的脱敏证据。

## 本地证据

- 交付脚本在一次性文件系统根目录中使用命令替身完成合同测试。这些测试覆盖摘要拒绝、
  不产生修改的 check-only 模式、受控路径幂等安装、防火墙/systemd 调用、健康失败原子回滚、
  备份排除和完整性元数据。
- `install.sh --check-only` 用于检查 Linux、容量、磁盘预算、Docker/Compose、curl、systemd
  和部署包假设，且不会创建路径、Secret、防火墙规则、unit 文件或容器。
- 本地证据未使用任何 Secret 值或云提供商凭据。

### 必需的 ShellCheck 门禁（本地，2026-08-11）

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

## 待补充的真实服务器证据

获得授权后，为下列每项记录 UTC 时间、精确摘要引用和脱敏命令结果。不得记录 Secret 值。

1. 确认 Lighthouse 地域、容量、磁盘、当前系统更新以及 Docker 和 Compose 版本；
   依次运行 `install.sh --check-only` 与 `install.sh`。
2. 确认 Lighthouse 安全组和宿主防火墙都只允许 TCP 22/80/443；禁用密码认证前，
   确认使用密钥认证的 SSH 会话仍然可用。
3. 发布或取得精确的 app/gateway OCI 摘要，使用 `deploy.sh` 部署，并通过受信域名证书
   记录健康响应（不得使用 `--insecure`）。
4. 在条件允许时从至少两个中国大陆网络上传合法的真实 WAV/MP3，等待分析、播放 Range、
   提问、删除结果，并用带时间戳的证据确认 24 小时清理计划。
5. 运行 `backup.sh`，验证其 `SHA256SUMS`，在隔离环境中恢复，再部署一个已知正常的旧版
   Release，并记录自动与手动回滚健康检查。

授权缺失属于外部交付门禁，不应据此声称本地实现或复审受到阻塞。
