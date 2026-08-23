# BTC-170 独立验证实验设计

## 状态

本设计已于 2026-08-23 获用户确认。实验只用于开发期 validation 比较，不构成模型
promotion，不改变产品默认算法，也不授权读取或重新使用任何已封存 test。

## 背景与目标

Plan D 的最终状态为 `data-first-required`。现有自研模型在三个随机种子的 real-gold
validation 上不稳定，混合方案也没有超过 `chroma-triad-viterbi-v1`；当前 legacy
exact-quality WCSR 为 `0.166596`。与此同时，`jayg996/BTC-ISMIR19` 官方仓库提供了
一套 170 类双向 Transformer 预训练权重，能够直接从音频产生带开始时间、结束时间和
和弦标签的预测。

本实验的目标是将 BTC-170 作为隔离候选接入 MuseEcho 的 ML 开发环境，并使用现有
real-gold validation 和统一指标回答以下问题：

1. BTC-170 是否显著超过当前 legacy 的 exact-quality WCSR；
2. 改善是否至少覆盖两个真实数据集，而不是只适配单一数据域；
3. CPU 推理成本、峰值内存和确定性是否允许后续继续研究；
4. BTC 的预训练能力是否值得在后续阶段与独立 bass/转位侧通道组合。

## 非目标

- 不读取、解封、重放或重新生成任何 Plan C test 证据。
- 不建立新的 test v2，不执行 promotion，不修改默认算法。
- 不在本阶段扩充 MuseEcho 公开词表。
- 不在本阶段训练或微调 BTC，也不接入 Basic Pitch。
- 不把 BTC 依赖加入产品运行时、离线发布包或容器镜像。
- 不把上游 `.pt` 权重提交到 Git。

## 已选方案

采用“当前 ML 环境兼容适配器”，而不是运行上游旧环境或建立独立容器。

适配器在 MuseEcho 的 Python 3.12、PyTorch 2.8 和 librosa 0.11 环境中复现 BTC 推理
结构与特征口径，并复用现有 evaluation 数据结构。上游实现中与模型结构和推理语义
有关的部分按 MIT 许可证移植并保留归属说明；旧版命令行、训练代码、MIDI 导出、数据集
加载器和无关基线不进入项目。

这种方式的优点是评测进程、CPU 计时和现有候选处于同一运行环境，且能使用当前安全
加载能力和测试基础设施。代价是必须验证当前实现与上游 checkpoint 的张量结构及推理
语义完全一致。

## 系统边界

BTC 候选仅存在于 `ml` 包内部，由四个清晰边界组成：

1. **上游制品锁定**：记录仓库、commit、下载 URL、文件字节数、Git blob SHA-1、下载后
   SHA-256、许可证和本地缓存位置；实际值在获取制品时一次性计算并写入版本化锁定文件。
2. **模型与 checkpoint**：定义当前 PyTorch 兼容的 BTC 推理网络，安全加载固定权重并
   校验完整张量集合、名称、形状和数值类型。
3. **特征与标签适配**：复现 22,050 Hz 单声道、144-bin CQT、24 bins/octave 输入；将
   BTC 输出转成 MuseEcho 的规范和弦与完整时间轴。
4. **validation runner**：只接受 real-gold validation manifest，调用现有统一评测指标，
   记录预测摘要、环境、CPU 和内存证据，生成可重放报告。

这些模块不由 `src/museecho` 导入，也不注册为产品算法。

## 数据流

```text
固定 real-gold validation manifest
            │
            ├── 路径约束与音频摘要校验
            │
            ├── 22,050 Hz 单声道重采样
            │
            ├── BTC 144-bin CQT 特征
            │
            ├── BTC-170 安全 checkpoint 推理
            │
            ├── 标签映射、连续帧合并、完整时间轴修复
            │
            └── 统一 metrics + CPU/内存记录
                         │
                         └── 路径无关预测与 validation 报告
```

