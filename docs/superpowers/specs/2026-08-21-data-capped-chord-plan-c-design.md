# MuseEcho 深度和弦识别 Plan C：数据封顶设计修订

日期：2026-08-21

状态：用户已于 2026-08-21 批准 Plan C 及本文；实施计划见 `docs/superpowers/plans/2026-08-21-data-capped-chord-plan-c.md`

基准规格：`docs/superpowers/specs/2026-08-17-deep-chord-recognition-design.md`

## 1. 修订范围与优先级

本文是深度和弦识别规格的数据封顶修订。它不覆盖原始规格，也不改写已经冻结的实验和数据证据。发生冲突时，本文只对以下主题拥有优先级：

- G1 数据就绪门禁；
- A/B 数据课程与训练阶段；
- 首个公开词表；
- 比赛候选的完成与晋级定义；
- IDMT-SMT-Guitar V2、MAESTRO 和后续候选数据的优先级。

原规格中的许可证、防泄漏、测试集隔离、checkpoint 恢复、CPU 复现、模型制品校验、线上回退和 Evidence-first 边界继续有效。

本文后续实施计划只覆盖 Plan C 核心：数据角色、双层 G1、课程冻结、词表收缩、课程比较、统计报告和模型晋级。IDMT-SMT-Guitar V2 的下载审计与 MAESTRO feasibility 是独立工作流，各自需要单独的规格和实施计划；Plan C 核心只消费它们产生的已批准 inventory、manifest 或机器可读 feasibility 结论。

## 2. 已冻结的事实

截至本修订批准时，可合法用于正式和弦训练并完成全量审计的 `real-gold` 为 Winterreise、RWC-P 和 GuitarSet：

- 124 个独立作品；
- 8.9408 小时有效人工或人工复核标注；
- 17,795 个和弦区间；
- `sus2` 只覆盖 15 个独立作品，低于原定每个公开 quality 至少 20 个作品的门槛；
- real-gold train、calibration、validation、test 已按 group 冻结并通过泄漏审计。

完成审计的 `synthetic-supervised` 为 IDMT-SMT-Chord-Sequences 与 Jazznet，合计 41.487981 小时。`decide_training_route()` 已据此冻结 Route A，因为可用合成监督低于原定 60.0 小时门槛。

继续检索发现的数据不能在短期内合法、完整地把 real-gold 提升至 500 个作品和 80 小时。第三方 Kaggle 镜像、来源不明的孤立和弦、无音频标注和未明确许可的数据均不得用于填充门槛。

## 3. 新目标与非目标

### 3.1 新目标

Plan C 在当前合法数据上完成一个可复现、可否定的小数据研究闭环：

1. 比较 real-only、synthetic-to-real 和条件性 score-to-real 三种课程；
2. 在相同冻结真实 validation 上选择一个候选；
3. 候选和传统基线在同一冻结 test 上只比较一次；
4. 无论深度模型是否优于传统基线，都保存可重放的实验、置信区间和失败结论；
5. 只有通过独立晋级门的模型才能作为实验功能进入产品，legacy 仍是安全默认。

### 3.2 非目标

Plan C 不承诺：

- 训练出覆盖任意曲风和任意商业音乐的通用和弦模型；
- 把 124 个作品表述成生产规模数据；
- 用合成、score-derived 或伪标签时长改写 real-gold 数量；
- 通过降低 unknown 门槛、随机文件切分或反复查看 test 制造高分；
- 在许可证未明确时发布由 IDMT-SMT-Guitar V2 或第三方商业音频训练的权重；
- 在 MAESTRO 元数据可行性阶段下载 101 GB 全量音频。

## 4. 双层 G1 门禁

原 `G1 NOT READY` 拆为两个相互独立且必须同时报告的事实：

### 4.1 G1a 数据工程就绪

`G1a PASS` 表示当前数据已经具备可信实验所需的最小工程条件：

- 数据源和许可证已登记；
- 音频与标注适配器完成；
- manifest、音频头、时长和标签覆盖已审计；
- group 和指纹防泄漏规则已执行；
- real-gold 四路切分已经冻结。

G1a 只授权 Plan C 研究实验，不代表数据达到生产规模。

### 4.2 G1b 生产规模充足

`G1b NOT MET` 保留原规划目标：至少 500 个独立作品、80 小时有效 real-gold，并且每个公开的非 `N/X` quality 至少覆盖 20 个独立作品。

G1b 不再阻塞 Plan C 实验，但在数据卡、模型卡、比赛报告和产品开关中必须持续显示为未满足。任何 synthetic、score-derived、增强片段或同曲重复录音都不得计入 G1b。

## 5. 数据角色与隔离

数据集必须且只能属于一个角色：

- `real-gold`：真实演奏音频及人工或人工复核的时间对齐和弦标注；
- `real-score-supervised`：真实演奏音频及从严格对齐 MIDI/乐谱确定性派生的标签；
- `synthetic-supervised`：由符号序列渲染或计算生成的音频和标签；
- `weak-label-validation`：只验证标签转换或数据管线；
- `rejected` 或 `needs-review`：不能进入正式训练。

