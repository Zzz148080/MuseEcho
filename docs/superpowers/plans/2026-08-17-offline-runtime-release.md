# MuseEcho v0.1.0 离线运行时 Release 实施计划

> **供自主执行者使用：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐项实施本计划。步骤使用复选框（`- [ ]`）语法跟踪。

**目标：** 发布正式的 `v0.1.0` GitHub Release；其应用和网关镜像归档具备 identity/checksum/no-build Smoke 证据，可在不构建、不拉取的情况下验证、导入、Smoke 和运行。

**架构：** 现有 `distribution` 作业仍是必需的构建/安全门禁。一个小型 PowerShell 接收脚本验证 Release identity 清单、加载镜像 tar，并启动仅包含运行时内容的 Compose 文件；维护者脚本在不重建镜像的情况下打包这些文件和校验和。GitHub Actions 配额导致本应为 GREEN 的最终 `main` 制品未被保留，因此已发布 Release 使用任务 6 中记录并获用户授权的来源回退：从精确 GREEN main SHA 重建，针对这些字节重新执行 Release identity、打包/校验和、no-build Smoke 和下载验证；不得声称其与不可用 CI tar 字节相等，也不得声称许可证/漏洞/VEX 是这些发布字节的直接证据。

**技术栈：** PowerShell 7/Windows PowerShell 5.1、Docker Engine/Desktop、Docker Compose v2、GitHub Actions、Python Release identity 验证器、Markdown、Git/GitHub Release。

**当前状态（2026-08-17）：** 任务 1–4 的实现与复审、PR CI、合并及随后 main CI、获批的本地来源回退、Release 发布和下载证据重放均已按此顺序完成。由于 Actions 未保留制品，原计划下载精确 main 制品的步骤仍明确为未完成。任务 6 步骤 4 是本文档对账；步骤 5 仍未完成，须等待其 PR CI 及随后 main CI 通过，并确认重新读取的已发布资产未变化。

## 全局约束

- Release 版本严格为 `v0.1.0`；既不是草稿，也不是预发布。
- 运行时资产为 `museecho-app.tar`、`museecho-gateway.tar`、`museecho-offline-runtime-v0.1.0.zip` 和 `SHA256SUMS.txt`。
- 接收者启动流程绝不构建或拉取；Compose 使用 `pull_policy: never`，每次 `up` 均使用 `--no-build`。
- Release 镜像的源代码与策略边界是精确的 GREEN `main` SHA。由于其 Actions 制品未保留，已发布镜像字节来自记录在案的本地来源回退，并保留自身已验证的 `release-images.json` identity；不声称其与不可用 CI tar 字节相等。
- 默认接收流程保留加密数据卷，绝不公开删除数据卷的开关。
- 不需要第三方模型密钥。
- `ENG-010` 仍为 `BLOCKED`：离线运行时不等于离线源代码重建。
- 现有任务 23 证据保留为历史证据，不重写为当前 Release 证据。
- `REFLECTION.md` 变更仅限此前获准修正的过时 GitHub 证据句和客观 Release 事实；不重写学生主观结论。

---

### 任务 1：接收者运行时契约

**文件：**
- 创建：`release/offline-runtime/offline-runtime.ps1`
- 创建：`release/offline-runtime/compose.yaml`
- 创建：`release/offline-runtime/README.md`
- 创建：`release/offline-runtime/release-version.txt`
- 创建：`scripts/test-offline-runtime.ps1`

**接口：**
- 输入：同一制品目录中的 `release-images.json`、`museecho-app.tar` 和 `museecho-gateway.tar`。
- 输出：`offline-runtime.ps1 -Action Verify|Import|Start|Smoke|Stop`，以及名为 `museecho-offline` 的仅运行时 Compose 项目。

- [x] **步骤 1：编写接收者 RED 测试**

创建一个任务临时夹具，其中包含两个小型归档替身、字面 schema-v1 Release identity、假 Docker 可执行文件和真实接收者脚本。测试必须断言可观察行为：

