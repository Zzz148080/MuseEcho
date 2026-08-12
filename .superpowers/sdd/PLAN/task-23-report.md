# Task 23 — Engineering Audit 与高风险缺陷闭环报告

## 状态

`DONE_WITH_CONCERNS`。本地 Engineering Audit、全部 6 项指定风险重评、4 个 High finding 闭环、2 个 Medium finding 闭环、锁定 Linux 全量回归和离线镜像安全链均已完成。最终审计为：

| Severity | OPEN | FIXED | ACCEPTED | BLOCKED |
| --- | ---: | ---: | ---: | ---: |
| Critical | 0 | 0 | 0 | 0 |
| High | 0 | 4 | 0 | 0 |
| Medium | 0 | 2 | 0 | 4 |
| Low | 0 | 0 | 0 | 0 |

四个 Medium blocker 分别是当前浏览器/前端完整链、远程 GitHub/GitLab CI、目标云与公网/恢复证据、正式 current-source Dockerfile 的离线可重建性。宿主还缺少 brief 最终 wrapper 所需的 `pwsh` 和 `uv`。这些边界没有被伪装为成功，因此状态不是无条件 `DONE`。

计划主提交为 `audit: close engineering risks`，实际实现从 `31b2351fcf308b4aeb3ce8b1931afafe3350522d` 延续到最终复审修复 `f697d13`。`audit/23-engineering` 已非 force 推送并建立 GitHub 草稿 PR #1；未执行云部署或代写学生 `REFLECTION.md`。

## 审计合约

- 人可读记录位于 `docs/audits/ENGINEERING_AUDIT.md`；checker 为纯标准库 `scripts/check_engineering_audit.py`。
- 固定 15 个工程域、10 个真实 finding 和 36 个 evidence ID。每个 finding 均固定 ID、domain、severity、status、description、evidence、owner、disposition 与 verification/reopen condition。
- checker 拒绝缺失/重复域、finding 和 evidence，非法 schema/status/severity，未来时间，FIXED 无 RED+GREEN，空泛 ACCEPTED/BLOCKED，OPEN Critical/High，finding 删除或 severity 降级，文件存在冒充验证，同一证据换 ID，以及改写为无意义成功的 scan/audit/release 命令。
- 镜像安全证据不只信任 Markdown。Checker 解析 `docs/audits/evidence/task23-security-manifest.json`，固定其 normalized SHA-256，并交叉当前 vulnerability policy 与完整 runtime boundary digest。
- 完整 1.8MB Trivy raw、366MB tar 和 1.2GB DB 不纳入 Git；本轮原始材料保留在 ignored Task 23 证据目录及 Task 20 worktree cache。提交的 2.6KB deterministic compact manifest 固定工具/DB/image/config/tar/raw/inventory/VEX/tuple/policy/runtime digest、计数、exit 与 UTC。

## TDD：checker RED → GREEN

首个测试先于 checker/audit 创建。`2026-08-11T10:40:00Z`：

```powershell
uv run pytest tests/unit/test_engineering_audit.py -q
```

预期 RED：collection exit `1`，`ModuleNotFoundError: scripts.check_engineering_audit`。

