# 100 MB 音频上传限制实施计划

> **供自主执行者使用：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐项实施本计划。步骤使用复选框（`- [ ]`）语法跟踪。

**目标：** 接受并分析最大 100 MiB 的音频文件，同时不削弱流式处理、时长、清理或服务端强制限制。

**架构：** 将权威 Python 文件上限提高到 100 MiB，并继续将请求上限派生为文件字节数加 64 KiB multipart 开销。浏览器预检和面向用户的文档采用完全相同的边界，同时保持 600 秒解码限制和 PCM 内存限制不变。

**技术栈：** Python 3.12、FastAPI/Starlette、pytest、React 19、TypeScript、Vitest。

## 全局约束

- 接受恰好 `100 * 1024 * 1024` 个文件字节，并拒绝超出的第一个字节。
- 保留 `DEFAULT_REQUEST_OVERHEAD_BYTES = 64 * 1024`，并从文件上限派生请求体上限。
- 解码时长上限保持 600 秒。
- 不改动支持的格式、FFmpeg 白名单、加密保留机制或结果呈现。
- 不增加 Caddy 请求体上限或新的运行时依赖。

---

### 任务 1：服务端文件与请求边界

**文件：**
- 修改：`tests/api/test_upload.py`
- 修改：`src/museecho/application/uploads.py`

**接口：**
- 输入：`UploadSubmissionService.submit(source, filename, media_type)` 和已安装的默认 `UploadBodyLimitMiddleware`。
- 输出：`DEFAULT_MAX_UPLOAD_BYTES == 100 * 1024 * 1024`；`DEFAULT_MAX_UPLOAD_REQUEST_BYTES == DEFAULT_MAX_UPLOAD_BYTES + 64 * 1024` 仍在 `museecho.api.analyses` 中派生。

- [ ] **步骤 1：增加一个失败的服务回归测试**

通过默认 `UploadSubmissionService` 提交一个生成的、以 WAV 命名且大小为 `30 * 1024 * 1024 + 1` 字节的流，使用现有有效探测器和记录协作者，并断言产生一个任务、一次加密存储写入和一个入队分析。该测试通过可观察的提交行为防止回退到旧的 30 MiB 上限。

- [ ] **步骤 2：增加一个失败的默认中间件边界测试**

在不显式覆盖配置的情况下运行真实 `UploadBodyLimitMiddleware`。发送一个分析上传 ASGI scope，其 `Content-Length` 为 `100 * 1024 * 1024 + 64 * 1024`；断言下游应用被调用。再增加一个字节重复执行，并断言响应状态为 413，且不调用下游。

- [ ] **步骤 3：确认 RED**

运行：

```powershell
.venv\Scripts\python.exe -m pytest tests/api/test_upload.py -q --basetemp=tmp/100mb-red
```

预期：新服务测试在旧的 30 MiB 边界引发 `UploadTooLargeError`，新的默认中间件测试对当前应有效的 100 MiB 加开销请求返回 413。

- [ ] **步骤 4：实施最小服务端变更**

只修改 `src/museecho/application/uploads.py` 中的权威值：

```python
DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024
```

保持 `DEFAULT_MAX_UPLOAD_REQUEST_BYTES` 从它派生，并保持两个构造函数在超过其受支持上限时都以失败关闭。

- [ ] **步骤 5：确认 GREEN**

运行：

```powershell
.venv\Scripts\python.exe -m pytest tests/api/test_upload.py -q --basetemp=tmp/100mb-server-green
```

预期：所有上传 API 测试均通过，包括早期 `Content-Length` 拒绝和分块请求强制限制。

---

### 任务 2：浏览器与当前产品契约

**文件：**
- 修改：`frontend/src/features/upload/UploadForm.test.tsx`
- 修改：`frontend/src/features/upload/UploadForm.tsx`
- 修改：`README.md`
- 修改：`SPEC.md`
- 审计检查器要求时修改：`docs/audits/FUNCTIONAL_AUDIT.md`

**接口：**
- 输入：浏览器 `File.size`、`validateFile(file)` 和 `uploadErrorPresentation(reason)`。
- 输出：浏览器预检和所有当前产品指引统一公开 100 MB 限制。

- [ ] **步骤 1：用失败的边界行为替换旧前端大小测试**

使用覆盖了 `size` 属性的轻量 `File` 对象，避免实际分配 100 MiB。断言恰好 `100 * 1024 * 1024` 不返回验证错误，而 `100 * 1024 * 1024 + 1` 会在任何上传传输调用前渲染包含 `不能超过 100 MB` 的警告。

- [ ] **步骤 2：确认前端为 RED**

运行：

```powershell
npm.cmd --prefix frontend test -- --run src/features/upload/UploadForm.test.tsx
```

预期：恰好 100 MiB 的用例被拒绝，错误消息仍显示 30 MB。

- [ ] **步骤 3：对齐浏览器与文档**

将 `MAX_UPLOAD_BYTES` 设为 `100 * 1024 * 1024`；把帮助文本、本地验证消息和 `upload_too_large` 呈现改为 100 MB。将 `README.md` 中的当前限制及 `SPEC.md` 中所有当前需求/风险条目从 30 MB/MiB 改为 100 MB/MiB。较早的 Superpowers 设计/计划文档记录了当时获批的边界，应保持不变；本计划及其设计取代它们。

- [ ] **步骤 4：确认前端为 GREEN 并检查静态类型**

运行：

```powershell
npm.cmd --prefix frontend test -- --run src/features/upload/UploadForm.test.tsx
npm.cmd --prefix frontend run typecheck
npm.cmd run typecheck
```

预期：聚焦 Vitest、前端 TypeScript 和 E2E TypeScript 全部通过。

- [ ] **步骤 5：验证不可变的历史审计边界**

运行：

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_acceptance_matrix.py tests/unit/test_engineering_audit.py -q --basetemp=tmp/100mb-audit
.venv\Scripts\python.exe scripts/check_acceptance_matrix.py SPEC.md docs/audits/FUNCTIONAL_AUDIT.md
```

E004 绑定其精确历史提交/树及历史边界摘要。绝不能从可变的当前文件刷新它。如果验证失败，应恢复或获取精确的历史 Git 对象并调查不匹配；不得重写历史证据来迎合当前检出内容。

- [ ] **步骤 6：运行完整验证并发布**

运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/container-pytest.ps1 -Image museecho-task3-verification-env:latest
npm.cmd --prefix frontend test -- --run
npm.cmd --prefix frontend run build
.venv\Scripts\python.exe scripts/license_audit.py
git diff --check
```

预期：锁定容器中的 Python 测试套件、全部前端测试、生产前端构建、许可证审计和差异完整性检查均通过。只提交预期文件，推送 `codex/expand-common-audio-formats`，并监控 PR #3 的 `quality`、`e2e` 和 `distribution` 作业直至成功终态。
