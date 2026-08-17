# MuseEcho v0.1.0 离线运行时 Release 设计

## 目的与批准

用户批准了离线运行时包，并要求 Codex 自动继续，直至正式 GitHub Release 成功。接收者下载 Release 资产后，该软件包必须允许其在不再下载容器层或构建依赖的情况下运行和验证 MuseEcho。

本工作**不**声称当前 Dockerfile 可以使用 `--network none` 从源代码重建。因此，本次 Release 后工程发现 `ENG-010` 仍为 `BLOCKED`。

## Release 形态

正式的非预发布 GitHub Release 为 `v0.1.0`。它包含四项资产：

1. `museecho-app.tar`：从精确的 GREEN `main` SHA 重建的应用镜像，其证据边界为已记录 fallback 中的 identity/checksum/no-build Smoke；
2. `museecho-gateway.tar`：在同一 fallback 运行中重建的网关镜像，具有相同的证据边界；
3. `museecho-offline-runtime-v0.1.0.zip`：面向接收者的运行时工具包；
4. `SHA256SUMS.txt`：两个镜像归档和运行时工具包的校验和。

资产相互分离是因为 GitHub 对每项 Release 资产有大小限制。自动生成的源代码归档仍是源代码分发物，不能替代镜像归档。

## 运行时工具包

zip 包含：

- `offline-runtime.ps1`，提供 `Verify`、`Import`、`Start`、`Smoke` 和 `Stop` 操作；
- `compose.yaml`，只包含运行时镜像引用，没有 `build` 段；
- `release-images.json`，为精确 main 本地 fallback 资产集生成并验证，用于绑定应用/网关镜像 ID 和 tar SHA-256 值；
- `scripts/container-smoke.ps1`，复用仓库现有脚本，用于检查真实 WAV 上传、分析完成、重启、持久化、加密、镜像 identity 和清理；
- `README.md` 和 `release-version.txt`。

若文件缺失、identity 数据畸形、镜像 ID 无效或 SHA-256 不匹配，`Verify` 将以失败关闭。`Import` 在 `docker load` 前执行验证，并检查加载的 `museecho-app:local` 和 `museecho-gateway:local` ID 是否与清单一致。`Start` 先执行导入，仅在不存在时创建一个外部 32 字节 Base64 `audio-kek`，然后使用 `--no-build` 启动 Compose。Compose 文件采用 `pull_policy: never`、仅限环回地址的 4173 端口 HTTPS、只读 Secret 绑定、只读根文件系统、丢弃 capabilities，并持久保存加密数据。`Stop` 保留数据卷。常规操作均不会删除数据卷。

`Smoke` 导入并验证镜像，然后以 no-build 模式运行现有隔离容器 Smoke。它生成的 Secret、WAV、容器、网络和数据卷都是临时的，即使失败也会移除。

## 维护者打包流程

`distribution` 作业仍是 Release 资格所需的构建和策略门禁。最终 main 运行通过，但其制品上传因 GitHub Actions 配额被跳过，因此没有留下可下载的字节来源。PowerShell 打包脚本接收证据目录和语义版本，依据两个 tar 验证 identity 清单、暂存运行时工具包、构建 zip 并生成 `SHA256SUMS.txt`。它不重建或重新标记镜像。

CI `distribution` 作业仅在现有镜像 identity、Compose、Secret、许可证、漏洞和 VEX 门禁通过后运行打包脚本。其配置会把两个镜像归档和生成的离线运行时资产保留到一个短期 Actions 制品中。对于 `v0.1.0`，作业虽通过，但保留步骤因配额被跳过。根据用户要求自动继续至正式发布成功的指示，获准的来源回退是：在精确 GREEN main SHA 上重建，并针对发布字节重新执行 Release identity、打包、校验和、no-build Smoke 以及发布后下载检查。因此，本 Release 的准确声明仅为同一源代码边界，以及针对实际发布字节完成的上述检查。GREEN main CI 可证明其内部构建通过已配置的许可证/漏洞/VEX 管线；但由于制品未保留，这些门禁不能作为发布 tar 字节的直接证据，也不主张发布字节与不可用 CI 输出逐字节相等。

## 接收者流程

接收者将全部四项资产下载到同一目录，在该目录解压 zip，启动 Docker Desktop，然后运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\offline-runtime.ps1 -Action Verify
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\offline-runtime.ps1 -Action Smoke
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\offline-runtime.ps1 -Action Start
```

随后打开 `https://localhost:4173`。Caddy 使用本地内部 CA，因此浏览器可能要求添加仅限 localhost 的证书例外。可选的第三方模型密钥不是必需项。若需停止并保留分析：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\offline-runtime.ps1 -Action Stop
```

## 失败处理

- 缺失或被修改的资产会在镜像导入前失败。
- 已加载镜像 identity 不匹配会在 Compose 启动前失败。
- Docker 引擎或 Compose 插件缺失时返回原始命令失败，不报告成功。
- 运行时流程中的 Compose 绝不构建或拉取镜像。
- Smoke 清理会报告清理失败，但不掩盖主失败。
- 如果 tag 目标不是最终 GREEN `main` SHA，或任何上传资产的校验和与本地发布资产集不同，则停止 Release 发布。

## 测试与验收

实现遵循 TDD。合成 PowerShell 测试使用假 Docker 和小型夹具归档，证明哈希失败关闭、identity 检查、no-build 启动、no-pull Compose 配置、Secret 生成和保留数据卷的停止行为。打包测试证明确定性文件选择、清单验证、zip 内容和校验和生成。

最终验收还要求：

1. 仓库全部质量门禁通过；
2. 使用当前 Docker 镜像或最终 CI 证据完成真实本地打包；
3. 隔离 no-build Smoke 到达分析 `complete`；
4. PR 重新以 `main` 为目标后 CI 为 GREEN；
5. 合并后的 `main` CI 为 GREEN；
6. 非草稿、非预发布的 GitHub Release `v0.1.0`，其 tag 指向已验证的 `main` SHA，且四项资产与 `SHA256SUMS.txt` 一致；
7. 交付文档已更新 Release URL、tag、SHA、run ID、离线运行时与离线源代码构建之间的准确区别，以及剩余学生/人工/部署边界。

## 发布记录

上述验收形态已于 2026-08-17 实现。实现和复审完成且 PR CI 通过后，PR #3 合并为 main SHA `d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1`；随后 main run `31997390847` 的 quality、E2E 和 distribution 均通过。非草稿、非预发布的 `v0.1.0` Release 于 `2026-08-17T05:54:50Z` 发布，恰好包含设计中的四项资产。发布后重新下载全部四项资产、重新计算哈希，并由解压后的工具包完成真实 no-build Smoke，形成证据重放。该发布记录只证明发布字节的 identity/checksum/no-build Smoke 和下载回验，不把未保留的 CI tar 描述为已审计归档，也不主张两者字节相同。`ENG-010`、公共 registry、GitLab、云部署及学生/人工门禁仍不在本次已完成 Release 声明范围内。