初始实现 focused GREEN（已由后续复审轮取代）：

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_engineering_audit.py -q
```

结果：`27 passed in 1.73s`，exit `0`。CLI 结果为 `engineering findings validated: 9 (BLOCKED/Medium=3, FIXED/High=4, FIXED/Medium=2)`，exit `0`。

Mutation 覆盖固定域、schema、重复/删除/降级、时间、RED+GREEN、ACCEPTED/BLOCKED、OPEN Critical/High、证据换 ID、文件存在冒充、虚假 scan/verify、compact manifest 与 current policy/runtime drift。

## 指定风险与真实 finding 闭环

### ENG-001 High FIXED — 多文件 Bash parse harness

- RED：把无效语法放入 fresh-checkout inventory 的最后一个 shell 文件；旧 harness 只调用一次 `bash -n file1 file2 ...`，exit `0`，证明后续文件未被解析。
- 修复：每个 tracked 与 fresh-checkout shell 文件分别启动一次 `bash -n`，任一失败即 fail closed。
- GREEN：`powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/deploy/test_shell_line_endings.ps1`，8 个文件逐个解析，exit `0`。

### ENG-002 High FIXED — release identity 空 comparison class

- RED：manifest-only verify 在 image-id、tar、scan 三类 comparison inventory 全空时返回成功。
- 修复：至少要求一个完整 comparison class；保留现有 CI 的 tar+scan 语义和可选 image-id，partial inventory 仍失败。
- GREEN：`tests/unit/test_release_identity.py` 为 `10 passed`，exit `0`；current app/gateway tar+scan identity verify exit `0`。

### ENG-003 High FIXED — development partial startup/cleanup

- RED：部分 `compose up` 失败可能不执行 down；down 失败可能覆盖或吞掉 startup 主错误。
- 修复：进入 startup 前即标记 cleanup required，finally 总是执行 down；保留主错误并同时报告 cleanup error。
- GREEN：新的 synthetic `scripts/test-development-smoke.ps1` 覆盖 partial-start、primary-only、cleanup-only 与 combined failure，exit `0`。

### ENG-004 Medium FIXED — container smoke 无离线 no-build 路径

- RED：旧 smoke 无条件 build，cache miss 可进入锁定 `npm ci` 的网络获取；没有 local identity 校验或 `compose up --no-build`。
- 修复：新增显式 `-NoBuild`/`-DockerCommand` 路径，在启动前检查 app/gateway exact local sha256 ID，强制 `compose up --no-build`，默认生产 build smoke 语义不变。
- GREEN：synthetic contract 证明 no-build 不调用 build；真实 no-build smoke 校验 app `655f785560e3…` 与 gateway `2235e208dd7d…`，完成 WAV、restart、ciphertext、history、cleanup，exit `0`。

### ENG-005 Medium FIXED — production observability

- RED：`museecho.observability` 不存在；生产仅返回简单 health，缺少安全 request ID、阶段耗时、队列/失败/清理/fallback 指标。
- 修复：加入线程安全 runtime metrics、32-hex request ID、稳定 error code、safe resource summary、liveness/readiness 区分，并接入 queue、stage、cleanup、LLM/fallback。日志禁止 header、原始文件名、音频、完整问题和 token。
- GREEN：focused observability/health/runtime 为 `14 passed`；安全、访问、上传、队列、repository、cleanup 比例回归为 `82 passed, 1 skipped`。

### ENG-009 High FIXED — dirty Docker context egg-info

- RED：Task 20 runtime policy/image 包含 6 个 gitignored `src/museecho.egg-info/*`，clean checkout 不存在；`.dockerignore` 未排除任意 `*.egg-info`。
- 修复：`.dockerignore` 增加 `**/*.egg-info`；正式 Dockerfile clean context contract 证明不会 COPY 该类目录；受控审计派生层显式删除旧 base 残留；policy runtime manifest 更新为完整 clean current boundary，不改 67 条 CVE statement。
- GREEN：clean-context test、committed-policy equality 与完整 runtime drift mutations 全部通过；审计镜像内无 egg-info。

### BLOCKED Medium

- `ENG-006`：当前 Chrome/accessibility/workflow 以及 current frontend type/build。宿主 Chrome `151.0.7922.76` 存在且 no-build HTTPS 可达，但锁定 root Playwright junction 目标已消失，当前 exact-lock frontend cache 缺 `@types/node`。禁止下载后不能启动完整链。
- `ENG-007`：GitHub Actions/GitLab CI 需要远程仓库与 runner 授权；本轮只验证本地定义/合约，不声称远程结果。
- `ENG-008`：腾讯云、DNS、SSH、公网 TLS、跨网、24h、backup/restore、live rollback 需要外部 target 授权；本轮没有以本地证据替代。

## 当前 runtime 与离线镜像安全链

Base 到当前 worktree 的 runtime/build 边界只改变 4 个观测性相关 source 文件并新增 `src/museecho/observability.py`；Dockerfile、Compose、Caddy、Python/npm manifests 和 locks 均未变。因为 source 已变，Task 20 镜像不能直接声称为 current artifact。

正式 Dockerfile 使用 `--pull=false --network none` 重建时，锁定 pip/apt BuildKit layer 在当前 builder cache 不可用，构建 fail closed，exit `1`。没有为 GREEN 开放网络或改 Dockerfile。用于本地审计的是明确标为非发布的受控 current-source derivative：

- base daemon image ID：`sha256:96cd900d6c17c360b01665362330aca8ef032b0d4d1f140659a52265ce47f39c`
- current audit daemon/config ID：`sha256:655f785560e3c1163397fab3095411c29374ab6fcd6782211bf9a53aafcd3be4` / `sha256:ee74a82050c6c8d5d499cfd04ca1fd70112a44f8ef71d5549efbbcbacfd021c0`
- audit tar SHA-256：`f6d396b708da44d6a1bb8882486906dc608eac85e0416cac674685c859987d44`
- gateway daemon/config ID：`sha256:2235e208dd7d8568c735ba19f1969644384626296eaff5cabb41acfaed86c547` / `sha256:8cc0429e45fd48c911a92fd8504c1f3c14daccb0fee8a24529d72af51b0b4053`

Derivative 保留 production UID 10001、CMD 与环境，只删除旧 egg-info 并覆盖 current source。它仅用于 current-source Linux regression、no-build smoke 与安全审计，禁止当作正式 Dockerfile release artifact。

离线 scanner 边界：Trivy `0.70.0`，image digest `sha256:be1190afcb28352bfddc4ddeb71470835d16462af68d310f9f4bca710961a41e`；Task 20 DB SHA-256 `fbd7a1751c20449fc014ce29514c745d16d196d2c67ad6fb88315ac7357d62bf`，UpdatedAt `2026-08-09T12:54:52.355618652Z`。DB 子目录只读挂载，fanal cache 使用 container tmpfs；全部扫描使用 `--network none --skip-db-update --skip-java-db-update --skip-version-check --offline-scan`。

| Gate | UTC | Exit | 结果 |
| --- | --- | ---: | --- |
| Current app raw | `2026-08-11T11:44:08Z` | 0 | 181 occurrences；67 unique CVE；12 Critical + 169 High；raw/tuple SHA fixed |
| Exact policy/runtime audit | `2026-08-11T11:44:30Z` | 0 | 181 tuple、38 affected packages、52 clean runtime files、67 OpenVEX statements |
| App VEX gate | `2026-08-11T11:50:41Z` | 0 | residual High/Critical = 0 |
| Gateway raw/gate | `2026-08-11T11:36:24Z` / `11:51:12Z` | 0 / 0 | unsuppressed occurrences = 0 |
| Release tar+scan identity | `2026-08-11T11:44:20Z` | 0 | app/gateway config ID、tar SHA、raw scan ImageID 全一致 |

Observability diff 另外检查了 decoder、FFmpeg、动态 SQL、subprocess 和外部执行入口，未新增任何路径；因此复用 67 条逐 CVE reachability statement 是在完整 policy/runtime mutation GREEN 后进行，不是自动沿用或 VEX 降级。

## 初始实现验证（已由后续复审轮取代）

本节保留 Task 23 首次实现的历史证据；其中 `681 passed`、
Functional `29/11/0` 与 Engineering `9 findings / 3 blockers` 已被下文
review fix rounds 的 current `748 passed, 1 skipped`、`28/12/0` 与
`10 findings / 4 blockers` 取代，不得用于当前完成声明。

工具版本：Python `3.12.13`、pytest `9.1.1`、Ruff `0.16.2`、mypy `2.3.0`、Docker client/server `29.1.3`、Trivy `0.70.0`、Node `24.16.0`、npm `11.13.0`、Chrome `151.0.7922.76`、Git `2.48.1.windows.1`。宿主没有 `pwsh`、`uv` 或 ShellCheck。

| Gate | UTC | Command / boundary | Result |
| --- | --- | --- | --- |
| Static/type | `2026-08-11T11:21:30Z` | Ruff format/check + strict mypy src | 87 formatted files；46 source files；exit 0 |
| Locked Linux full | `2026-08-11T12:14:10Z` | `scripts/container-pytest.ps1 -Image museecho-app:task23-audit` | `681 passed in 248.21s`；wrapper cleanup exit 0 |
| Risk regression | `2026-08-11T12:07:35Z` | runtime security/access/upload/repository/cleanup/queue | `82 passed, 1 intentional skip`；exit 0 |
| Five-minute budget | `2026-08-11T12:06:30Z` | locked Linux ffmpeg-capable runtime | `1 passed in 51.24s`；exit 0 |
| Frontend Vitest | `2026-08-11T11:54:30Z` | current frontend; retained offline cache | 12 files / 66 tests；exit 0 |
| Frontend type/build | `2026-08-11T11:56:55Z` | exact current lock cache | NOT_RUN；missing `@types/node`, no download |
| Current Chrome E2E | `2026-08-11T12:01:00Z` | installed Chrome + reachable no-build HTTPS | NOT_RUN；missing locked Playwright cache |
| Secret real | observed by `2026-08-11T12:27:51Z` | `scripts/secret-scan.ps1` | 210 tracked/non-ignored files；exit 0 |
| Secret synthetic | `2026-08-11T11:57:18Z` | `scripts/test-secret-scan.ps1` | credential/error mutations passed；exit 0 |
| License/dependency | `2026-08-11T11:57:35Z` | stdlib license audit + offline lock parse | policies/inventories passed；exit 0 |
| No-build smoke | `2026-08-11T12:00:10Z` | exact local IDs + `compose up --no-build` | real WAV/restart/ciphertext/history/cleanup；exit 0 |
| Functional/Engineering audits | observed by `2026-08-11T12:25:38Z` | both checker unit suites and CLIs with a unique worktree basetemp | `61 passed in 15.76s`; Functional `29 PASS / 11 PARTIAL / 0 FAIL`; Engineering 9 findings；exit 0 |

Host five-minute test originally failed because host lacks ffmpeg/ffprobe；同一测试在实际锁定 Linux runtime 中通过，所以没有误判为产品缺陷。Fresh-checkout Bash 门通过；ShellCheck 因宿主/WSL均无该工具而未运行。

## 最终 brief command 与等价门

Brief 要求在提交前运行以下 exact command：

```powershell
pwsh -File scripts/verify.ps1; if ($LASTEXITCODE) { exit $LASTEXITCODE }; uv run python scripts/check_engineering_audit.py docs/audits/ENGINEERING_AUDIT.md
```

在 `2026-08-11T12:25:38Z` 前逐字运行。`pwsh` 与 `uv` 均被 PowerShell 报告为 `CommandNotFoundException`，整体 exit `1`；因此 `verify.ps1` 和尾随 checker 没有由这个 wrapper 启动。没有下载工具来凑形式。

等价门不依赖缺失 wrapper：直接使用锁定 `.venv`、Windows PowerShell 5.1 和 locked/current-source Linux 审计镜像，覆盖 Ruff、mypy、681-test Linux full、27-test Engineering checker、35-test Functional checker、PowerShell lifecycle/container/shell contracts、Secret、license、frontend Vitest、no-build production smoke、five-minute budget、offline raw→audit→VEX/gateway 与 release identity。当前 frontend type/build、Chrome E2E 和远程/公网门仍如实 NOT_RUN/BLOCKED。

## 自审与 concerns

自审逐项检查了源/构建 manifest 差异、no-build 不进入 build、cleanup 双错误保留、release comparison 非空、checker mutation、audit finding/证据交叉、egg-info clean context、observability 敏感信息与外部执行路径、VEX identity/policy drift、容器/volume/network/task-temp cleanup 以及 `git diff --check`。

保留 concerns：

1. 正式 Dockerfile current-source rebuild 在当前离线 BuildKit cache 无法完成；受控 derivative 不是 release artifact。
2. 一次 frontend `--pull=false --network none` cache probe 仍执行了 registry metadata/auth resolution；容器网络禁止了 npm 获取，发现后不再重复 build。没有执行 host `npm ci`。
3. 当前 exact-lock frontend type/build 和 Chrome E2E 因 retained cache 缺失未重跑；Task 22 历史成功只作历史参考，不作为 Task 23 current PASS。
4. exact wrapper 因宿主缺 `pwsh`/`uv` 不可运行；ShellCheck 也不可用。没有联网修复环境。
5. 远程 CI、腾讯云/DNS/SSH、公网 TLS/跨网/24h/backup/rollback 与学生人工验收均未运行，继续由 Functional Audit/`BLOCKERS.md` 保持开放。
6. 最后一轮 host pytest 初次在全局 `C:\Users\P\AppData\Local\Temp\pytest-of-P` 枚举时被 ACL 拒绝，54 项均为 fixture setup error；改用此前不存在的 worktree 内 `--basetemp=tmp/task23-pytest-final-20260811-a` 后相同 61 项全部通过。没有更改测试或产品逻辑来绕过失败。

结论只适用于当前本地提交边界及 compact manifest 固定的离线审计身份；不声称部署完成、远程 CI 通过或公开发布完成。

## Review fix round 1/5 (base `47b203e`)

### Review findings and TDD closure

| Review area | RED | GREEN |
| --- | --- | --- |
| Independent FIXED/security evidence | 40 failed, 3 passed, 24 deselected | 43 passed, 24 deselected |
| Trusted no-build identity and repeated start | synthetic contract exit 1 | wrong/duplicate/swapped/runtime-drift mutations rejected; both starts require `--no-build`; exit 0 |
| Safe 500/background failure and waiting queue | 5 failed, 12 passed | 17 passed |
| Development cleanup-only semantics | lifecycle contract exit 1 | partial-start, primary-only, cleanup-only, combined passed |
| Functional Task 23 truth | 2 new assertions failed | 36 acceptance tests and CLI: 28 PASS / 12 PARTIAL / 0 FAIL |
| Direct Linux checker CLI | outside-repository `ModuleNotFoundError: scripts` | package and direct-script entry points passed |
| Cross-document Functional statistics | locked Linux: 727 passed, 1 stale `(29,11,0)` failure | delivery/audit focused suite 112 passed and all current documents use `(28,12,0)` |

The checker now fixes every finding's relevant RED/GREEN kind, command, path,
result, and coverage independently of the Markdown conclusion. E020-E025 have
complete command/flag/path/result contracts. Every compact-manifest field has a
coherent mutation, the entire object and normalized digest are fixed, and the
real runtime-boundary builder is rerun against current source and policy.

### Production behavior fixes

- `container-smoke.ps1 -NoBuild` requires a tracked trusted manifest and exact,
  distinct app/gateway daemon and config IDs. It validates Compose image tags,
  local daemon identities, and both running container identities after initial
  start and restart recovery. No no-build start can omit `--no-build`.
- The ASGI observability boundary ignores malicious inbound request IDs,
  generates a safe ID, adds it to stable unhandled-500 JSON, and never logs
  exception text, uploaded names/content, questions, headers, or tokens.
  Background failures expose only UUID task, pre-failure stage, and stable code.
- Queue depth reports waiting jobs only. Active-only, active-plus-waiting,
  retry, failure, and finally cleanup states are covered.
- Development smoke preserves primary and cleanup errors independently and has
  a real cleanup-only synthetic mode.

### Fresh offline current-source security chain

The review source changed `app.py`, `application/queue.py`, and
`observability.py`; Dockerfile, Compose, Caddy, Python/npm manifests, and locks
did not change. The controlled audit-only derivative removed stale base
egg-info and overlaid current `src/`; it is not a formal Dockerfile release.

| Identity/evidence | Value |
| --- | --- |
| app daemon/config | `sha256:b0231299644d58f7845e3c137faeca6f0f8cc7df2f3dbbcb656c75060128a724` / `sha256:89c7b7ad0a9d1708ce0cf277389c1fca7e13e05bb3937b602a6e2533cf9729ac` |
| app tar/raw | `c45998dfa5bc6c733799b036f07d64ebce081f23a4cd7497bcb323f72bb7e25e` / `3706685719c8295bbcaf746b9eb6816181aa1b63dcee80fb54855c8760377c0f` |
| app inventory/VEX | `2f47a957d0cceac194079d4f07cfa8e3952c12574fd1eee66c29f3c9fbd1e507` / `76b539cb0b71dbb6339150f322eaf049207d862d66a209fdb97bf64245c7afaa` |
| runtime/policy | `92f1f7b034daed01a6edac12de7293b56ea1abfd37b5e9448bb593c4a6079958` / `d01cc0559b7dffe6e2b93617493ae5a93ca99cb2630f6fc01c899a30b8013679` |
| release manifest | `c41563ea754d1f892d7dc596646d040582f6503f457f273cecc11f291558933a` |
| gateway raw | `64513e95a8ac9e5b9bcdf9a274a5e3108f08dbb6dbdb2ad97601c8eed7bbfd7d` |
| compact manifest | canonical finding tuple SHA-256 `4ab629f0f3b74d2357fcf19d195831c37adbee645d881e9a3fb4605224de35ba`; normalized manifest SHA-256 `c662ae5b52167dfb2dd74b52fb997e6f302820b45682ee08c3506169f4e83fd9` |

Trivy `0.70.0`, image digest
`sha256:be1190afcb28352bfddc4ddeb71470835d16462af68d310f9f4bca710961a41e`,
and the retained Task 20 DB SHA-256
`fbd7a1751c20449fc014ce29514c745d16d196d2c67ad6fb88315ac7357d62bf`
were unchanged. DB was read-only, cache was tmpfs, and all scanner commands
used `--network none`, offline, and no-update flags.

| Gate (UTC) | Exit/result |
| --- | --- |
| app raw `2026-08-11T19:07:10Z` | 0; 181 occurrences, 169 High, 12 Critical, 67 CVEs |
| gateway raw `2026-08-11T13:12:55Z` | 0; 0 occurrences |
| exact audit `2026-08-11T19:08:00Z` | 0; package ownership, 52-file runtime, 181 tuples, 67 statements exact |
| app VEX `2026-08-11T19:11:58Z` | 0; residual High/Critical 0 |
| gateway gate `2026-08-11T19:12:21Z` | 0; unsuppressed High/Critical 0 |
| tar+scan identity `2026-08-11T19:08:20Z` | 0; app/gateway config, tar, scan agree |

The observability/queue changes add no decoder, FFmpeg, dynamic SQL,
subprocess, or external execution path. Reuse of the 67 CVE assessments was
therefore accepted only after current runtime/policy mutation tests and the
fresh raw/audit/VEX chain passed. Complete raw JSON, tars, and the 1.2 GB DB
remain ignored; only the deterministic compact manifest is tracked.

### Fresh gates

- Trusted real no-build smoke: `2026-08-11T13:21:51Z`, exit 0 in 66.2s;
  identity checked across both starts; real WAV, restart, ciphertext, history,
  and cleanup passed; containers/volume/network empty afterward.
- Locked Linux attempts recorded rather than hidden: 721 passed / 6 stale
  audit failures; then 727 passed / 1 stale process-statistics failure; final
  `2026-08-11T13:45:34Z` run was `728 passed in 342.25s`, exit 0, cleanup empty.
- Static/type `2026-08-11T13:51:59Z`: Ruff format 93 files, Ruff lint, strict
  mypy 46 source files, and acceptance checker typing all exit 0.
- Secret/license `2026-08-11T13:52:11Z`: real Secret scan checked 210 files;
  synthetic mutations and reviewed license policy passed. Python 14 direct
  dependencies, root 8 lock packages, and frontend 218 lock packages parsed
  offline.
- Frontend Vitest remains the existing current 12 files / 66 tests. Frontend
  type/build and current Chrome E2E are NOT_RUN in this review; no npm or
  browser download was attempted.

Final focused verification at `2026-08-11T13:56:12Z` passed 139 selected
Python tests, both container/development lifecycle synthetic scripts, both
audit CLIs, Ruff format (93 files), and Ruff lint. Container-pytest cleanup and
fresh-checkout LF/per-file Bash parse contracts passed at
`2026-08-11T13:57:31Z`.

The exact required wrapper was then executed verbatim and returned exit `1`:
both `pwsh` and `uv` raised `CommandNotFoundException`. Because the wrapper
continued after the first missing command under Windows PowerShell semantics,
neither absence is hidden. No tool was downloaded. The locked equivalent tail
`.venv\Scripts\python.exe scripts/check_engineering_audit.py
docs/audits/ENGINEERING_AUDIT.md` returned exit 0; its prerequisite gates are
the fresh 728-test locked Linux run, static/type, Secret, license/dependency,
synthetic lifecycle, no-build real smoke, and offline security chain above.

### Remaining concerns

The formal Dockerfile current-source build still cannot be completed with the
available offline BuildKit cache; the derivative must not be promoted. Remote
GitHub/GitLab CI, Tencent Cloud/DNS/SSH/public TLS/cross-network/24h/
backup/rollback, current browser E2E, frontend type/build, ShellCheck, exact
`pwsh`/`uv` wrapper, and student manual acceptance remain outside the proven
local boundary unless a later section records a real run. No remote write or
push occurred.

### Review commit

The review implementation, tests, current security evidence, audit truth, and
process updates are committed as
`07cf82687df5fa4adba9448c1fbaf1a81871a29e` —
`fix: harden engineering audit evidence`. This exact hash is backfilled by a
documentation-only follow-up commit; neither commit was pushed.

## Review fix round 2/5

The rereview confirmed that the retained materials were internally valid but
that the completion CLI did not read them. The behavioral RED pointed both
material-directory environment variables at empty directories; the old CLI
still returned zero and claimed nine findings validated. The default CLI now
fails closed unless every retained app/gateway raw, package, inventory, VEX,
tar, release manifest, Trivy DB/metadata, and required local image is present
and exact. Only explicit `--schema-only` is portable and its output states that
retained materials were not validated.

Strict completion recomputes app raw counts (`181`, `169 High`, `12 Critical`,
`67` CVEs), the exact policy/package audit, inventory, 67-statement OpenVEX,
canonical finding tuple, app/gateway tar/config/scan release identity, Trivy DB
timestamp/hash, current source boundary, and four local daemon image IDs. Each
required input has a deletion mutation; malformed scan inventories, count,
tuple, DB timestamp, local image identity, manifest fields and current-source
drift fail closed. Focused verification passed 89 checker tests and the actual
strict CLI returned exit 0 with `10` findings.

The formal current-source Dockerfile build failure is now `ENG-010 Medium
BLOCKED` rather than prose-only context. Evidence E035 records the offline build
exit 1; E036 states the external cache precondition and prohibits promoting the
controlled derivative. Current disposition is 4 High FIXED, 2 Medium FIXED, 4
Medium BLOCKED, and 0 OPEN.

Fresh round-2 verification completed at `2026-08-11T17:11:57Z`: locked Linux
returned `748 passed, 1 skipped in 358.26s` (the skip is the deliberately
portable integration when the sibling retained DB is absent); the host strict
completion path validated the real retained materials and all four local image
IDs. Ruff format/check, `mypy src` for 46 source files, Functional `28/12/0`,
Engineering 10-findings completion, Secret synthetic and the 210-file real
scan all returned zero. Container-pytest and task-local temp cleanup were empty.

After the user explicitly requested GitHub publication, the authenticated
`Zzz148080/MuseEcho` remote received the already-reviewed Task 20, Task 21 and
Task 22 branches without force-push. Task 23 was kept local until all five fix
rounds passed independent rereview; it was then pushed without force and opened
as GitHub draft PR #1. No cloud deployment or other external system was
modified.

Round-2 implementation and evidence are committed as
`a240f64bcd57a34818356805b9a177086668752c` —
`fix: validate retained engineering evidence`; this hash is backfilled by a
documentation-only follow-up commit.

## Review fix round 3/5

The second rereview found one current-evidence drift after `ENG-010` was added:
Functional evidence E902 and its executable contract still asserted nine
findings and three Medium blockers, while Engineering strict completion
reported ten and four. A new cross-audit test derived the expected counts from
the parsed Engineering Audit and failed on the stale E902 result. E902 now runs
the explicit strict-material command and records `findings=10`,
`blocked-medium=4`; the report summary table matches. Functional and
Engineering and delivery-contract suites passed 134 tests, and both exact audit
CLI commands returned zero.

Round-3 implementation and current-evidence consistency are committed as
`93baab9f6f20d6e34dc393a837a6d6cb2a5fddaf` —
`fix: keep audit statistics consistent`.

## Review fix round 4/5

The final rereview correctly found that adding the cross-audit test changed the
acceptance-suite boundary from 36 to 37 tests while E014 still claimed 36.
The current evidence record and executable contract now say 37, and the
cross-audit assertion derives the OPEN count from Engineering findings instead
of hard-coding zero. The acceptance-only RED evidence was `37 passed` against
the stale record. After advancing the audit generation time to the new current
evidence boundary, the acceptance-only suite passed `37` tests; the combined
Functional, Engineering, and delivery-contract suite passed `134` tests.
Functional validation remained `28 PASS / 12 PARTIAL / 0 FAIL`, strict
Engineering completion revalidated all retained materials and `10` findings,
Ruff format/check passed, both the 210-file and synthetic Secret scans passed,
and `git diff --check` returned zero.

Round-4 implementation is committed as `f75c808` —
`fix: align current acceptance evidence`.

## Review fix round 5/5

The final read-only review found two remaining truth-boundary gaps. Engineering
E030 still contained the superseded 36-test result, while Functional E014
claimed an unavailable `uv run` command had exited zero. The earlier 9-finding
and `29/11` evidence was also presented under an unlabeled current-validation
heading. Three focused tests failed on those exact conditions before any
implementation change.

E014 and E030 now use the actual locked `.venv\Scripts\python.exe` PowerShell
command, including an explicit fail-fast check and the worktree-local pytest
basetemp. E030 is part of the Engineering fixed evidence contract, so later
command or result drift fails closed. The initial evidence sections are
explicitly labeled superseded, while the retained historical RED/GREEN facts
remain available. Adding the two cross-audit tests moved the acceptance file to
39 tests; the exact recorded command then produced `39 passed` and the
Functional CLI remained `28 PASS / 12 PARTIAL / 0 FAIL`.

The final round-5 focused suite passed `137` tests. Strict Engineering
completion re-read the retained materials and validated 10 findings; Ruff
format/check and acceptance-checker strict mypy passed. The 210-file real
Secret scan, synthetic Secret mutations, `git diff --check`, and task-local
temporary-directory cleanup all returned zero. A combined mypy invocation for
the dual package/direct-script Engineering entry point is not a project gate:
it discovers the same imported modules under two names, so no success is
claimed for that unsupported command.

Independent final merge review returned 0 Critical, 0 Important, and 0 Minor.
The branch was published as `origin/audit/23-engineering`, and draft PR #1 is
`https://github.com/Zzz148080/MuseEcho/pull/1` against `main`.