```powershell
$verify = Invoke-Receiver -Action Verify
if ($verify.ExitCode -ne 0) { throw $verify.Output }

$start = Invoke-Receiver -Action Start -SecretsDirectory $secretRoot
if ($start.ExitCode -ne 0) { throw $start.Output }
$dockerLog = Get-Content -Raw -LiteralPath $fakeDockerLog
if ($dockerLog -match '(?m)\b(build|pull)\b') { throw 'offline receiver used network/build path' }
if ($dockerLog -notmatch 'compose .* up .*--no-build') { throw 'offline receiver omitted --no-build' }

$key = [Convert]::FromBase64String((Get-Content -Raw "$secretRoot/audio-kek"))
if ($key.Length -ne 32) { throw 'receiver did not generate a 32-byte KEK' }
```

增加独立夹具运行，证明修改后的 tar 会在任何 Docker 调用前失败，错误的已加载应用镜像 ID 会在 Compose 前失败，并且 `Stop` 不包含 `--volumes`。

- [x] **步骤 2：运行接收者测试并确认 RED**

运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-offline-runtime.ps1
```

预期：由于缺少 `offline-runtime.ps1` 或其操作而以非零状态退出。失败必须发生在假 Docker 成功路径可能满足断言之前。

- [x] **步骤 3：实施最小接收者和 Compose 运行时**

接收者在导入前验证清单和归档哈希：

```powershell
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
foreach ($name in @('app', 'gateway')) {
    $entry = $manifest.images.$name
    if ($entry.image_id -notmatch '^sha256:[0-9a-f]{64}$') {
        throw "$name release image id is invalid"
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $tarPaths[$name]).Hash.ToLowerInvariant()
    if ($actual -ne $entry.tar_sha256) { throw "$name release tar SHA-256 mismatch" }
}
```

`Import` 对每个已验证 tar 运行 `docker load --input`，并将 `docker image inspect --format '{{.Id}}'` 与清单比较。`Start` 仅在外部 Secret 不存在时创建它，然后运行：

```powershell
docker compose --file $composePath --project-name museecho-offline config --quiet
docker compose --file $composePath --project-name museecho-offline up --detach --wait --no-build
```

Compose 文件不包含 `build` 键，使用 `pull_policy: never`，只绑定 `127.0.0.1:${MUSEECHO_HTTPS_PORT:-4173}:8443`，以只读方式挂载 Secret 目录，并保留现有的非 root/只读/cap-drop 健康边界。`Stop` 运行不带 `--volumes` 的 `down --remove-orphans`。`Smoke` 先导入，再使用当前 Release 清单调用工具包内的 `scripts/container-smoke.ps1 -NoBuild`。

- [x] **步骤 4：运行接收者 GREEN 和变异探针**

运行同一测试命令。预期：`Offline runtime synthetic tests passed.`。随后通过测试自身的夹具模式临时修改假应用 ID 和一个 tar 字节；每次运行都必须在对应契约处失败，且不留下夹具残留。

- [x] **步骤 5：提交任务 1**

```powershell
git add -- release/offline-runtime scripts/test-offline-runtime.ps1
git commit -m "feat: add verified offline runtime loader"
```

---

### 任务 2：当前 Release identity 的 no-build Smoke

**文件：**
- 修改：`scripts/container-smoke.ps1`
- 修改：`scripts/test-container-contract.ps1`

**接口：**
- 输入：旧版任务 23 安全清单或当前 `release-images.json` 清单。
- 输出：单一 no-build Smoke 入口；从 `images.<name>.image_id` 派生当前应用/网关 ID，同时保留旧版验证。

- [x] **步骤 1：增加失败的当前清单测试**

用以下字面当前清单扩展合成契约：

```powershell
[ordered]@{
    schema_version = 1
    images = [ordered]@{
        app = [ordered]@{ image_id = $appDaemonId; tar_sha256 = ('a' * 64) }
        gateway = [ordered]@{ image_id = $gatewayDaemonId; tar_sha256 = ('b' * 64) }
    }
} | ConvertTo-Json -Depth 4
```

在不提供四个旧版预期 ID 参数的情况下调用 `container-smoke.ps1 -NoBuild -ReleaseManifest <path>`。断言成功；随后把一个 ID 变为畸形值，并断言在 Compose `up` 前失败。

- [x] **步骤 2：确认 RED**

运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-container-contract.ps1
```