runner 不接收泛化的 split 参数。它要求 manifest 的 `split` 严格等于 `validation`、
`corpus_role` 严格等于 `real-gold`，并校验每条音频仍位于已声明的数据集根目录内。任何
其他 split，包括 train、calibration 和 test，均在加载音频前拒绝。

## 词表映射

BTC-170 的 168 个声学类别由 12 个根音与以下 14 种 quality 的笛卡尔积组成，另有 `N`
和 `X`：

`min`、`maj`、`dim`、`aug`、`min6`、`maj6`、`min7`、`minmaj7`、`maj7`、`7`、
`dim7`、`hdim7`、`sus2`、`sus4`。

映射规则冻结如下：

- `maj`、`min`、`7`、`maj7`、`min7`、`dim`、`hdim7`、`sus2`、`sus4` 保留；
- `aug`、`min6`、`maj6`、`minmaj7`、`dim7` 映射为 `X`，并记录
  `unsupported-quality:<quality>`；
- `N` 保持 `N`，`X` 保持 `X`；
- BTC 不输出 bass，因此所有已知兼容和弦暂时使用根音位置 `bass="1"`；
- 报告明确标注本实验不评估转位识别能力，不把根音位置默认值解释成 bass 预测。

不把不支持的 quality 折叠到相近类别，以避免人为提高 MuseEcho 词表指标。如果实验值得
继续，再通过独立设计扩充词表并重新冻结比较协议。

## 时间轴与置信度

相邻同类帧合并为事件。事件边界来自 BTC 固定帧网格，首事件必须从 `0.0` 开始，末事件
必须精确结束在 manifest 时长。预测缺口补为 `N`；非法标签补为 `X`。事件重叠、倒序、
零时长或越过音频尾部均视为适配器错误，不通过静默裁剪掩盖。

第一阶段只使用 BTC 帧级最大 softmax 概率形成事件置信度，不在 validation 上拟合温度或
阈值。ECE、known precision 和 coverage 在报告中保留，但标记为“未校准、仅供诊断”；
候选结论以不依赖阈值的 WCSR、macro-F1、边界和操作指标为主。若 BTC 进入后续阶段，
温度和发布阈值必须只用 calibration 拟合，并由新的设计冻结。

## checkpoint 安全与可重复性

上游权重来自官方仓库中的 `test/btc_model_large_voca.pt`。获取流程先下载到 Git 忽略的
缓存目录，再计算文件 SHA-256；锁定文件记录实际摘要后，后续运行只接受完全匹配的字节。
下载中断、文件尺寸异常、摘要不一致或来源重定向到非批准主机均立即失败。

禁止使用 `torch.load(..., weights_only=False)`。首先尝试 `weights_only=True`；若旧
checkpoint 因受限 NumPy 类型不能直接读取，只允许在无网络、无工作区写权限的一次性
转换进程中加载，并仅输出纯张量 `state_dict`、均值和标准差。转换产物与源文件分别记录
SHA-256，逐张量校验名称、形状、dtype 和有限值。无法完成安全转换时，实验状态为
`blocked-unsafe-checkpoint`，不得降低加载安全要求。

模型加载要求 checkpoint 张量集合与当前结构完全一致。缺失键、额外键、形状不符、非有限
统计量或非浮点模型参数均立即拒绝；不使用 `strict=False` 部分加载。

## 评测与比较

BTC 与 `chroma-triad-viterbi-v1` 使用同一 real-gold validation manifest、同一
`evaluation-v1.json` 和同一指标实现。报告至少包含：

- root、majmin、triads、sevenths 和 exact-quality WCSR；
- quality macro-F1；
- 0.05 秒容差下的边界 precision、recall 和 F1；
- 预测事件数、参考事件数和事件数量比例；
- `N`、`X`、不支持 quality 的时长比例；
- 总 CPU 秒、五分钟归一化 CPU 秒、实时系数和峰值进程内存；
- GuitarSet、RWC Popular、Schubert Winterreise 的相同分项；
- 输入 manifest、配置、权重、适配器源代码和预测 JSONL 的 SHA-256 身份。