## Merged-result verification fix

The first local `--no-ff` merge reproduced seven audit-only failures on the
main checkout even though the merged tracked tree was byte-identical to the
reviewed branch. Root-cause tracing found pre-existing generated
`src/museecho.egg-info` in the main checkout. The Docker context already
excluded every `**/*.egg-info`, and the committed policy intentionally bound a
clean source tree, but `build_runtime_boundary_manifest()` excluded only
`__pycache__` and bytecode. A dirty checkout could therefore change the audit
boundary even though those files can never enter the release image.

A focused RED created a temporary dirty source tree and observed
`src/museecho.egg-info/PKG-INFO` in the manifest. The minimal fix ignores any
path component ending in `.egg-info`, matching `.dockerignore`; the dirty and
clean boundary tests then passed. The focused security/audit set passed 168
tests, and the final locked Linux suite passed `753 passed, 1 skipped in
352.52s`. The behavior fix is commit
`acb2cb09e7c62e104ef64331f105514d6ce3016a` —
`fix: ignore generated runtime metadata`.

## Cross-checkout line-ending verification fix

The second merged-result verification retained the generated metadata and
found a separate checkout portability defect: `core.autocrlf=true` had written
the two Task 23 Python files as CRLF on `main`, while the reviewed worktree
contained LF. The Functional Audit current-boundary digest hashed raw working
tree bytes, so identical Git content failed only because of legal checkout
line endings. A focused RED reproduced distinct digests for the same text with
LF and CRLF. The digest now canonicalizes CRLF to LF only for text-like content
(no NUL byte), while a binary regression contract proves binary bytes remain
exact. E004 was refreshed to the canonical current-boundary digest. The full
acceptance test file passed 41 tests and the Functional CLI then passed with
28 PASS / 12 PARTIAL / 0 FAIL. A session-collection assertion now binds E014
and E030 to the actual complete-file count so later test additions fail closed.

