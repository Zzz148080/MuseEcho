# MuseEcho V1 工程审计

- **生成时间（UTC）：** `2026-08-17T06:17:36Z`
- **范围：** 基于 `2b612947e5b06ee060e9341409e8056bf1129cc0` 的任务 23 工程风险，包括当前工作源代码修复与保留的任务 20 安全材料。
- **方法：** 仅在复现后记录发现项。已修复发现项同时保留失败和通过证据。默认完成校验器针对不可变任务 23 策略快照读取并重算保留的 raw/package/VEX/inventory/tar/release/DB/image 材料；`--schema-only` 明确不表示完成。最终产品/CI 实现 SHA `0674f74f4097e46cee98c4715a62ad5aa55101cf` 在 run `31966788273` 中通过 GitHub quality、浏览器 E2E 和 distribution；合并后的 main SHA `d99e7b95f83f0f5cd6867bd10bacc274e6d2a0e1` 通过 run `31997390847`，正式 GitHub `v0.1.0` 离线运行 Release 已发布并完成回下载验证。这些后续事实不改写保留的任务 23 证据。GitLab 保持补充性质且未运行；公网/云端和不可用的 current-source 离线构建门也保持未运行。
- **安全边界：** 正式 Dockerfile 重建在 `--network none` 下因 BuildKit 依赖层不可用而 fail-closed。因此，任务 23 安全证据使用明确标为非发行的审计镜像：它派生自精确任务 20 app runtime，移除陈旧 egg 元数据并覆盖任务 23 源代码。跟踪的 compact manifest 绑定保留的 Trivy DB、精确 tar/config ID、raw tuple digest、inventory、VEX、门禁退出值和 `docs/audits/evidence/task23-image-vulnerability-policy.json`。独立维护的 `scripts/image-vulnerability-policy.json` 为 distribution 门绑定当前 checkout；更新它不会重新标记或扫描保留的任务 23 镜像材料。

## 领域覆盖

| 领域 | Evidence ID | 结论 |
| --- | --- | --- |
| architecture-boundaries | E012, E029 | Layer 边界和 port 保持静态干净；聚焦 runtime/security 回归通过。 |
| types-static | E012 | 当前 Python 源代码通过 Ruff format/lint 和严格 mypy。 |
| dependencies-licenses | E018, E032 | 已复审许可证策略和三份锁定依赖 manifest 均通过离线验证。 |
| runtime-image-vulnerabilities | E020, E021, E022, E023, E024, E025 | 功能前任务 23 app 镜像 raw 181/67 逐 CVE 复审后 residual 为零；gateway raw 和门均为零。该保留镜像证据不是当前分支 runtime 扫描。 |
| performance-resources | E019, E031 | 锁定 Linux 五分钟 workload 在 51.24 秒内通过；no-build Smoke 未残留容器、卷、网络或临时目录。 |
| concurrency-async-subprocesses | E011, E029 | 队列锁定/失败指标和受限 runtime/subprocess 边界通过聚焦回归。 |
| access-control-csrf-cors | E029 | Token、origin、CSRF、same-origin 和 runtime 边界回归通过。 |
| upload-parsing | E029 | 上传校验、限制、解析隔离和 repository invariant 通过。 |
| secrets-logging-errors | E016, E017, E029 | 真实和合成 Secret 扫描通过；安全错误与请求 logging 边界有测试。 |
| data-lifecycle-backup | E019, E029 | 清理、过期、重启持久化、加密卷行为和幂等恢复通过；不声称具有 HA。 |
| observability | E011 | Request ID、结构化安全日志、liveness/readiness、queue/stage/cleanup/fallback 计数器和 duration 指标通过。 |
| test-isolation | E013, E019, E029 | 最终锁定 Linux 套件、聚焦风险套件和真实 no-build 生命周期通过并精确清理。 |
| accessibility | E014, E037 | 新鲜 12 文件/78 测试 UI 套件通过 label、landmark、keyboard、status、privacy、精确上传后缀和 workflow 行为；真实浏览器执行在上一个产品/CI 实现边界通过。 |
| reproducible-build-ci-release-identity | E003, E005, E009, E025, E034 | 逐文件 shell 解析、非空 identity 比较、显式 no-build identity、干净 Docker context、精确 tar/scan identity 和 policy drift 测试通过。 |
| operations-recovery | E007, E019, E030 | Development cleanup 同时保留主失败与清理失败；production no-build 重启/清理和功能 checker 通过。 |

