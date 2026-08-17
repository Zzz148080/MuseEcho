# MuseEcho 第二阶段：深度学习和弦识别实施计划

> **执行状态：** 已由用户于 2026-08-18 书面批准并开始实施；复选框只记录真实完成的工作。

**目标：** 建立真实音乐数据上的可复现深度学习和弦识别系统，扩展常见和弦词表，在冻结测试集上显著优于现有模板基线，并以 ONNX 模型安全接入 MuseEcho。

**规格：** `docs/superpowers/specs/2026-08-17-deep-chord-recognition-design.md`

**架构：** 训练系统位于独立 `ml/` Python 项目；产品运行时只加载带哈希 manifest 的 ONNX 制品。模型采用 CQT 输入、小型多任务 CRNN 和确定性时序后处理。现有 `chroma-triad-viterbi-v1` 通过统一接口保留为基线与故障回退。

**技术栈：** Python 3.12、uv、PyTorch、NumPy、librosa、mir_eval、scikit-learn、ONNX、ONNX Runtime、pytest；现有 FastAPI、SQLAlchemy、React、TypeScript 和 Playwright 产品栈。

## 全局约束

- 比赛阶段的文档、代码、配置和可发布模型均在独立比赛工作区开发，不删除或移动原课程项目文件。
- 原始音乐、特征缓存、训练 checkpoint、优化器状态和本地实验日志不得提交 Git。
- 数据集必须先完成许可登记；“能下载”不等于“可训练或可发布”。
- 测试集按作品/cover group 冻结，不能按帧随机切分，也不能在调参时反复查看。
- 合成音频只用于单元测试和故障探针，不作为比赛准确率的主要证据。
- 每个正式实验绑定 Git SHA、配置、数据清单哈希、切分哈希、随机种子和输出哈希。
- 生产推理不得访问网络，不包含 PyTorch，不在启动时动态下载模型。
- 新模型未达到质量、校准、性能和产品回归门槛前，默认识别器保持 legacy。
- 所有适合确定性测试的工作遵循 RED → GREEN → REFACTOR；模型指标改进必须保留真实失败实验。

## 阶段门禁

| 门禁 | 进入条件 | 退出证据 |
| --- | --- | --- |
| G0 规格批准 | SPEC 与 PLAN 已审阅 | 用户书面批准及绑定的 Git SHA |
| G1 数据就绪 | 许可、转换和防泄漏规则已实现 | 数据卡、清单哈希、切分审计和类别统计 |
| G2 基线冻结 | 统一评测器完成 | legacy 在冻结验证/测试协议上的报告 |
| G3 训练链可信 | 小数据 overfit、恢复和复现通过 | 两次同配置训练的一致性报告 |
| G4 候选晋级 | 验证集选模完成，候选冻结 | 一次正式测试集报告及全部质量门槛 |
| G5 产品候选 | ONNX、回退和契约升级完成 | parity、E2E、2 vCPU/4 GB 性能和完整回归 |

---

### 任务 1：建立独立 ML 工程和制品边界

**文件：**

- 新建：`ml/pyproject.toml`
- 新建：`ml/uv.lock`
- 新建：`ml/README.md`
- 新建：`ml/src/museecho_ml/__init__.py`
- 新建：`ml/tests/test_package_boundary.py`
- 修改：`.gitignore`
- 新建：`models/chords/README.md`
- 新建：`models/chords/manifest.schema.json`

**接口：** 训练项目可独立安装和测试；主产品不导入 `museecho_ml`；大制品路径默认忽略。

- [x] **步骤 1：编写边界失败测试**

测试训练包导入、配置目录存在、manifest schema 可解析，并扫描 Git 跟踪候选，拒绝音频、checkpoint、特征缓存和实验数据库。

- [x] **步骤 2：运行并确认 RED**

运行：`uv run --project ml pytest -q ml/tests/test_package_boundary.py`

预期：FAIL，因为独立 ML 工程尚不存在。

- [x] **步骤 3：建立最小训练项目**

锁定训练、评测、导出依赖。训练依赖不加入主产品的默认 runtime；`models/chords` 只定义制品合同，不提交未通过门禁的模型。