## GitHub Linux quality fix

Draft PR #1 supplied the first remote CI run and failed in `quality`: Linux
mypy reported four `attr-defined` errors for Windows-only `ctypes.WinDLL` and
`subprocess.CREATE_NEW_PROCESS_GROUP`. The exact failure was reproduced with
`mypy --platform linux` before implementation. The minimal production change
uses runtime-guarded `getattr` access (and an integer cast for the creation
flag), preserving the existing Windows process-tree behavior while making
both Linux and Windows mypy pass. Because production source changed, the
non-release audit derivative and retained app tar/raw/package/inventory/VEX/
release identity were regenerated with the fixed offline Trivy DB. Raw stayed
181 occurrences / 67 CVEs, exact audit and VEX residual passed, gateway stayed
zero, and trusted no-build smoke passed the refreshed app identity. The locked
Linux current-source suite then passed `755 passed, 1 skipped in 360.54s` with
empty cleanup. The branch must be pushed again before remote CI can establish
the remote GREEN result.

## Remote evidence truth review

The next independent review found three evidence-truth defects rather than a
new product failure: E010/E012 still described the pre-fix default mypy run,
GitHub Actions was still called NOT_RUN after run `31523692229` had failed,
and E902 was timestamped before the regenerated final retained materials.
Focused RED demonstrated that adding the truthful GitHub failure record was
rejected by both validators: Engineering hard-coded the range through E036,
and Functional required every external blocker evidence row to be NOT_RUN.

The validators now bind E037/E906 as fixed executed negative evidence that
cannot support PASS. External blockers may cite that evidence only when its
fixed contract explicitly sets `supports_pass=False`; an arbitrary successful
command remains rejected. The current audit commands record both Windows-host
and explicit Linux mypy success for 46 source files, strict retained-material
completion after regeneration, and the actual GitHub failure while preserving
GitLab as NOT_RUN. The focused audit/security suite passed 162 tests and both
strict CLIs returned zero. A new pushed GitHub run remains required.