## 证据索引

| ID | 类型 | 命令 | 路径 | 结果 | 观察时间（UTC） | 退出码 |
| --- | --- | --- | --- | --- | --- | --- |
| E001 | RED_COMMAND | uv run pytest tests/unit/test_engineering_audit.py -q | tests/unit/test_engineering_audit.py | `ModuleNotFoundError: scripts.check_engineering_audit` | 2026-08-11T10:40:00Z | 1 |
| E002 | RED_COMMAND | powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/deploy/test_shell_line_endings.ps1 with invalid syntax in the last fresh-checkout file | tests/deploy/test_shell_line_endings.ps1 | 旧多文件 `bash -n` 调用接受了无效的最后一个文件 | 2026-08-11T10:44:00Z | 1 |
| E004 | RED_COMMAND | python scripts/verify_release_identity.py verify --manifest manifest-only.json | tests/unit/test_release_identity.py | 仅 manifest 的 verify 在没有任何比较类别时返回成功 | 2026-08-11T10:47:00Z | 1 |
| E006 | RED_COMMAND | powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-development-smoke.ps1 against the old smoke | scripts/test-development-smoke.ps1 | Compose 部分启动会跳过 down，且清理失败可能替换或隐藏主失败 | 2026-08-11T10:50:00Z | 1 |
| E010 | RED_COMMAND | .venv/Scripts/python.exe -m pytest tests/unit/test_observability.py -q | tests/unit/test_observability.py | `ModuleNotFoundError: museecho.observability` | 2026-08-11T10:57:00Z | 1 |
| E005 | CURRENT_COMMAND | .venv/Scripts/python.exe -m pytest tests/unit/test_release_identity.py -q | tests/unit/test_release_identity.py | 10 个测试通过；verify 拒绝空比较 inventory，同时 tar + scan 和可选 image-id 保持有效 | 2026-08-11T11:09:30Z | 0 |
| E033 | RED_COMMAND | .venv/Scripts/python.exe -m pytest tests/unit/test_task20_final_delivery_contract.py::test_docker_context_excludes_generated_python_package_metadata -q | tests/unit/test_task20_final_delivery_contract.py | 1 个测试失败，因为 `.dockerignore` 未排除被 Git 忽略的 egg-info 元数据 | 2026-08-11T11:39:00Z | 1 |
| E035 | RED_COMMAND | docker build --pull=false --network none --tag museecho-app:task23-formal-offline . | Dockerfile | 正式 current-source Dockerfile 构建以 exit 1 结束，因为网络禁用时锁定 pip/apt BuildKit layer 不可用 | 2026-08-11T11:40:10Z | 1 |
| E036 | EXTERNAL_NOT_RUN | NOT RUN: formal current-source Dockerfile build requires the complete locked BuildKit pip and apt cache under network none | Dockerfile | 保留的任务 23 派生物仅供审计，不是 Release 产物 | 2026-08-11T11:40:11Z | NOT_RUN |
| E034 | CURRENT_COMMAND | .venv/Scripts/python.exe -m pytest tests/unit/test_task20_final_delivery_contract.py::test_docker_context_excludes_generated_python_package_metadata tests/unit/test_image_vulnerability_audit.py::test_committed_policy_matches_clean_runtime_boundary_without_generated_metadata tests/unit/test_image_vulnerability_audit.py::test_audit_rejects_schema_probe_or_complete_runtime_boundary_drift -q | tests/unit/test_image_vulnerability_audit.py | 干净 Docker context 合同通过，6 个 policy/runtime drift mutation 通过；派生镜像不含 egg-info | 2026-08-11T11:45:10Z | 0 |
| E015 | EXTERNAL_NOT_RUN | NOT RUN: local Task 23 review lacked the locked Node/Playwright cache before the remote run | .superpowers/sdd/PLAN/task-22-report.md | 保留历史 NOT_RUN；产品实现覆盖已由 E037 取代 | 2026-08-11T11:56:55Z | NOT_RUN |
| E026 | EXTERNAL_NOT_RUN | NOT RUN: local current Chrome E2E lacked the locked Playwright cache before remote CI | e2e | 保留历史本地 NOT_RUN；产品实现覆盖已由 E037 取代 | 2026-08-11T12:01:00Z | NOT_RUN |
| E028 | EXTERNAL_NOT_RUN | NOT RUN: Tencent Cloud, DNS, SSH, public TLS, cross-network, 24-hour observation, backup/restore, and live rollback require external target authorization | DEPLOYMENT_EVIDENCE.md | 不声称已有公网 URL、目标服务器基准或远端运维证据 | 2026-08-11T12:01:10Z | NOT_RUN |
| E031 | CURRENT_COMMAND | docker run --rm --network none --read-only with current app and pytest deps -m pytest tests/performance/test_five_minute_budget.py -q | tests/performance/test_five_minute_budget.py | 在锁定且支持 ffmpeg 的 Linux runtime 中，1 个测试于 51.24 秒内通过 | 2026-08-11T12:06:30Z | 0 |
| E029 | CURRENT_COMMAND | .venv/Scripts/python.exe -m pytest tests/unit/test_runtime_security_boundaries.py tests/unit/test_access_service.py tests/api/test_upload.py tests/integration/test_repository.py tests/integration/test_cleanup.py tests/unit/test_queue.py -q | tests/unit/test_runtime_security_boundaries.py | access、upload、queue、repository、lifecycle 和 security 边界共 82 个测试通过，1 个有意跳过 | 2026-08-11T12:07:35Z | 0 |
| E008 | RED_COMMAND | powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-container-contract.ps1 against the old smoke | scripts/test-container-contract.ps1 | 缺少显式 no-build 路径、受信镜像 identity 校验、runtime identity 检查和重复 `up --no-build` | 2026-08-11T12:45:00Z | 1 |
| E009 | CURRENT_COMMAND | powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-container-contract.ps1 | scripts/test-container-contract.ps1 | 合成合同拒绝错误、重复、交换及 runtime-drifted 镜像 identity，并要求两次启动都使用 `--no-build` | 2026-08-11T13:02:00Z | 0 |
| E011 | CURRENT_COMMAND | .venv/Scripts/python.exe -m pytest tests/unit/test_observability.py tests/api/test_health.py tests/integration/test_runtime_app.py -q | tests/unit/test_observability.py | 安全请求和后台失败日志、稳定 500 响应、指标、liveness/readiness、清理降级与恢复均通过 | 2026-08-11T13:03:00Z | 0 |
| E007 | CURRENT_COMMAND | powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-development-smoke.ps1 | scripts/test-development-smoke.ps1 | 合成 partial-start、仅主失败、仅清理失败和组合失败报告均通过 | 2026-08-11T13:04:00Z | 0 |
| E021 | CURRENT_COMMAND | docker run --rm --network none --tmpfs /root/.cache/trivy:rw,nosuid,nodev,size=512m --mount type=bind,source=TASK20_TRIVY_DB,target=/root/.cache/trivy/db,readonly --mount type=bind,source=TASK23_EVIDENCE,target=/evidence aquasec/trivy:0.70.0 image --input /evidence/museecho-gateway-task20.tar --scanners vuln --severity HIGH,CRITICAL --format json --output /evidence/gateway-raw-review1.json --skip-db-update --skip-java-db-update --skip-version-check --offline-scan | docs/audits/evidence/task23-security-manifest.json | Gateway raw occurrences=0、distinct-cves=0；精确 config 和 raw SHA 已固定 | 2026-08-11T13:12:55Z | 0 |
| E016 | CURRENT_COMMAND | powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/secret-scan.ps1 | scripts/secret-scan.ps1 | 210 个已跟踪和未忽略文件通过 | 2026-08-11T13:52:11Z | 0 |
| E017 | CURRENT_COMMAND | powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-secret-scan.ps1 | scripts/test-secret-scan.ps1 | 合成凭据、不可读文件和缺失文件 mutation 通过 | 2026-08-11T13:52:11Z | 0 |
| E018 | CURRENT_COMMAND | .venv/Scripts/python.exe scripts/license_audit.py | scripts/license_audit.py | Python、npm、容器、构建工具、Go module 和 OS package inventory 与策略一致 | 2026-08-11T13:52:11Z | 0 |
| E032 | CURRENT_COMMAND | .venv/Scripts/python.exe scripts/license_audit.py; parse pyproject.toml package-lock.json frontend/package-lock.json offline | scripts/license_audit.py | License policy 通过；离线解析 Python 14 项依赖、根目录 8 个 lock package 和 frontend 218 个 lock package | 2026-08-11T13:52:20Z | 0 |
| E003 | CURRENT_COMMAND | powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/deploy/test_shell_line_endings.ps1 | tests/deploy/test_shell_line_endings.ps1 | LF 检查通过，`bash -n` 独立解析 8 个 fresh-checkout 文件 | 2026-08-11T13:57:31Z | 0 |
| E020 | CURRENT_COMMAND | docker run --rm --network none --tmpfs /root/.cache/trivy:rw,nosuid,nodev,size=512m --mount type=bind,source=TASK20_TRIVY_DB,target=/root/.cache/trivy/db,readonly --mount type=bind,source=TASK23_EVIDENCE,target=/evidence aquasec/trivy:0.70.0 image --input /evidence/museecho-app-task23-review1.tar --scanners vuln --severity HIGH,CRITICAL --format json --output /evidence/app-raw-review1.json --skip-db-update --skip-java-db-update --skip-version-check --offline-scan | docs/audits/evidence/task23-security-manifest.json | Trivy 0.70.0 与固定 DB 发现 app occurrences=181、distinct-cves=67、critical=12、high=169；raw SHA 与 tuple SHA 已固定 | 2026-08-11T19:07:10Z | 0 |
| E022 | IMPLEMENTATION_BOUNDARY_COMMAND | docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --workdir /workspace --mount type=bind,source=REPOSITORY,target=/workspace,readonly --mount type=bind,source=TASK23_EVIDENCE,target=/evidence --entrypoint /app/.venv/bin/python museecho-app:task23-review1 /workspace/scripts/image_vulnerability_audit.py --scan /evidence/app-raw-review1.json --package-files /evidence/app-package-files-review1.json --policy /workspace/scripts/image-vulnerability-policy.json --release-identity /evidence/release-images-review1.json --image-name app --vex-output /evidence/app-openvex-review1.json --inventory-output /evidence/app-inventory-review1.json | docs/audits/evidence/task23-security-manifest.json | 功能前任务 23 镜像 raw tuple、package ownership、67 条已复审 statement 和 release identity 通过；当前源代码 policy 单独绑定，本记录不是当前 runtime-image 扫描 | 2026-08-11T19:08:00Z | 0 |
| E025 | CURRENT_COMMAND | python scripts/verify_release_identity.py verify --manifest tmp/task23-engineering/release-images-review1.json --tar app=tmp/task23-engineering/museecho-app-task23-review1.tar --tar gateway=tmp/task23-engineering/museecho-gateway-task20.tar --scan app=tmp/task23-engineering/app-raw-review1.json --scan gateway=tmp/task23-engineering/gateway-raw-review1.json | docs/audits/evidence/task23-security-manifest.json | App/gateway config ID、tar SHA256 和 raw scan ImageID 一致 | 2026-08-11T19:08:20Z | 0 |
| E023 | CURRENT_COMMAND | docker run --rm --network none --tmpfs /root/.cache/trivy:rw,nosuid,nodev,size=512m --mount type=bind,source=TASK20_TRIVY_DB,target=/root/.cache/trivy/db,readonly --mount type=bind,source=TASK23_EVIDENCE,target=/evidence aquasec/trivy:0.70.0 image --input /evidence/museecho-app-task23-review1.tar --scanners vuln --severity HIGH,CRITICAL --exit-code 1 --vex /evidence/app-openvex-review1.json --skip-db-update --skip-java-db-update --skip-version-check --offline-scan | docs/audits/evidence/task23-security-manifest.json | App VEX 门 residual High/Critical=0 | 2026-08-11T19:11:58Z | 0 |
| E024 | CURRENT_COMMAND | docker run --rm --network none --tmpfs /root/.cache/trivy:rw,nosuid,nodev,size=512m --mount type=bind,source=TASK20_TRIVY_DB,target=/root/.cache/trivy/db,readonly --mount type=bind,source=TASK23_EVIDENCE,target=/evidence aquasec/trivy:0.70.0 image --input /evidence/museecho-gateway-task20.tar --scanners vuln --severity HIGH,CRITICAL --exit-code 1 --skip-db-update --skip-java-db-update --skip-version-check --offline-scan | docs/audits/evidence/task23-security-manifest.json | 未 suppression 的 gateway 门 High/Critical=0 | 2026-08-11T19:12:21Z | 0 |
| E019 | CURRENT_COMMAND | powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/container-smoke.ps1 -NoBuild -ReleaseManifest docs/audits/evidence/task23-security-manifest.json -ExpectedAppDaemonImageId sha256:b0231299644d58f7845e3c137faeca6f0f8cc7df2f3dbbcb656c75060128a724 -ExpectedAppConfigImageId sha256:89c7b7ad0a9d1708ce0cf277389c1fca7e13e05bb3937b602a6e2533cf9729ac -ExpectedGatewayDaemonImageId sha256:2235e208dd7d8568c735ba19f1969644384626296eaff5cabb41acfaed86c547 -ExpectedGatewayConfigImageId sha256:8cc0429e45fd48c911a92fd8504c1f3c14daccb0fee8a24529d72af51b0b4053 | scripts/container-smoke.ps1 | 受信 app/gateway daemon/config identity、两个 runtime 容器 identity、真实 WAV、重启、密文、历史和清理均在无构建条件下通过 | 2026-08-11T19:15:30Z | 0 |
| E027 | EXTERNAL_NOT_RUN | NOT RUN: GitLab CI has no pipeline result for the Task 23 implementation boundary | .gitlab-ci.yml | GitHub 实现边界作业如 E037 所示为绿色；GitLab 仍未运行 | 2026-08-12T19:11:39Z | NOT_RUN |
| E037 | IMPLEMENTATION_BOUNDARY_COMMAND | gh run view 31630284744 --repo Zzz148080/MuseEcho --json conclusion,jobs,url,headSha | .github/workflows/ci.yml | 上一个产品/CI 实现边界 `2b2730e` 的 run `31630284744` 以 quality、e2e 和 distribution success 完成；它不是分支顶端证据 | 2026-08-12T19:11:39Z | 0 |
| E014 | CURRENT_COMMAND | npm.cmd --prefix frontend test -- --run | frontend/src | 当前 frontend 的 12 个测试文件和 78 个测试通过 | 2026-08-13T23:53:53Z | 0 |
| E012 | CURRENT_COMMAND | .venv/Scripts/python.exe -m ruff format --check src tests scripts; .venv/Scripts/python.exe -m ruff check .; .venv/Scripts/python.exe -m mypy src; .venv/Scripts/python.exe -m mypy --platform linux src | scripts/check_engineering_audit.py | 96 个文件格式正确；lint 通过；Windows 宿主和显式 Linux 严格 mypy 各通过 47 个源文件 | 2026-08-14T02:28:00Z | 0 |
| E013 | IMPLEMENTATION_BOUNDARY_COMMAND | powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/container-pytest.ps1 -Image museecho-task3-verification-env:latest; .venv\Scripts\python.exe -m pytest tests/unit/test_task20_final_delivery_contract.py -q | tests | 历史实现边界在锁定 Linux 验证 runtime 中 841 个测试通过、7 个跳过，包括 100 MiB 上传限制回归；PowerShell 宿主上 20 个测试通过，包括 4 个仅 PowerShell harness；本证据早于 `7f8412b`，不能证明其播放/节奏变更或最终分支顶端；容器和 task-temp 清理完成 | 2026-08-14T09:00:00Z | 0 |
| E030 | CURRENT_COMMAND | .venv\Scripts\python.exe -m pytest tests/unit/test_acceptance_matrix.py -q --basetemp tmp/task23-e014 -p no:cacheprovider; if ($LASTEXITCODE) { exit $LASTEXITCODE }; .venv\Scripts\python.exe scripts/check_acceptance_matrix.py SPEC.md docs/audits/FUNCTIONAL_AUDIT.md | docs/audits/FUNCTIONAL_AUDIT.md | 48 个测试通过；验证 40 个条目：PASS=36、PARTIAL=4、FAIL=0 | 2026-08-16T19:37:07Z | 0 |
| E038 | IMPLEMENTATION_BOUNDARY_COMMAND | gh run view 31966788273 --repo Zzz148080/MuseEcho --json status,conclusion,headBranch,headSha,jobs,url | .github/workflows/ci.yml | `codex/expand-common-audio-formats` 上最终产品/CI 实现 SHA `0674f74f4097e46cee98c4715a62ad5aa55101cf` 在 run `31966788273` 中通过 quality（5m43s）、e2e（3m10s）和 distribution（7m30s） | 2026-08-16T19:37:07Z | 0 |

