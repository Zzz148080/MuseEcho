# Broadcast WAV 零填充兼容性设计

## 问题

MuseEcho 在 FFprobe 之前就拒绝 `D:\CloudMusic\华晨宇 - 忒修斯的船.wav`，尽管该文件是有效的 Pro Tools Broadcast WAV。其 RIFF 和 WAVE 边界正确，FFprobe 识别出一个探测分数为 99 的 `pcm_s24le` 流，时长为 289.065 秒。该文件使用一个 40 字节的非扩展 PCM `fmt ` 块，其中声明的扩展大小和余下 22 个填充字节均为零。MuseEcho 目前只接受长度恰好为 16 或 18 字节的非扩展 PCM `fmt ` 块。

## 决策

保留现有严格的 RIFF 块遍历和 PCM 字段检查。对于非扩展 PCM 或 IEEE-float WAVE 格式：

- 继续接受标准的 16 字节 `fmt ` 载荷；
- 仅当 `cbSize` 为零且 `cbSize` 后每个字节均为零填充时，才接受 18 至 64 字节的载荷；
- 拒绝任何非零尾随字节、非零扩展大小、重复或乱序的 `fmt `/`data` 块、不一致的 RIFF 长度或无效的 PCM 采样率/对齐字段；
- WAVEFORMATEXTENSIBLE 验证保持不变。

这一方案比将签名信任委托给 FFprobe 更窄，也比把 Pro Tools 特有的块序列加入白名单更具可移植性。

## 验证

增加聚焦测试，构造相同的 40 字节 PCM `fmt ` 布局，并证明验证能到达现有的探测/解码边界。再增加一个配对拒绝测试，其中包含一个非零填充字节。运行上传测试模块，然后重新构建或重新加载开发应用，并通过 `https://localhost:4173/api/analyses` 提交用户的原始 WAV。成功修复应返回 HTTP 202 并创建分析，而不是返回 `invalid_audio` 或网关 502。