- [x] **步骤 4：验证 GREEN 和产品隔离**

运行 ML 单测，并使用 `rg` 确认 `src/museecho` 没有导入 PyTorch 或训练包。

- [x] **步骤 5：提交**

提交消息：`build: establish isolated chord ml workspace`

### 任务 2：实现规范和弦标签与词表

**文件：**

- 新建：`ml/src/museecho_ml/labels.py`
- 新建：`ml/src/museecho_ml/vocabulary.py`
- 新建：`ml/tests/test_labels.py`
- 新建：`ml/configs/vocabulary-v2.json`

**接口：** `parse_annotation(raw) -> CanonicalChord`；`CanonicalChord.transpose(semitones)`；标签可编码为 root/quality/bass heads 并无损 round-trip。

- [x] **步骤 1：固定接受和拒绝样例**

覆盖 Harte 风格标签、转位、等音、`N`、`X`、七和弦、挂留和弦、超出词表标签及恶意/畸形输入。

- [x] **步骤 2：运行 RED**

运行：`uv run --project ml pytest -q ml/tests/test_labels.py`

- [x] **步骤 3：实现规范化与分层编码**

首发性质严格使用 SPEC 词表。`aug/dim7/6/9/add9` 等映射为 `X` 并保留转换原因，不静默映射成大小三和弦。

- [x] **步骤 4：增加性质覆盖和移调性质测试**

对所有 12 个根音、所有首发 quality 和全部合法 bass 运行 encode/decode/transpose round-trip。

- [x] **步骤 5：提交**

提交消息：`feat: define hierarchical chord vocabulary`

### 任务 3：建立数据登记、许可和适配器

**文件：**

- 新建：`ml/src/museecho_ml/data/registry.py`
- 新建：`ml/src/museecho_ml/data/manifest.py`
- 新建：`ml/src/museecho_ml/data/adapters/base.py`
- 新建：`ml/src/museecho_ml/data/adapters/isophonics.py`
- 新建：`ml/src/museecho_ml/data/adapters/billboard.py`
- 新建：`ml/src/museecho_ml/data/adapters/rwc.py`
- 新建：`ml/src/museecho_ml/data/adapters/winterreise.py`
- 新建：`ml/tests/data/test_adapters.py`
- 新建：`docs/ml/DATA_CARD.md`
- 新建：`docs/ml/dataset-registry.example.json`

**接口：** 每个适配器把用户合法持有的本地音频与标注转换为统一 manifest，不负责绕过登录、购买、许可证或访问控制。

- [x] **步骤 1：逐项完成数据源许可调查**

对 Isophonics、McGill Billboard、RWC Popular Music 和 Schubert Winterreise 分别记录标注许可、音频取得方式、可否用于模型训练、可否发布权重和引用要求。状态只能是 `approved`、`blocked` 或 `needs-review`。

调查结论已记录在 `docs/ml/dataset-registry.example.json`：Winterreise 获准本地训练；
RWC-P 音频与官方标注均为 CC-BY-NC-4.0，在用户确认非商业比赛与私有云训练后获准用于该
范围；Isophonics 与 McGill Billboard 因许可/官方来源不足继续保持 `needs-review`。模型权重
发布权与训练许可分离，未被本步骤自动放行。

- [x] **步骤 2：编写 manifest 合同测试**

缺少许可证、哈希、作品 ID、标注版本或本地路径越界时必须失败。测试只使用程序生成的小型音频。

- [x] **步骤 3：实现只读适配器**

适配器不复制音频到仓库，不修改原数据集；输出规范区间、转换统计和不可解析标签报告。

- [x] **步骤 4：生成真实数据盘点报告**

输出总作品数、总时长、每种 quality 的作品数/时长、`N/X` 占比和数据源分布。不得把未获批准的数据计入正式训练清单。

完成证据：`docs/ml/winterreise-inventory-v2.1.json`。Winterreise 2.1 的 48 条录音、24
个作品和 4328 个区间已完成只读哈希与统计；正式本地 manifest 哈希为
`0bf74b8b4ea25e1322fa75db106747dccff942580119b7a4b3f0db2f11a4af17`。