只有 `real-gold` 可以进入 calibration、validation 和 test。`real-score-supervised` 与 `synthetic-supervised` 只能进入预训练或 train-only 辅助阶段，不能计入 G1，也不能影响真实测试集阈值。

既有 `decide_training_route()` 和 Route A 冻结报告保持不变，作为原 A/B 规划的历史证据。Plan C 是独立的实验课程，不把 41.487981 小时解释为 Route B 已通过。

## 6. Plan C 实验课程

三个课程共享相同的模型架构、real-gold finetune 数据、数据增强边界、校准集、validation、测试协议和 CPU 预算。除预训练来源外，不允许为某个课程单独优化模型容量或后处理规则。

### 6.1 C0 real-only

- 从固定随机初始化训练；
- 只读取 real-gold train；
- 作为数据受限条件下的深度基线。

### 6.2 C1 synthetic-to-real

- 先在 IDMT-SMT-Chord-Sequences 与 Jazznet 的 role-pure train manifest 上预训练；
- 保存独立的预训练 checkpoint、优化器状态、manifest 哈希和报告；
- 再用与 C0 完全相同的 real-gold train 和 finetune 配置微调；
- 不因 synthetic 小于 60 小时而跳过此对照。

### 6.3 C2 score-to-real

- 只有 MAESTRO 元数据、作品分组、MIDI 对齐和确定性和弦派生 feasibility 全部通过后才创建；
- feasibility 阶段只下载固定哈希的官方小型元数据和程序生成 MIDI 夹具，不下载全量音频；
- 真正进入 C2 前必须单独批准音频下载、训练许可证和 `real-score-supervised` manifest；
- 任一条件未满足时，C2 以结构化 `skipped` 结论结束，不阻塞 C0、C1 或 Plan C 完成。

### 6.4 重复与选择规则

- C0、C1 和可用的 C2 使用同一组固定随机种子：`20260821`、`20260822`、`20260823`；
- calibration 只拟合置信度参数，不参与 checkpoint 选择；
- 课程比较使用三个种子的中位 validation 结果，不能只挑最好种子；课程按以下顺序以未舍入数值进行确定性排序：Plan C 精确词表 WCSR、Plan C 公开 quality 的 Macro-F1、published-known precision、coverage、较低的五分钟 CPU 墙钟时间；
- 所有数值仍相同时优先选择预训练阶段更少的课程，固定顺序为 C0、C1、C2；
- 获胜课程中选择最接近该课程中位精确词表 WCSR 的种子 checkpoint；并列时选择数值最小的种子；
- 选择规则、种子和 manifest 哈希必须在读取 test 之前冻结。

## 7. 数据受限词表

Plan C 首个候选词表为：

- `maj`
- `min`
- `7`
- `maj7`
- `min7`
- `dim`
- `hdim7`
- `sus4`
- `N`
- `X`

`sus2` 在全部 real-gold 中也只有 15 个独立作品，因此 Plan C 将它映射为 `X`，不能作为公开类别。

正式训练前必须只使用 real-gold train manifest 重新统计公开 quality 的独立 group 数。任何不足 20 个 train group 的 quality 继续映射为 `X`。validation 和 test 的类别统计不得用于扩大词表；本修订允许进一步缩小词表，不允许在 Plan C 内重新扩大。

Bass head 可以保留为辅助训练目标。Plan C 不承诺向产品公开转位，除非后续独立规格批准该行为。

## 8. 小数据评测与统计

所有课程和 legacy 基线必须使用同一参考标注和同一评测实现。除原规格指标外，Plan C 增加：

- 以 work/cover group 为重采样单位的 10,000 次 bootstrap 95% 置信区间；
- bootstrap 随机种子固定为 `20260821` 并写入报告；
- Winterreise、RWC-P、GuitarSet 分数据集结果；
- 三个数据集等权的 dataset-macro 结果，防止较大来源支配总分；
- 每个课程三个训练种子的中位数、最小值和最大值；
- 失败实验、C2 跳过原因和未支持 quality 的明确记录。

测试集只能在课程、checkpoint、词表、校准方法和阈值全部冻结后运行一次。若 test 结果被用于修改模型，该 test 必须降级，Plan C 在没有新合法测试集时停止晋级。

## 9. 项目完成与模型晋级分离

### 9.1 Plan C 实验完成

满足以下条件即表示研究任务完成，无论模型成绩是否提升：

1. C0、C1 和可用的 C2 按固定协议运行并保存可恢复 checkpoint；
2. 不可用的 C2 有机器可读的跳过原因；
3. 所有 validation、bootstrap、分数据集和资源报告可重放；
4. 一个候选在读取 test 前被冻结；
5. legacy 与候选的单次 frozen-test 报告完成；
6. 数据卡和模型卡明确标记 G1b 未满足及适用范围。

一个诚实、可复现的“未超过 legacy”结论属于 Plan C 的有效完成结果。

### 9.2 实验模型晋级