预期：当前清单失败，因为现有 Smoke 要求四个旧版 ID，并读取 `app.daemon_image_id`。

- [x] **步骤 3：实现双 schema identity 解析**

增加一个返回预期 daemon ID 的解析器。对于当前 schema，它严格验证 `app` 和 `gateway`，二者均为小写 SHA-256 镜像 ID，并拒绝重复 ID。对于旧版 schema，保留每个现有 daemon/config 比较。只有派生出的 daemon ID 用于检查 Docker tag 和运行中容器。

设置 `-NoBuild` 时，只要求 `compose.yaml`；构建模式 Smoke 仍要求 Dockerfile 和 Caddyfile。这样生成的运行时工具包无需携带构建输入。

- [x] **步骤 4：确认 GREEN 和旧版兼容性**

运行契约脚本。预期：旧版路径和当前清单路径均通过；错误 tag、互换 identity、重复 identity、畸形 identity 和运行时漂移探针均在测试框架内以失败关闭。

- [x] **步骤 5：提交任务 2**

```powershell
git add -- scripts/container-smoke.ps1 scripts/test-container-contract.ps1
git commit -m "test: accept audited release identity in no-build smoke"
```

---

### 任务 3：维护者打包与 CI 保留

**文件：**
- 创建：`scripts/prepare-offline-release.ps1`
- 创建：`scripts/test-prepare-offline-release.ps1`
- 修改：`.github/workflows/ci.yml`

**接口：**
- 输入：`-Version 0.1.0`、`-EvidenceDirectory tmp/image-security`，以及两个待验证 tar 文件和 `release-images.json`。
- 输出：`tmp/offline-release/museecho-offline-runtime-v0.1.0.zip` 和 `tmp/offline-release/SHA256SUMS.txt`。

- [x] **步骤 1：编写打包 RED 测试**

使用 `tests/unit/test_release_identity.py` 已支持的小型有效 Docker-save 夹具 tar，或在任务临时目录中生成字面单镜像 tar 夹具。调用真实打包脚本并断言：

```powershell
$zip = Join-Path $output 'museecho-offline-runtime-v0.1.0.zip'
if (-not (Test-Path -LiteralPath $zip -PathType Leaf)) { throw 'runtime zip missing' }
Expand-Archive -LiteralPath $zip -DestinationPath $expanded
$required = @('offline-runtime.ps1','compose.yaml','release-images.json','README.md','release-version.txt','scripts/container-smoke.ps1')
foreach ($path in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $expanded $path))) { throw "zip missing $path" }
}
```

解析 `SHA256SUMS.txt`，并独立计算两个输入 tar 和 zip 的哈希。修改 identity 清单中的 tar 摘要，断言打包失败且不生成输出 zip。

- [x] **步骤 2：运行打包测试并确认 RED**

运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-prepare-offline-release.ps1
```

预期：由于打包脚本尚不存在而以非零状态退出。

- [x] **步骤 3：实施确定性打包**

脚本用 `^\d+\.\d+\.\d+$` 验证 `Version`，针对两个 tar 调用现有 Python identity 验证器，只暂存六个指定工具包文件，以不带 BOM 的 UTF-8 写入 `v$Version`，创建 zip，并按以下格式生成排序后的小写校验和：

```text
<64 lowercase hex>  museecho-app.tar
<64 lowercase hex>  museecho-gateway.tar
<64 lowercase hex>  museecho-offline-runtime-v0.1.0.zip
```

任务临时暂存目录在 `finally` 中删除；仅在显式解析的输出目录中替换输出文件。

- [x] **步骤 4：向 CI 增加打包门禁**

在 `quality` 中运行两个合成 PowerShell 测试。在 `distribution` 中，所有 identity/许可证/漏洞/VEX 门禁通过后运行打包脚本，并将现有保留制品的路径改为：

```yaml
path: |
  tmp/image-security/
  tmp/offline-release/