- [x] **步骤 5：执行 G1 数据数量检查**

正式训练建议至少包含 500 个相互独立作品和 80 小时有效标注；每个拟发布的非 `N/X` quality 至少来自 20 个独立作品。未达到时必须补充合法数据或书面缩小词表，不能用同一批合成和弦填充。

检查结论：`G1 NOT READY`。当前仅 24 个作品、2.214 小时有效标注；`maj7`、`min7`、
`dim`、`hdim7`、`sus2`、`sus4` 均未达到每类 20 个独立作品。该数据可用于训练链 smoke，
不能单独作为比赛候选训练集。

- [ ] **步骤 6：提交**

提交消息：`feat: add licensed chord dataset registry`

### 任务 4：实现去重和冻结切分

**文件：**

- 新建：`ml/src/museecho_ml/data/fingerprint.py`
- 新建：`ml/src/museecho_ml/data/split.py`
- 新建：`ml/tests/data/test_split.py`
- 新建：`ml/configs/split-v1.json`
- 生成：`docs/ml/split-audit-v1.json`

**接口：** `build_split(manifest, policy, seed)` 生成不可变 train/calibration/validation/test 清单和 SHA-256。

- [x] **步骤 1：编写泄漏反例**

覆盖同作品不同录音、同 artist、重复音频、裁剪片段和缺失 group metadata。证明简单随机帧切分会失败。

已用确定性测试覆盖作品/cover 合并、可选 artist-disjoint、跨 cover 精确音频哈希冲突、
PCM 裁剪近重复和必填 group metadata；切分单位固定为连通作品组而非帧。

- [x] **步骤 2：实现元数据分组和音频近重复检测**

先按显式 work/cover group 聚合，再用轻量音频指纹发现遗漏。疑似跨集重复进入人工审计清单，不自动忽略。

已实现作品/cover/可选 artist 连通分组、跨 cover 精确哈希 fail-closed，以及有界内存的
16-bit PCM shingle 指纹与裁剪包含度评分。真实全库候选清单将在 RWC 下载、校验和盘点完成后生成。

- [ ] **步骤 3：冻结四份清单**

建议比例为 train 70%、calibration 10%、validation 10%、test 10%，按作品组和质量分布约束划分。测试清单的标签统计可生成，但训练代码不得读取测试音频。

- [ ] **步骤 4：验证确定性和隔离性**

相同 manifest/policy/seed 必须生成逐字节相同清单；任意 group 不得跨集；测试集权限或路径配置与训练进程隔离。

- [ ] **步骤 5：提交**

提交消息：`test: freeze leakage-resistant chord splits`

### 任务 5：建立统一评测器并冻结 legacy 基线

**文件：**

- 新建：`ml/src/museecho_ml/evaluation/metrics.py`
- 新建：`ml/src/museecho_ml/evaluation/report.py`
- 新建：`ml/src/museecho_ml/evaluation/legacy_adapter.py`
- 新建：`ml/tests/evaluation/test_metrics.py`
- 新建：`ml/configs/evaluation-v1.json`
- 生成：`docs/ml/experiments/legacy-baseline-v1.json`
- 生成：`docs/ml/experiments/legacy-baseline-v1.md`

**接口：** 相同预测 JSONL 和 reference JSONL 输入必须生成可重放的 WCSR、F1、边界、校准和分层报告。

- [x] **步骤 1：用手算小例子固定指标**

覆盖完全正确、根音错误、性质错误、边界偏移、`N/X`、忽略区间和不等长片段，避免指标库使用方式错误。

已用时长不等的对齐区间固定 root/maj-min/triads/sevenths/精确性质分数，并以一对一边界
匹配、按时长 Macro-F1、ECE 和 published precision/coverage 手算反例约束实现。`N/X` 的
完整报告口径仍随步骤 2 的统一报告器完成。

- [ ] **步骤 2：实现评测器**

报告 root、maj/min、triads、sevenths、精确首发词表、Macro-F1、边界 F1、过/欠分段、ECE 和 precision/coverage。

- [ ] **步骤 3：封装并运行 legacy**

只为评测封装当前识别器，不修改其阈值。记录运行环境、输入清单、算法版本和完整错误分层。