候选只有同时满足以下条件才可进入受控实验功能：

- frozen test 的 maj/min WCSR 不低于 legacy；
- frozen test 的 Plan C 精确词表 WCSR 严格高于 legacy；
- published-known precision、coverage、ECE、确定性、ONNX parity 和 CPU 资源门满足原规格；
- 权重分发所涉及的每个训练数据集已经明确批准；
- 产品持续显示实验状态并保留 legacy 回退。

原规格“精确词表 WCSR 相对 legacy 提升至少 8 个百分点”保留为强比赛结果和生产候选目标，不再是 Plan C 研究任务完成的必要条件。未通过晋级门时，深度模型不得成为默认实现，产品继续使用 legacy。

## 10. 数据候选的处理

### 10.1 IDMT-SMT-Guitar V2

独立数据审计工作流可以执行可恢复下载、MD5 校验、安全解压和只读审计。其 CC BY-NC-ND 4.0 许可证在法律结论前保持 `needs-review`：不得进入 C0、C1、C2，不得据此批准权重发布。

### 10.2 MAESTRO

独立 feasibility 工作流先处理固定官方元数据与程序生成 MIDI 夹具。Plan C 只接受机器可读 `passed` 结论和已批准 manifest；`real-score-supervised` 不进入 calibration、validation、test，也不计入 G1。101 GB 全量音频下载需要 feasibility 通过后的独立批准。

### 10.3 McGill-Billboard

第三方 Kaggle 镜像只有 chromagram 和和弦标注，没有原始音频。它保持 `needs-review`。只有官方标注许可、合法持有音频、作品/cover 分组和指纹审计全部通过后，才可通过后续规格加入 real-gold。

### 10.4 其他 Kaggle 候选

来源不明的 Major/Minor 短音频、单音吉他数据、教学 notebook 和 MOSS-Music 模型不进入 Plan C 数据课程。它们不能增加 G1，不需要下载。

## 11. 失败关闭与错误处理

- manifest 含混合角色时，训练在读取音频前失败；
- synthetic 或 score-derived 路径指向 calibration、validation 或 test 时失败；
- 词表统计读取非 train split 时失败；
- C1 缺失任一正式 synthetic manifest 时明确失败，不静默退化为 C0；
- C2 feasibility 未通过时只生成 `skipped` 报告，不创建空 manifest；
- test 身份、模型哈希、词表或校准哈希不匹配时拒绝评测；
- 任一数据许可为 `needs-review`、`blocked` 或权重分发状态不明确时拒绝实验模型晋级；
- 不允许用复制、裁剪、增强或移调后的样本增加独立作品计数。

## 12. 测试策略

实施必须遵循测试先行，并至少证明：

- `real-score-supervised` 是合法但与 real-gold 严格隔离的角色；
- `decide_training_route()` 仍对已冻结 inventory 返回 Route A；
- Plan C 固定产生 C0、C1，并按 feasibility 确定 C2 或结构化跳过；
- 三个课程只能共享同一 real-gold finetune、calibration、validation、test 身份；
- 词表只根据 real-gold train group 统计收缩；
- `sus2` 确定性映射为 `X`；
- 三种课程和种子顺序变化不改变中位课程选择；
- group bootstrap 在固定种子下逐字节可复现；
- synthetic/score-derived 无法进入真实评测；
- 未通过权重许可或晋级门的模型不能成为产品默认值；
- 现有 checkpoint 精确恢复、CPU 复现、全 `N/X` batch、两首 overfit 和 CPU smoke 继续通过。

## 13. 文档与证据

实施完成后必须更新或新增：

- `docs/ml/DATA_CARD.md`：同时显示 G1a、G1b 和各数据角色；
- `docs/ml/PHASE_APPROVAL.md`：记录 Plan C 授权范围；
- 实验索引：登记 C0、C1、C2/skip 和 frozen-test；
- 模型卡：声明数据上限、词表、置信区间、未支持类别和适用范围；
- 机器可读课程冻结文件：绑定 manifest、split、种子、词表和选择规则哈希；
- 旧 Route A 冻结报告：只读保留，不覆盖或重新解释。

对外结论必须限定为：在公开、合法且可复现的有限真实数据上，对传统算法、real-only 和辅助预训练进行了冻结协议比较；结果只代表所列数据集，不证明对所有音乐风格具有生产级泛化能力。

## 14. 完成定义

本修订完成实现需要同时满足：

1. 双层 G1 状态及 Plan C 数据角色进入代码和文档；
2. C0、C1、条件性 C2 课程可确定性冻结；
3. 数据受限词表从 train-only 统计生成并绑定哈希；
4. 三种课程使用相同真实 finetune 和评测边界；
5. 小数据 bootstrap 与 dataset-macro 报告可复现；
6. 单次 test 访问和模型晋级规则可机器校验；
7. 未达到晋级门时 legacy 自动保持默认；
8. 所有原始数据、音频、checkpoint 和缓存继续位于 Git 忽略边界；
9. 文档不把 G1a、Plan C 完成或合成时长表述成 G1b 已满足。