```

仅证据保留使用 `continue-on-error`；打包本身会阻断作业。

- [x] **步骤 5：确认 GREEN**

运行两个 PowerShell 测试、YAML 解析/契约测试、Release identity 单元测试和 `git diff --check`。预期：零失败，且没有临时残留。

- [x] **步骤 6：提交任务 3**

```powershell
git add -- scripts/prepare-offline-release.ps1 scripts/test-prepare-offline-release.ps1 .github/workflows/ci.yml
git commit -m "build: package audited offline runtime assets"
```

---

### 任务 4：Release 前文档与交付契约

**文件：**
- 修改：`README.md`
- 创建：`RELEASE_REPRODUCTION.md`
- 修改：`SPEC.md`
- 修改：`PLAN.md`
- 修改：`DECISIONS.md`
- 修改：`AGENT_LOG.md`
- 修改：`BLOCKERS.md`
- 修改：`COURSE_DELIVERY_CHECKLIST.md`
- 修改：`DELIVERY_REPORT.md`
- 修改：`REFLECTION.md`
- 修改：`REFLECTION_NOTES.md`
- 现有验证器要求时修改：`docs/audits/FUNCTIONAL_AUDIT.md`
- 现有验证器要求时修改：`docs/audits/ENGINEERING_AUDIT.md`
- 测试：现有交付、验收、工程和最终契约测试

**接口：**
- 输入：已实现的接收者/打包行为，以及已知 Release URL `https://github.com/Zzz148080/MuseEcho/releases/tag/v0.1.0`。
- 输出：一致区分离线运行时 PASS 与离线源代码构建 BLOCKED 的措辞。

- [x] **步骤 1：编写或更新失败的交付契约测试**

仅在现有检查器会读取文档的位置增加行为文档契约断言。发布前所需含义为：

```text
offline-runtime=READY_FOR_RELEASE
offline-source-build=BLOCKED:ENG-010
deployment=NOT_RUN
```

检查器必须拒绝删除 `ENG-010`、把运行时工具包称为离线源代码构建或声称已完成云部署的文本。

- [x] **步骤 2：确认文档为 RED**

运行聚焦交付/验收/工程测试。预期：失败，因为当前文档仍称不存在 Release，过时的反思记录也仍称最终 GitHub 证据待完成。

- [x] **步骤 3：更新完整项目时间线**

记录接收者先决条件、四项资产、三个接收者命令、localhost CA 警告、数据保留行为、不需要供应商密钥，以及精确 Release 边界。按时间顺序更新状态块。当学生/人工门禁和 `ENG-010` 仍存在时，保持 `MUSEECHO V1 PARTIALLY READY`。

在 `REFLECTION.md` 中，只替换此前获准修正的过时客观句：最终 GitHub 证据由合并 SHA `d99e7b95...` 上的 main run `31997390847` 关闭，而正式离线源代码构建及学生/人工门禁仍未关闭。在 `REFLECTION_NOTES.md` 中，保留 run `31687703913` 和产品 run `31966788273` 作为历史边界，增加 main run `31997390847`，并只关闭最终 GitHub/Release 证据。Release 证据是带日期的客观记录，不是重写后的主观结论。

- [x] **步骤 4：确认文档为 GREEN**

运行交付验证器、验收验证器、工程检查器、聚焦单元测试、Secret 扫描和 `git diff --check`。预期：全部通过，且非 READY 边界不变。

- [x] **步骤 5：提交任务 4**

```powershell
git add -- README.md RELEASE_REPRODUCTION.md SPEC.md PLAN.md DECISIONS.md AGENT_LOG.md BLOCKERS.md COURSE_DELIVERY_CHECKLIST.md DELIVERY_REPORT.md REFLECTION.md REFLECTION_NOTES.md docs/audits
git commit -m "docs: prepare v0.1.0 offline runtime release"
```

---

### 任务 5：完整验证、PR 集成与 main 证据

**文件：**
- 不计划修改源代码；如果验证暴露缺陷，则按 TDD 修复。

**接口：**
- 输入：任务 1–4 的提交。
- 输出：GREEN 功能 PR 和 GREEN 的已合并 `main` 运行，用于确立源代码/策略边界；保留的 distribution 制品在可用时提供 Release 资产，否则必须使用明确记录的来源回退。

- [x] **步骤 1：验证完整分支**