- [ ] **步骤 4：冻结 G2 基线**

提交基线报告和预测哈希，不提交测试音频。后续候选使用完全相同评测配置。

- [ ] **步骤 5：提交**

提交消息：`test: establish real-music chord baseline`

### 任务 6：实现可缓存且时间对齐的 CQT 特征

**文件：**

- 新建：`ml/src/museecho_ml/features/cqt.py`
- 新建：`ml/src/museecho_ml/features/cache.py`
- 新建：`ml/src/museecho_ml/features/augment.py`
- 新建：`ml/tests/features/test_cqt.py`
- 新建：`ml/configs/features-cqt-v1.json`

**接口：** `extract_features(audio, config) -> FeatureSequence`，包含主 CQT、bass CQT、帧时间和有效 mask；缓存 key 绑定音频、配置和代码版本哈希。

- [ ] **步骤 1：固定时间轴和分块失败测试**

覆盖短音频、5 分钟分块、不同采样率、尾块、重叠上下文、静音和非有限输入。

- [ ] **步骤 2：实现离线特征提取**

初始配置使用 22.05 kHz、至少 6 个八度、每半音多个 bin 和固定 hop。参数写入 JSON，不散落在代码中。

- [ ] **步骤 3：实现内容寻址缓存**

原子写入，损坏缓存自动拒绝并重算；缓存默认位于仓库外或 ignored 目录。

- [ ] **步骤 4：实现标签同步增强**

移调必须同时更新 root/bass；时间伸缩必须同步区间。每项增强有确定性种子、强度上限和可关闭消融开关。

- [ ] **步骤 5：运行长音频资源测试并提交**

提交消息：`feat: add aligned cqt training features`

### 任务 7：实现多任务 CRNN 和可验证损失

**文件：**

- 新建：`ml/src/museecho_ml/model/crnn.py`
- 新建：`ml/src/museecho_ml/model/loss.py`
- 新建：`ml/src/museecho_ml/model/batch.py`
- 新建：`ml/tests/model/test_crnn.py`
- 新建：`ml/configs/model-crnn-v1.json`

**接口：** 输入 `[batch, channel, frequency, time]` 和 mask；输出 root、quality、bass、boundary logits 及有限标量损失。

- [ ] **步骤 1：编写 shape、mask 和 NaN 测试**

覆盖不同长度 batch、全 `N`、全 `X`、无 bass 标签、稀有类别和空有效区间。

- [ ] **步骤 2：实现最小 CNN + BiGRU + 四 head**

网络规模、dropout、归一化和隐藏维度全部来自配置。不得把词表长度硬编码进 layer。

- [ ] **步骤 3：实现 masked multi-task loss**

类别权重只来自 train split 统计；所有 loss 分量分别记录，禁用 head 时权重必须显式为零。

- [ ] **步骤 4：小批次前后向验证**

检查梯度有限、参数确实更新、mask 帧不改变 loss。

- [ ] **步骤 5：提交**

提交消息：`feat: implement multitask chord crnn`

### 任务 8：实现可恢复、可复现的训练器

**文件：**

- 新建：`ml/src/museecho_ml/training/train.py`
- 新建：`ml/src/museecho_ml/training/checkpoint.py`
- 新建：`ml/src/museecho_ml/training/seed.py`
- 新建：`ml/src/museecho_ml/training/early_stop.py`
- 新建：`ml/tests/training/test_training_loop.py`
- 新建：`ml/configs/train-smoke.json`
- 新建：`ml/configs/train-crnn-v1.json`

**接口：** 单一命令读取不可变配置，完成训练、恢复、验证和制品索引；checkpoint 选择只依据 validation 主指标。

- [ ] **步骤 1：实现两首程序夹具 overfit 门**

训练器必须能在极小数据上把 root/quality loss 显著降低并达到预设准确率，否则不能启动昂贵训练。

- [ ] **步骤 2：实现 checkpoint 和精确恢复**

保存模型、优化器、scheduler、epoch、随机状态、配置和数据哈希；不匹配时拒绝恢复。

- [ ] **步骤 3：验证复现性**

