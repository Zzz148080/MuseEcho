# Broadcast WAV 零填充兼容性实施计划

> **供自主执行者使用：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐项实施本计划。步骤使用复选框（`- [ ]`）语法跟踪。

**目标：** 接受普通 PCM `fmt ` 块只包含零填充的有效 Pro Tools Broadcast WAV 文件，同时不削弱 MuseEcho 的签名验证。

**架构：** 仅扩展上传边界中的 `_validate_pcm_wave_format`。保留现有 RIFF 解析器、注册表、FFprobe/FFmpeg 验证、上传限制、时长限制和编解码器策略。

**技术栈：** Python 3.12、pytest、FastAPI 上传服务、FFprobe/FFmpeg、Docker Compose。

## 全局约束

- 最大音频载荷仍严格为 `100 * 1024 * 1024` 字节。
- 仅当 `cbSize == 0` 且所有尾随字节均为零时，才接受非扩展 PCM 填充。
- WAVEFORMATEXTENSIBLE、块顺序、RIFF 长度、PCM 字段、解码和时长检查保持不变。
- 修复后，用户的原始 WAV 必须通过真实 HTTPS 网关。

---

### 任务 1：接受普通 PCM `fmt ` 块的零填充

**文件：**
- 修改：`tests/api/test_upload.py`
- 修改：`src/museecho/application/uploads.py`

**接口：**
- 输入：`_minimal_wave(...)`、`FFmpegAudioValidator` 和 `audio_format_for_suffix(".wav")`。
- 输出：`_validate_pcm_wave_format(format_data: bytes) -> None` 接受标准 PCM 数据及有界的全零填充。

- [ ] **步骤 1：编写失败的接受与拒绝测试**

构造一个 PCM WAVE，其 `fmt ` 载荷为标准 16 字节，随后是 `cbSize=0` 和 22 个零字节。断言 `FFmpegAudioValidator` 会到达 monkeypatch 后的 `probe_audio` 和 `decode_audio` 调用。在配对测试中，将最后一个填充字节替换为 `\x01`，并断言在调用任一工具前发生 `InvalidAudioError`。

- [ ] **步骤 2：运行聚焦测试并确认 RED**

运行：`python -m pytest tests/api/test_upload.py -k "zero_padded_pcm_format" -q`

预期：接受用例以 `InvalidAudioError: audio file signature is invalid` 失败；非零填充拒绝用例通过。

- [ ] **步骤 3：实施最小验证变更**

对于非扩展格式，保留 16 字节标准用例。否则要求至少 18 字节，要求偏移 16 处的两字节扩展大小为零，并在偏移 18 之后有任何非零字节时拒绝。保留外层 `fmt ` 块现有的 64 字节上限。

- [ ] **步骤 4：确认聚焦测试和模块测试为 GREEN**

运行：`python -m pytest tests/api/test_upload.py -k "zero_padded_pcm_format" -q`

预期：2 个测试通过。

运行：`python -m pytest tests/api/test_upload.py -q`

预期：所有可运行的上传测试均通过；环境特定的跳过项保持明确记录。

- [ ] **步骤 5：通过开发栈验证实际文件**

如果热重载尚未应用源代码变更，则重启开发应用。通过 `https://localhost:4173/api/analyses` 提交 `D:\CloudMusic\华晨宇 - 忒修斯的船.wav`，确认 HTTP 202，确认分析到达成功终态，并确认两个 Compose 服务均保持健康。

- [ ] **步骤 6：提交**

仅暂存这两个源代码/测试文件以及本设计和计划，然后使用提交消息 `fix: accept zero-padded broadcast wav formats` 提交。
