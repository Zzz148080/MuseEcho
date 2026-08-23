# BTC-170 和弦识别研究候选模型卡

## 结论

BTC-170 在冻结的 real-gold validation 上得到 `continue-btc-research`。这表示它值得继续
作为独立研究候选，不表示产品晋升、发布批准或默认算法切换。MuseEcho 产品默认算法仍为
`chroma-triad-viterbi-v1`，本实验没有修改产品运行时。

本次比较共覆盖 39 首、3969.142403628118 秒音频：GuitarSet 24 首、RWC Popular 11 首、
Schubert Winterreise 4 首。BTC-170 的整体 exact-quality WCSR、root WCSR 和 boundary F1
均显著高于 legacy；但它在 GuitarSet 上的 exact 与 root 明显低于 legacy，说明当前结果仍有
清晰的域泛化风险。

## 候选来源与身份

- 上游：`jayg996/BTC-ISMIR19`，官方文件 `test/btc_model_large_voca.pt`。
- 文件大小：12,229,576 bytes。
- Git blob SHA-1：`11c6edbaaaee33737aa7a41dcb9044191630326f`。
- 文件 SHA-256：`1673d23f8f9a55ae7f9e8b80a51da616debb22675b8d8b67ea6ce0ef37b0ab51`。
- checkpoint tensor contract SHA-256：
  `c0da39af39ed831e90fe635e9bb3a5112591f705dc0980505fb2451368cd6809`。
- artifact lock SHA-256：
  `de9b3ece8da2c1a0ef8c53885adb11487ba974dcff95b9606edd8e6d74f4cfee`。
- 安全加载：只允许 `torch.load(..., weights_only=True)`；模型参数必须
  `load_state_dict(..., strict=True)`，本实验的安全加载与制品身份门禁均通过。

权重只保存在 Git 忽略的本地研究缓存中，不随源码或发行物分发。上游源码标注 MIT 许可，
但这不能单独证明权重训练数据来源和权重再分发权；在独立完成该审计前，权重只能用于本地
研究验证，不能进入产品运行时或对外分发。

## 评测边界

评测只读取冻结的 `real-gold` / `validation` manifest；39 首曲目的身份、时长和分组对两个
候选完全一致。Plan C 的 test manifest 与 test prediction 继续永久封存：本实验没有读取、
枚举、重放或重新授权任何 test 制品。validation 已用于选择继续研究的方向，因此这些结果
不是最终无偏测试，也不能用于 promotion。

BTC-170 支持 `maj`、`min`、`7`、`maj7`、`min7`、`dim`、`hdim7`、`sus2` 和 `sus4`。
`aug`、`min6`、`maj6`、`minmaj7` 和 `dim7` 严格映射为 `X`。模型没有 bass head；为了与
现有输出结构兼容，已知和弦统一写为 `bass="1"`。因此本实验没有评估转位或低音识别能力，
不能把兼容字段解释为 bass 预测正确。

## 整体结果

下表保留正式报告中的未舍入门禁数值：

| 候选 | Exact WCSR | Root WCSR | Boundary F1 | 预测/参考事件比 |
| --- | ---: | ---: | ---: | ---: |
| BTC-170 | 0.509887025080584 | 0.6681232039749315 | 0.21172319153107233 | 1.3702517162471395 |
| Legacy | 0.15776271037617706 | 0.15789141299007192 | 0.0009225092250922509 | 0.027917620137299773 |

BTC 相对 legacy 的 exact、root 和 boundary F1 增量分别为
`0.35212431470440697`、`0.5102317909848596` 和 `0.2108006823059801`。
BTC 共输出 2,994 个事件，参考为 2,185 个；legacy 仅输出 61 个事件。BTC 的事件密度更接近
参考，但高于参考约 37%，仍需继续处理边界碎片化。

BTC 的 quality Macro-F1 为 `0.3664354727872798`，published coverage 为
`0.22345256263959454`，published-known precision 为 `0.7640917815492029`。映射为 `X`
的 BTC 预测累计 `35.18518518518522` 秒；legacy 对应记录为 0 秒。