相同 CPU 配置和种子运行两次，关键曲线和最终 checkpoint 参数在声明容差内一致。

- [ ] **步骤 4：增加 GPU 训练入口**

GPU 只加速同一训练语义。记录设备、CUDA、驱动和精度模式；CPU smoke 必须始终可运行。

- [ ] **步骤 5：通过 G3 并提交**

提交消息：`feat: add reproducible chord trainer`

### 任务 9：执行受控训练轮次和消融

**文件：**

- 新建：`ml/configs/experiments/r1-root-quality.json`
- 新建：`ml/configs/experiments/r2-multitask-augmentation.json`
- 新建：`ml/configs/experiments/r3-temporal-ablation.json`
- 生成：`docs/ml/experiments/EXPERIMENT_INDEX.md`
- 生成：`docs/ml/experiments/<run-id>.json`
- 生成：`docs/ml/experiments/<run-id>.md`

**接口：** 每一轮只改变声明的变量，使用相同 validation 协议；失败实验同样进入索引。

- [ ] **R0：数据/训练链 smoke**

在极小合法子集验证数据读取、特征、训练、评测和恢复，不报告为模型成绩。

- [ ] **R1：root + quality 深度基线**

禁用 bass/boundary 和随机增强，建立 CRNN 对 legacy 的首个可解释对比。

- [ ] **R2：完整多任务与增强**

启用 bass/boundary、类别权重和经过审计的增强；分别做无增强、无 boundary、无 bass 消融。

- [ ] **R3：时序编码对照**

只有 R2 已稳定但仍未达到 validation 门槛时，对比 BiGRU 与轻量 TCN/Conformer。保持输入、参数量级和训练预算可比。

- [ ] **候选冻结**

根据 validation 精确词表 WCSR、七和弦 Macro-F1、published precision/coverage 和性能共同选择一个候选。记录选择规则，不创建“挑最好测试集结果”的模型动物园。

- [ ] **一次 G4 正式测试**

冻结 checkpoint、阈值方案和 manifest 草案后，运行一次 test split。若根据该报告继续修改模型，该 test split 必须降级，重新建立测试集。

- [ ] **提交实验索引**

提交消息：`docs: record chord model experiments`

### 任务 10：校准概率并生成和弦事件

**文件：**

- 新建：`ml/src/museecho_ml/postprocess/calibration.py`
- 新建：`ml/src/museecho_ml/postprocess/decode.py`
- 新建：`ml/src/museecho_ml/postprocess/events.py`
- 新建：`ml/tests/postprocess/test_decode.py`
- 生成：`ml/configs/calibration-<model-version>.json`

**接口：** 帧级 logits + calibration manifest -> 完整、无重叠、版本化的事件；阈值只由 calibration split 选择。

- [ ] **步骤 1：编写不确定性和边界反例**

覆盖过度自信、root/quality 冲突、静音、短抖动、相邻同标签、低能量边缘和音频尾帧。

- [ ] **步骤 2：拟合温度与 published 阈值**

同时满足已知和弦 precision ≥ 0.85、coverage ≥ 0.65 和 ECE ≤ 0.08；参数写入 manifest，不硬编码。

- [ ] **步骤 3：实现受限时序解码**

禁止非法 root/quality/bass 组合；`X/N` 和低置信度映射产品 `unknown`；保留内部错误分析标签。

- [ ] **步骤 4：验证事件覆盖和确定性**

同一帧输出重复运行必须产生逐字节相同事件 JSON。

- [ ] **步骤 5：提交**

提交消息：`feat: calibrate and decode chord events`

### 任务 11：导出 ONNX 和绑定模型 manifest

**文件：**

- 新建：`ml/src/museecho_ml/export/onnx.py`
- 新建：`ml/src/museecho_ml/export/manifest.py`
- 新建：`ml/tests/export/test_onnx_parity.py`
- 生成：`models/chords/<version>/manifest.json`
- 发行制品：`models/chords/<version>/model.onnx`
- 新建：`docs/ml/MODEL_CARD.md`

**接口：** manifest 固定模型 SHA-256、输入输出、特征、词表、校准、指标、许可证和最小 runtime 版本。

