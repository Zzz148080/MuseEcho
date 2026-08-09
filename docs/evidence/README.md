# Task 19 系统验证证据

本目录只保存可重复命令、工具版本、非敏感环境摘要和性能结果。不会保存上传音频、Cookie、CSRF/能力令牌、问题正文、密钥或服务日志正文。

## 浏览器与安全验证

标准环境使用 Node `22.22.2`、npm `10.9.8`、Playwright `1.61.1`、Python `3.12`，并要求 `ffmpeg`/`ffprobe` 位于 `PATH`。首次执行：

```powershell
npm ci
npm --prefix frontend ci
npx playwright install chromium
npm run typecheck
npm run e2e
```

本地已有 Chrome 时可用 `MUSEECHO_E2E_CHANNEL=chrome`，CI 不设置该变量并使用 Playwright 固定版本浏览器。测试服务器使用临时自签名 HTTPS 证书、临时 SQLite/密文目录和无外部 LLM 的确定性回退；它组装的仍是真实 API、加密存储、单工作队列和 MIR 管线。

覆盖范围：

- 上传 → 分析 → Music DNA → 结构地图 → Range 播放 → 拖选 → 和弦 → fallback 问答 → 永久删除；
- console、page error、失败请求与 5xx 响应；
- 1440×900、768×1024、390×844，无横向溢出，桌面双栏及窄屏堆叠；
- 键盘原生选区控件和可访问名称；
- 未授权/不存在资源不可区分、CSRF 双提交、Range `206`、32 MiB multipart 前置 `413`；
- 审计日志不包含文件名、问题正文、Cookie 名称和值。

## 五分钟性能基准

```powershell
uv run pytest -q tests/performance/test_five_minute_budget.py
uv run python scripts/benchmark.py --duration 300 --json docs/evidence/performance.json
```

基准以流式方式生成 300 秒、22.05 kHz、单声道 C–G–Am–F PCM WAV，然后走真实上传校验、加密持久化、单工作队列、解码、节奏、调性、结构、和弦、Evidence 和数据库持久化。进程 CPU 亲和性被强制为 2 核。

本次 Windows 实测见 [performance.json](performance.json)：总墙钟 `11.201268s`，峰值 RSS `323964928` 字节，结果已持久化，低于 `90s` 和 `4 GiB` 门槛。当前 Docker Desktop 守护进程不可用，因此 4 GiB 结论来自全程进程峰值观测，不宣称施加了容器硬内存上限；后续 Task 20 容器验证应在 Docker 可用时补充硬限额证据。

`performance.json` 不含绝对工作目录、用户名、令牌或输入音频，只记录平台版本、CPU 数量/亲和性、阈值、阶段耗时和聚合结果数量。