## 第一轮复审 RED/GREEN 记录

- 校验器/证据隔离：40 个定向 mutation 在精确逐发现项 E002-E011/E019/E033-E034 合同、
  完整 E020-E025 合同、compact-manifest mutation 和真实任务 23 捕获时 runtime builder 达到 43/43 前失败。
- 受信 no-build identity：旧 Smoke 在一个合成合同上失败；修复后的合同拒绝错误、重复、交换和
  运行中容器 drift，并证明两次启动均使用 `--no-build`。
- Observability 与队列真实性：5 个新断言先失败，随后恶意入站 request ID 被忽略、未处理 500
  响应变得稳定安全、后台失败事件只携带 task/stage/code，queue depth 只计算等待工作；聚焦套件最终 17/17 通过。
- Development 仅清理失败语义：可注入健康检查暴露仅清理失败前，一个生命周期合同先失败；
  仅主失败、仅清理失败、组合失败和 partial-start 模式随后通过。
- 功能真实性：frontend type/build 仍为当前 PASS 且复用任务 22 命令/计数时，两个断言失败；
  当前矩阵现以门禁 NOT_RUN 验证 `28 PASS / 12 PARTIAL / 0 FAIL`。
- 直接 Linux CLI：一次仓库外调用以 `ModuleNotFoundError: scripts` 失败；在不改变 checker 策略的情况下，
  package 与直接脚本 import 现均通过。