- [ ] **步骤 1：先写 manifest 校验失败测试**

缺字段、哈希错误、未知词表、shape 不符、版本过长或模型被替换时拒绝加载。

- [ ] **步骤 2：导出动态时间轴 ONNX**

训练图与推理图分离，不包含 optimizer、augmentation 或数据路径。

- [ ] **步骤 3：运行数值和事件 parity**

PyTorch/ONNX 帧概率最大绝对误差 ≤ `1e-4`，最终事件完全一致；覆盖短块、长块和不同 batch。

- [ ] **步骤 4：编写真实模型卡**

记录数据范围、指标、失败类别、适用/不适用场景、伦理/版权边界、性能和哈希。未通过指标不得写为比赛候选。

- [ ] **步骤 5：提交小型 manifest 与文档**

ONNX 是否进入 Git 由体积和发行策略决定；无论存放方式如何都必须由哈希绑定。

提交消息：`build: export versioned chord onnx model`

### 任务 12：接入可回退的产品识别器

**文件：**

- 新建：`src/museecho/analysis/chord_recognizer.py`
- 新建：`src/museecho/analysis/chord_legacy.py`
- 新建：`src/museecho/analysis/chord_onnx.py`
- 修改：`src/museecho/analysis/chords.py`
- 修改：`src/museecho/application/coordinator.py`
- 修改：`pyproject.toml`
- 修改：`uv.lock`
- 新建：`tests/unit/analysis/test_chord_recognizer.py`
- 新建：`tests/integration/test_chord_model_loading.py`

**接口：** `ChordRecognizer.recognize(samples, sample_rate, context) -> tuple[ChordEvent, ...]`；实现明确暴露 `algorithm_version` 和加载健康状态。

- [ ] **步骤 1：以失败测试固定依赖反转**

Coordinator 只依赖 recognizer 接口；legacy 与 ONNX 对相同事件 DTO 负责。主运行时不得导入训练包或 PyTorch。

- [ ] **步骤 2：封装 legacy，不改变结果**

现有和弦单测必须逐事件保持兼容，算法版本仍为 `chroma-triad-viterbi-v1`。

- [ ] **步骤 3：实现 ONNX 加载和分块推理**

启动时校验 manifest/SHA/词表/特征；块边界重叠裁剪后时间轴连续。

- [ ] **步骤 4：实现稳定回退**

模型缺失、哈希错误、ONNX 加载失败和受控资源错误使用 legacy；日志只记录稳定错误码和版本，不记录音频或用户路径。

- [ ] **步骤 5：增加配置和健康信息**

默认模型只有在 G5 前置条件通过后才切换；健康端点只报告可用性和版本，不泄漏绝对敏感路径。

- [ ] **步骤 6：提交**

提交消息：`feat: integrate fallback chord recognizers`

### 任务 13：扩展产品和弦契约和确定性乐理

**文件：**

- 修改：`src/museecho/theory/chords.py`
- 修改：`src/museecho/theory/functions.py`
- 修改：`src/museecho/application/evidence.py`
- 修改：`src/museecho/domain/models.py`
- 修改：`src/museecho/infrastructure/repositories.py`
- 可能新建：`migrations/versions/<revision>_expand_chord_contract.py`
- 修改：`frontend/src/api/client.ts`
- 修改：`frontend/src/api/types.ts`
- 修改：`frontend/src/features/chords/ChordDetails.tsx`
- 修改：对应 Python、TypeScript 与 repository 测试

**接口：** API 可安全传递首发新词表；理论对象支持可变数量组成音和转位；旧三和弦结果继续可读。

- [ ] **步骤 1：先写端到端契约 RED 测试**

至少覆盖 `C7`、`Cmaj7/E`、`Bm7b5`、`Dsus4`、`unknown` 和畸形标签，从 parser 到 API client 全链验证。

- [ ] **步骤 2：扩展确定性 parser 和理论 DTO**

理论输出不得继续假设恰好三个 pitch classes；对无法唯一确定的功能返回限制，不猜测。

- [ ] **步骤 3：扩展 Evidence 白名单**

只有达到 chord 置信门并通过新 parser 的标签可进入 Evidence；`N/X/unknown` 和不完整理论仍拒绝。

