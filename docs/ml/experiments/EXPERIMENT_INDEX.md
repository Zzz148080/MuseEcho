# Chord model experiment index

This index records successful, failed, skipped, and blocked experiments. Validation diagnostics from
training-chain gates are never presented as model or competition scores.

| ID | Stage | Status | Source SHA | Model score? | Evidence | Outcome |
| --- | --- | --- | --- | --- | --- | --- |
| `legacy-baseline-v1` | G2 | frozen | `e354f72` | yes, unified baseline | [JSON](legacy-baseline-v1.json), [Markdown](legacy-baseline-v1.md) | Frozen legacy validation/test baseline for later comparison. |
| `g3-training-reproducibility-v1` | G3 | passed | `2fcbdb2` | no | [JSON](g3-training-reproducibility-v1.json), [Markdown](g3-training-reproducibility-v1.md) | Tiny real-gold overfit, deterministic CPU reproduction, and checkpoint restore passed. |
| `r0-pipeline-smoke-v1` | R0 | passed | `72cc490` | no | [JSON](r0-pipeline-smoke-v1.json), [Markdown](r0-pipeline-smoke-v1.md) | Real data-to-feature-to-train-to-validation pipeline and exact CPU resume passed. |
| `b0-synthetic-pretrain` | B0 | skipped | `72cc490` | no | route decision in R0 evidence | Route A is frozen; 41.487981 synthetic-supervised hours are below the 60-hour Route B threshold. |
| `r1-root-quality` | R1 | superseded | — | no | historical G1 state in R0 evidence | Original production-scale route was replaced by the approved data-capped Plan C protocol. |
| `r2-multitask-augmentation` | R2 | superseded | — | no | historical G1 state in R0 evidence | Original production-scale route was replaced by the approved data-capped Plan C protocol. |
| `r3-temporal-ablation` | R3 | not started | — | no | conditional plan item | Runs only if a valid R2 stabilizes but misses its validation gate. |
| `plan-c-c0` | C0 | completed | `25b9d48` | validation only | [seed 20260821](plan-c-C0-seed-20260821.json), [20260822](plan-c-C0-seed-20260822.json), [20260823](plan-c-C0-seed-20260823.json) | Three formal real-gold-only runs completed. Median exact WCSR: 0.116977; median known precision: 0.017113. |
| `plan-c-c1` | C1 | completed | `25b9d48` | validation only | [seed 20260821](plan-c-C1-seed-20260821.json), [20260822](plan-c-C1-seed-20260822.json), [20260823](plan-c-C1-seed-20260823.json) | Three formal synthetic-pretrain plus real-gold-finetune runs completed. Median exact WCSR: 0.136838; median known precision: 0.017093. |
| `plan-c-c2` | C2 | skipped | `f9e2c39` | no | [JSON](plan-c-C2-seed-20260821.json), [protocol](../plan-c/protocol-v1.json) | Structured skip: `score-supervision-not-approved`. |
| `plan-c-validation-selection` | selection | frozen | `25b9d48` | validation only | [selection](../plan-c/selection-v1.json) | C1 seed 20260821 selected by the frozen median/ranking rule; selection SHA `5bb7ad3b…`. |
| `plan-c-frozen-test` | test | consumed | `25b9d48` | yes | [comparison](plan-c-frozen-test-v1.json), [receipt](../plan-c/test-receipt-v1.json) | Candidate exact WCSR 0.171727 versus legacy 0.211910; candidate did not exceed legacy. |
| `plan-c-promotion` | promotion | rejected | `25b9d48` | decision | [promotion](../plan-c/promotion-v1.json) | Accuracy, seventh, precision, coverage, ONNX/full-analysis, and RWC-P/Winterreise distribution gates failed or were unavailable; legacy remains default. |

Plan C completed as an honest bounded research comparison, not a successful replacement model.
The single frozen-test receipt is consumed, the strong-result target is not met, and the product
default remains `chroma-triad-viterbi-v1`.