运行仓库的 PowerShell 验证门禁、Python 套件、前端测试/构建、E2E 类型检查、容器契约、Secret 扫描和真实 Docker distribution 构建。针对生成的当前 `release-images.json` 运行 no-build Smoke。记录精确计数、镜像 ID、tar 哈希和退出码。

- [x] **步骤 2：复审最终差异并推送**

确认没有生成的 tar、zip、密钥、缓存、数据库或临时证据被跟踪。以非强制方式推送 `codex/expand-common-audio-formats`。

- [x] **步骤 3：重新设定 PR #3 的目标并完成它**

将 PR #3 的目标从 `codex/fix-mp3-cover-art` 改为 `main`，检查扩大的比较范围，标记为可审阅，并等待精确 head SHA 上的 `quality`、`e2e` 和 `distribution` 达到成功终态。通过系统化调试和 TDD 修复任何失败，然后重复验证。

- [x] **步骤 4a：合并并验证 main CI**

使用仓库允许的合并方式合并 PR #3。等待所得合并 SHA 上的 `main` CI 运行通过全部三个作业。

- [ ] **步骤 4b：下载精确 main 制品（未完成）**

`image-vulnerability-evidence` 上传因 GitHub Actions 制品配额被跳过。没有留下可下载的 CI tar，因此无法获得 CI 内部 tar 与 Release 的精确字节 identity，也不作此声明。任务 6 记录另行获准的来源回退。

---

### 任务 6：发布 v0.1.0 并对账最终证据

**文件：**
- 为 GitHub 正文在本地创建：`tmp/release-v0.1.0-notes.md`（绝不跟踪）
- 发布后修改：任务 4 中承载当前 Release 证据的交付/状态文档

**接口：**
- 输入：精确 GREEN `main` SHA，以及其保留的 distribution 制品；若因保留失败而不可用，则输入一个经明确授权的来源回退，且必须具有 Release identity、打包/校验和、no-build Smoke 和发布后下载验证。
- 输出：正式 GitHub Release URL、tag、资产、校验和及发布后文档提交。

- [ ] **步骤 1a：从保留的最终 main 制品准备（未完成）**

最终 `main` 制品无法提取，因为保留步骤因配额被跳过。这条计划中的来源路径保持未完成，不得事后描述为成功。

- [x] **步骤 1b：执行获批的精确 main 本地来源 fallback**

从精确 GREEN main SHA `d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1` 重建，然后重新执行 Release identity、打包、`SHA256SUMS.txt` 每个条目以及完整 no-build Smoke。只发布该已验证的本地资产集。再次下载发布字节，重复哈希/identity/Smoke 验证，并记录 GREEN main 的许可证/漏洞/VEX 门禁适用于其内部构建，而不能证明发布 tar 字节；不声称发布字节与不可用 CI 输出相等。

- [x] **步骤 2：创建 tag 和正式 Release**

在已验证的 `main` SHA 上创建带注释 tag `v0.1.0`。发布标题为 `MuseEcho v0.1.0` 的非草稿、非预发布 Release，并恰好上传四项资产。Release 说明以接收者复现命令开头，并注明不包含云部署和离线源代码重建。

- [x] **步骤 3：验证 GitHub 发布**

从 GitHub 重新读取 Release。确认 tag 目标、发布状态、资产名称、资产大小和可下载字节。重新计算下载副本哈希，并与 `SHA256SUMS.txt` 比较。

- [x] **步骤 4：对账发布后文档**

向客观交付时间线追加精确 Release URL、解引用后的 tag 目标 SHA、main CI run ID、发布 UTC 时间，以及资产哈希/大小。记录 Actions 配额导致的来源 fallback，并明确避免声称与未保留 CI 输出字节相等。增加失败关闭的证据重放验证器和字段绑定清单。保留 `ENG-010`、部署及学生/人工边界。通过 PR 将此次对账提交并推送到 `main`。

- [ ] **步骤 5：运行最终证据验证**

等待发布后文档 CI 通过。确认 GitHub Release 仍指向原始 GREEN main SHA，全部四项资产仍可用，仓库树不包含生成的资产/Secret，且每份当前文档均写明相同的 Release 状态和剩余阻塞项。