- 跨文档统计：在其他 727 个测试通过后，锁定 Linux 暴露陈旧 `(29,11,0)` 交付合同；
  修复后的过程合同与全部当前文档统一为 `(28,12,0)`。

## 发现项

| ID | 领域 | 严重级别 | 状态 | 描述 | Evidence ID | 负责人 | 处置 | 复审条件 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ENG-001 | reproducible-build-ci-release-identity | High | FIXED | 任务 21 harness 将多个 Bash 文件传给同一个 `bash -n` 进程；该进程只解析第一个文件，可能遗漏后续无效部署脚本。 | E002, E003 | 任务 23 工程 | FIXED：对每个已跟踪和 fresh-checkout shell 文件独立调用 `bash -n`。 | 若 shell inventory 或解析 harness 不再保持逐文件单进程，则重新打开。 |
| ENG-002 | reproducible-build-ci-release-identity | High | FIXED | Release identity verify 在省略全部比较类别时仍接受 manifest，产生空洞成功。 | E004, E005 | 任务 23 工程 | FIXED：至少要求一份完整 image-id、tar 或 scan 比较 inventory，同时保留 tar + scan CI 语义和可选 image-id。 | 若仅 manifest 验证返回零，或接受不完整 inventory，则重新打开。 |
| ENG-003 | operations-recovery | High | FIXED | Development Smoke 未可靠清理部分启动，且可能隐藏主启动错误或 `compose down` 错误。 | E006, E007 | 任务 23 工程 | FIXED：启动前标记必须清理，始终尝试 down，保留主错误，并同时报告清理错误。 | 若 Compose 部分启动可跳过 down，或任一失败从输出消失，则重新打开。 |
| ENG-004 | reproducible-build-ci-release-identity | Medium | FIXED | Production Smoke 无条件构建镜像，其首次 no-build 修复未绑定受信逐服务 daemon/config identity，也未在两次启动后重新检查运行中容器。 | E008, E009, E019 | 任务 23 工程 | FIXED：要求受信 manifest 和互异的精确 app/gateway daemon/config ID，验证 Compose tag 与两个运行中容器，并在每次启动使用 `compose up --no-build`，不改变默认构建语义。 | 若 no-build 调用 `compose build`、接受错误/交换/共享 identity、遗漏运行中容器检查或未带 `--no-build` 启动，则重新打开。 |
| ENG-005 | observability | Medium | FIXED | Production 缺少安全请求/失败 observability；首次修复仍在未处理 500 响应中遗漏 request ID、在后台失败中丢失 task/stage/code，并将 active work 报为 queued。 | E010, E011 | 任务 23 工程 | FIXED：使用安全 ASGI 响应边界，忽略入站 ID，发出稳定 500 JSON 和生成的 request ID，失败时只记录 task/stage/error code，并分离 waiting 与 active 指标。 | 若日志包含上传内容、header、问题、token、异常文本或文件名，或仅 active work 增加 queue depth，则重新打开。 |
| ENG-006 | accessibility | Medium | VERIFIED | 本地 frontend/browser 执行最初受阻，但实现边界 GitHub quality 与真实 HTTPS 浏览器 E2E 通过。 | E015, E026, E037 | 任务 23 工程 | VERIFIED：保留本地 NOT_RUN 历史，并将产品/浏览器闭环绑定到上一个产品/CI 实现边界和成功 quality/E2E 作业；不声称存在产品缺陷或伪造 RED。 | 若实现边界 frontend build 或浏览器 E2E 失败，则重新打开。 |
| ENG-007 | reproducible-build-ci-release-identity | Medium | BLOCKED | GitHub Actions 在最终产品/CI 实现 SHA `0674f74f4097e46cee98c4715a62ad5aa55101cf` 上为绿色；GitLab CI 作为补充性后续配置仍未运行。 | E027, E038 | 仓库负责人 | EXTERNAL：保留 run `31966788273` 作为必需 GitHub 结果；仅在启用补充 mirror 时运行 GitLab 并保留日志/artifact，不把 GitLab 当作课程门禁。 | 若启用补充 GitLab pipeline 则复审；此处不声称 GitLab 已执行。 |
| ENG-008 | operations-recovery | Medium | BLOCKED | 目标云端、公网 TLS、跨网、24 小时观察、备份/恢复和真实回滚证据需要外部基础设施授权。 | E028 | 部署负责人 | EXTERNAL：在获授权目标上执行已记录的部署与恢复门，不伪造本地替代证据。 | 提供腾讯云、DNS、SSH、公网测试和回滚授权后复审。 |
| ENG-009 | reproducible-build-ci-release-identity | High | FIXED | Docker context 可能复制被 Git 忽略的 `museecho.egg-info` 文件，任务 20 policy/image 绑定了 6 个干净 checkout 中不存在的 dirty-worktree 产物。 | E033, E034, E022 | 任务 23 工程 | 任务 23 中 FIXED：排除全部 egg-info 目录，从受控审计层移除陈旧元数据，并将捕获时 policy snapshot 绑定到完整干净 runtime manifest，不改变 CVE statement；当前 distribution policy 独立维护。 | 若 clean-context probe 发现 egg-info、当前 policy 与完整当前 runtime manifest 不同，或 source 变更引入 decoder、FFmpeg、动态 SQL、subprocess 或外部执行路径却未重审 CVE，则重新打开。 |
| ENG-010 | reproducible-build-ci-release-identity | Medium | BLOCKED | 使用保留的离线 BuildKit cache 无法重建正式 current-source Dockerfile，因此保留的任务 23 派生物仅供审计，不能证明 Release 产物。 | E035, E036 | 构建环境负责人 | EXTERNAL：恢复完整锁定 pip/apt BuildKit cache，再在网络禁用条件下正式重建 Dockerfile；绝不提升该派生物。 | 正式 Dockerfile 离线构建返回零，且所得 release identity 与安全链通过后复审。 |

## 处置摘要

- Critical：0。
- High：4 FIXED、0 OPEN、0 ACCEPTED、0 BLOCKED。
- Medium：2 FIXED、1 VERIFIED、0 OPEN、0 ACCEPTED、3 BLOCKED。
- Low：0。

三项 Medium 阻塞项是证据/环境缺口，不是产品 Critical/High 缺陷。正式 Dockerfile 构建边界现为显式发现项，而非仅存在于说明文字：缺少完整锁定 cache 时无法重新构建，保留的任务 23 派生物明确为非发行且不得提升。没有漏洞被移除、降级或隐藏：raw app tuple 仍为 181 occurrences / 67 CVE，只有未经更改且逐 CVE 复审的 OpenVEX statement 将门禁降至零。
