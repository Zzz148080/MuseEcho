# Plan D 混合和弦识别开发模型卡

## 结论

Plan D 的最终开发状态为 `data-first-required`。三组随机种子的混合回放没有超过
legacy：exact vocabulary WCSR 均为 0.166596，与 legacy 完全相同；混合覆盖率只有
0.001708，事件数比例只有 0.027214。该结果不支持继续重训或替换线上算法。

产品默认算法保持 `chroma-triad-viterbi-v1`。Plan D 不是发布候选，也没有执行 promotion。

## 任务与设计边界

Plan D 研究一种确定性混合识别器：legacy 提供根音和初始边界，神经网络只在独立校准
达到精度优先阈值时修正 quality 与 bass。低置信度结果回退到 legacy，bass 只能取当前
和弦的合法和弦音或已批准转位音。

所有开发只使用 train、calibration 和 validation。Plan D 不重新使用 Plan C test；旧
test manifest 的 SHA-256
`06b92ce1bd46a1c432cefb9fe32f641095cfb081ac998e7772a66c20a686cddc`
继续永久封存，既有 receipt 保持 `consumed`，既有 promotion 保持 `rejected`。

## 数据上限

- real-gold 上限：124 个独立作品、8.940803 小时有效标注、17,795 个和弦区间。
- synthetic-supervised：41.487981 小时，只允许用于训练，不用于 calibration、validation
  或测试，也不能增加独立真实作品数。
- 开发数据来自 GuitarSet、RWC Popular Music Database 和 Schubert Winterreise；按
  `cover_group_id` 隔离，避免同作品跨 split 泄漏。
- 数据规模和类别覆盖仍是主要限制。特别是稀有 quality、真实演奏域和跨数据集变化不足，
  不能把合成时长解释成真实监督规模。

## Stage 0 失败审计

Stage 0 状态为 `completed`，development split、manifest、track、reference、frame grid、
vocabulary、legacy algorithm 和三个 seed 的身份检查全部通过。最大边界到帧网格误差为
0.0116077098 秒，没有发现足以解释低分的标签映射、时间对齐或指标实现缺陷。

审计同时确认深度模型存在明显 seed/domain 失稳：三个 seed 的预测事件比例分别为
3.856089、1.208487 和 0.098247，预测行为从过度碎片化跨越到严重欠预测。因此后续问题
被判断为数据与泛化问题，而不是可以通过修正审计缺陷消除的问题。

公开审计证据：

- `plan-d-stage-0-audit.json` 的 experiment SHA-256：
  `c0452fc7538cd5c4831f83a2d7ccfc415ec08ca4256cdd7cc3433252071896f2`
- `audit-v1.json` 的 audit SHA-256：
  `b6c727c321565d2783fc8c940453167828612012865d9d5867c9865560f8ab55`

## D1 三 seed validation replay

| Seed | Deep-only exact WCSR | Hybrid exact WCSR | Hybrid known precision | Hybrid coverage | Hybrid event ratio | 五分钟 CPU 秒 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 20260821 | 0.136838 | 0.166596 | 0.623288 | 0.001708 | 0.027214 | 3.368051 |
| 20260822 | 0.144668 | 0.166596 | 0.623288 | 0.001708 | 0.027214 | 3.011914 |
| 20260823 | 0.021385 | 0.166596 | 0.623288 | 0.001708 | 0.027214 | 2.894348 |

legacy exact WCSR 为 0.166596，known precision 为 0.623288，coverage 为 0.001708，事件数
比例为 0.028137。三个 seed 的 hybrid 结果都与 legacy exact、precision 和 coverage 相同，
只把事件数比例进一步降至 0.027214；因此没有 hybrid 增益。最大五分钟 CPU 时间为
3.368051 秒，CPU 门禁通过，但不能弥补准确率和覆盖率失败。

按数据集看，hybrid 与 legacy 同样没有差异：

| Validation 数据集 | Hybrid/legacy exact WCSR | Deep-only 三 seed 范围 |
| --- | ---: | ---: |
| GuitarSet | 0.454304 | 0.051297–0.410397 |
| RWC Popular | 0.090475 | 0.017714–0.082802 |
| Schubert Winterreise | 0.296028 | 0.008868–0.230287 |

hybrid 的最低 known precision 0.623288 达到精度门槛，CPU 和数据集回退检查也通过；但
minimum exact、相对 legacy 增益、相对 deep-only 增益、coverage 和 event ratio 均失败。
0.623288 的 precision 只发生在 0.1708% 的极低发布覆盖上，不能单独用于宣称模型有效。
deep-only exact 从 0.021385 到 0.144668，随机种子稳定性也不足。

公开 replay decision SHA-256：
`8f6022ca58e3ae343f17482a5bb9b3067dcd0e5b9e78b85f91c39e2c7f1584b0`。

## 结构化跳过与未完成项

D1 决策未达到 `advance-to-retraining`，所以 Tasks 8–10 按预注册分支结构化跳过：没有
实现或运行 Plan D 的 known/N/X 分层损失、effective-number 类别权重、均衡采样、
synthetic-only 域增强和 D2 三 seed 重训。相应地，Plan D 没有新的训练 checkpoint，也
没有 D2 checkpoint 精确恢复、全 N/X batch、两首小样本 overfit 或 CPU smoke 证据。
这些项目不是失败后被隐去，而是因为 `data-first-required` 明确禁止进入重训路径。

## 局限、适用范围与下一步

- 当前证据只支持研究诊断和离线回放，不支持产品替换。
- hybrid 的高 precision 伴随极低 coverage，绝大多数时间仍由 legacy 决定。
- 三个 deep-only seed 差异很大，说明现有真实监督不足以稳定训练。
- validation 已参与设计和门禁，不能充当最终无偏测试。
- 下一轮优先合法扩充到至少 30–50 小时/300 首独立 real-gold 作品，并改善各公开
  quality 的独立作品覆盖；长期目标仍为 80 小时/500 首。
- 数据与训练方案冻结后，必须建立新的冻结 test v2。没有 test v2，不得执行 promotion，
  也不得更改默认算法。