- [ ] **步骤 4：迁移存储并保留旧数据**

先验证 `String(20)` 是否覆盖所有规范 symbol；只有实际需要时迁移。迁移必须支持升级、回滚或明确不可逆边界，不能删除旧事件。

- [ ] **步骤 5：扩展前端显示与无障碍文案**

移除仅接受 `m?` 的正则，改为共享规范；详情显示实际组成音、性质、低音/转位和置信状态。

- [ ] **步骤 6：提交**

提交消息：`feat: support extended chord theory contracts`

### 任务 14：完成性能、E2E、发行与审计

**文件：**

- 修改：`scripts/benchmark.py`
- 修改：`tests/performance/test_five_minute_budget.py`
- 修改：`e2e/museecho.spec.ts`
- 修改：`Dockerfile`
- 修改：`compose.yaml`
- 修改：`THIRD_PARTY_NOTICES.md`
- 修改：`README.md`
- 生成：`docs/ml/chord-v2-evaluation.md`
- 生成：`docs/ml/chord-v2-performance.json`
- 生成：`docs/ml/chord-v2-release-audit.md`

- [ ] **步骤 1：运行 ML 全套验证**

运行训练包单测、数据清单/切分审计、候选评测、ONNX parity 和模型 manifest 校验。

- [ ] **步骤 2：运行产品回归**

运行后端、前端、类型检查、生产构建和真实 HTTPS E2E。E2E 覆盖新和弦、unknown 和 legacy 回退，不能只 mock 模型结果。

- [ ] **步骤 3：执行 2 vCPU/4 GB 基准**

记录 5 分钟和弦阶段与完整分析墙钟、CPU、峰值 RSS、冷启动和模型大小。和弦阶段 ≤ 30 秒、RSS ≤ 2 GB；完整分析 ≤ 90 秒、RSS ≤ 4 GB。

- [ ] **步骤 4：检查容器和发行制品**

生产镜像不含 PyTorch、训练数据、checkpoint、缓存或绝对本地路径；ONNX 与 manifest 哈希一致，离线启动不访问网络。

- [ ] **步骤 5：完成许可证、安全和隐私审计**

更新第三方通知，扫描模型/文档/日志/构建上下文；确认用户上传不会进入训练或第三方服务。

- [ ] **步骤 6：生成最终真实对比报告**

同时列出 legacy 与候选的统一测试成绩、各类别弱点、失败实验、性能和未支持词表。不得只选择成功歌曲截图。

- [ ] **步骤 7：通过 G5 后再切换默认模型**

默认切换必须是单独、可回退、可审查的提交。任何门槛未通过时保持 legacy 默认并报告未完成项。

- [ ] **步骤 8：提交和 PR**

提交消息：`feat: deliver deep chord recognition candidate`

## 推荐执行节奏

在数据可合法取得且具备训练 GPU 的前提下，建议使用 6 周：

1. 第 1 周：任务 1–5，完成词表、数据、切分、评测和真实 legacy 基线；
2. 第 2 周：任务 6–8，完成特征、模型和可信训练链；
3. 第 3–4 周：任务 9–10，执行受控训练、消融、校准和候选冻结；
4. 第 5 周：任务 11–13，ONNX 导出、产品接入和完整词表升级；
5. 第 6 周：任务 14，性能、E2E、发行审计、比赛报告和默认切换决定。

训练数据不足、许可未明确或 G1/G3/G4 门禁失败时，时间顺延；不得通过跳过测试、重复窥视 test split 或降低 unknown 门槛伪造进度。

## 最终交付物

- 经批准的 SPEC 与本 PLAN；
- 独立可复现的 `ml/` 训练工程和锁文件；
- 数据卡、数据清单哈希、切分审计和许可记录；
- legacy 基线、全部正式实验索引及候选测试报告；
- 带 SHA-256 manifest 的 ONNX 模型和模型卡；
- 可回退的产品识别器、新词表乐理/API/UI；
- 2 vCPU/4 GB 性能、真实 E2E、容器、许可证、安全和隐私证据；
- 清楚记录的已知限制、失败类别与下一阶段方向。