最大 softmax 置信度未经校准，只能用于诊断。ECE `0.19559118124634958` 不参与继续研究门禁，
也不能直接用作产品置信阈值。

## 分数据集结果

| Validation 数据集 | 候选 | Exact WCSR | Root WCSR | Boundary F1 |
| --- | --- | ---: | ---: | ---: |
| GuitarSet | BTC-170 | 0.19126764240375851 | 0.2781188109632613 | 0.07083333333333335 |
| GuitarSet | Legacy | 0.4399178307402314 | 0.4399178307402314 | 0.0 |
| RWC Popular | BTC-170 | 0.5788773759845042 | 0.7672915716309988 | 0.23335826477187732 |
| RWC Popular | Legacy | 0.08125892540824058 | 0.08143324730935456 | 0.0 |
| Schubert Winterreise | BTC-170 | 0.4602615445747252 | 0.5172712342269709 | 0.18032786885245902 |
| Schubert Winterreise | Legacy | 0.29602774274905397 | 0.29602774274905397 | 0.006349206349206349 |

BTC 在三个数据集中赢得两个 exact 比较，满足预注册门禁；GuitarSet 的回退表明继续研究应
优先检查训练域差异、独奏/伴奏条件和按数据集路由，而不能只依赖整体平均分。

## 配对不确定性

不确定性按 15 个 `cover_group_id` 整组配对重采样，使用 PCG64 seed `20260823`，共
10,000 次。BTC 减 legacy 的 95% bootstrap 区间为：

| 增量指标 | 点估计 | 95% 区间 |
| --- | ---: | ---: |
| Exact WCSR | 0.3521243147044076 | [0.1772572125916181, 0.5100121287420091] |
| Root WCSR | 0.5102317909848606 | [0.3187937832134127, 0.6742806467776908] |
| Boundary F1 | 0.2108006823059801 | [0.16718265596746704, 0.25117782456734106] |

三个区间均高于 0，但样本只有 15 个独立 cover group，且 validation 已参与研究决策；这仍
不足以替代新的冻结测试。

## 运行资源与复现

| 候选 | CPU 秒 | Wall 秒 | 五分钟 CPU 秒 | 五分钟 Wall 秒 | Wall 实时因子 |
| --- | ---: | ---: | ---: | ---: | ---: |
| BTC-170 | 24.125 | 24.874597300193273 | 1.823441757439677 | 1.880098628670204 | 0.00626699542890068 |
| Legacy | 14.171875 | 14.418246599962004 | 1.0711539339363907 | 1.089775457800347 | 0.0036325848593344893 |

进程峰值 RSS 为 681,422,848 bytes（649.85546875 MiB）。正式推理双跑的事件级摘要一致，
离线 replay 也精确重建了报告与决策。正式制品身份为：

- validation manifest SHA-256：
  `4e0522bcc9b0765ac8fdd7f2728994edecdf186e63ff2238af2854afd94c4106`
- path-free predictions SHA-256：
  `0b44e1a3bedef6c6ceed5af55a6f753d6de9fa3a7e2b188654cc06fea2a7697d`
- validation report canonical SHA-256：
  `35089aabd6c98197688739bc3adda28d5594780458328820df632728fd5e7a77`
- decision canonical SHA-256：
  `1c4f433ad0eef551767bcd8a19282a423fd09fb6cf80a4f883a36687dfacc4c1`

## 决策门禁与后续含义

八项预注册门禁全部通过：制品身份、安全 checkpoint 加载、至少两个数据集 exact 胜出、
整体 exact 高于 0.166596、root 不低于 legacy、boundary 不低于 legacy、确定性预测重放、
CPU 基准完成。决策没有失败谓词，且 `product_default_changed=false`。

`continue-btc-research` 的合理下一步是保持候选隔离，针对 GuitarSet 域退化、事件过分割、
置信度校准和许可来源继续实验。只有在方案再次冻结并建立新的、从未参与选择的 test v2 后，
才可能讨论 promotion；在此之前默认算法必须保持不变。

## 冻结证据

- `docs/ml/btc-170/validation-report-v1.json`
- `docs/ml/btc-170/decision-v1.json`
- `docs/ml/btc-170/comparison-v1.md`