validation 已参与开发，因此结果只能决定是否继续 BTC 研究，不能用于生产 promotion。

## 继续研究门禁

只有同时满足下列条件，BTC 才进入后续 bass/转位或词表扩充设计：

1. exact-quality WCSR 严格高于 legacy 基准 `0.166596`；
2. 至少两个真实数据集的 exact-quality WCSR 高于各自 legacy 结果；
3. 总体 root WCSR 和边界 F1 均不低于 legacy；
4. 推理结果在同一机器重复运行时预测摘要完全一致；
5. 五分钟音频 CPU 基准完成且无内存失控；
6. checkpoint 安全、许可证记录和制品身份检查全部通过。

报告同时给出效应大小和按作品分组的 bootstrap 置信区间，避免仅凭极小的点估计提升继续
开发。由于 validation 规模有限，本门禁不声明统计显著性等同于泛化证明。

## 失败处理

- 无法下载或摘要不匹配：状态 `blocked-artifact-integrity`；
- checkpoint 不能安全加载：状态 `blocked-unsafe-checkpoint`；
- 模型结构与权重不一致：状态 `failed-checkpoint-contract`；
- 音频损坏、为空、含非有限值或时长与 manifest 不符：整次实验失败并指出 track ID；
- runner 收到非 validation manifest：在读取音频前抛出权限错误；
- 输出时间轴不完整或非法：拒绝该运行，不生成正式比较报告；
- 单一数据集退化：如实记录，不用总体平均隐藏；
- 任一继续研究门禁失败：结论为 `btc-not-selected`，默认算法保持不变。

## 测试策略

实现采用测试先行：

1. 标签映射测试覆盖全部 170 类、严格 `X` 策略、`N/X` 与根音位置 bass；
2. 时间轴测试覆盖连续帧合并、首尾覆盖、`N` 缺口、非法重叠和零时长；
3. checkpoint 测试覆盖摘要、严格张量集合、shape、dtype、有限值和不安全加载拒绝；
4. 特征测试固定采样率、CQT 形状、短音频、空音频和确定性；
5. 模型测试使用最小纯张量 fixture 验证输出形状和重复推理一致性；
6. runner 测试证明只接受 real-gold validation，并在音频读取前拒绝其他 split；
7. 报告测试验证路径无关、摘要绑定、数据集分项和未校准置信度标记；
8. 集成 smoke 使用合成短音频，不使用封存数据；
9. 通过所有 ML 单元测试与 Ruff 后，才运行真实 validation 和 CPU 基准。

每个新增行为必须先出现针对缺失功能的预期失败测试，再实现最小代码使其通过。

## 许可证与交付边界

BTC 仓库源代码声明 MIT。设计实施时更新第三方许可清单，注明移植文件、上游 commit 和
版权归属。权重虽然随 MIT 仓库发布，但 README 说明训练音频来自 Isophonics、Robbie
Williams、UsPop2002 及在线音乐服务；因此本实验只授权内部比赛研究和 validation。

若未来需要在公开发行物或商业产品中分发 BTC 权重，必须先完成独立权利审计。未完成审计
前，权重、转换产物和预测缓存均不得进入 release、Docker 镜像或公开制品。

## 实验产物

成功运行产生以下路径无关、可核验产物：

- 上游制品锁定记录；
- BTC validation 预测 JSONL；
- BTC 统一指标 JSON 报告；
- legacy 与 BTC 对照 Markdown 报告；
- CPU/内存操作证据；
- 开发门禁决策 JSON；
- BTC 实验模型卡。

产物使用不可变写入语义：相同路径存在不同内容时拒绝覆盖。它们不得包含本机绝对路径、
音频字节或封存 test 信息。

## 后续分支

- 门禁通过：提出独立设计，评估扩充 quality 词表以及 Basic Pitch bass/转位侧通道；
- 门禁失败：保留 BTC 报告作为对照证据，停止集成，不调整产品默认算法；
- 权重权利或安全阻塞：停止实验，不用其他非官方权重替代。
