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
| `plan-c-c0` | C0 | ready | `f9e2c39` | no | [protocol](../plan-c/protocol-v1.json) | Real-gold-only three-seed course is frozen; no formal run result recorded yet. |
| `plan-c-c1` | C1 | ready | `f9e2c39` | no | [protocol](../plan-c/protocol-v1.json) | IDMT/Jazznet pretraining plus identical real-gold finetune is frozen; no formal run result recorded yet. |
| `plan-c-c2` | C2 | skipped | `f9e2c39` | no | [protocol](../plan-c/protocol-v1.json) | Structured skip: `score-supervision-not-approved`. |
| `plan-c-validation-selection` | selection | not run | `f9e2c39` | no | [protocol](../plan-c/protocol-v1.json) | Requires completed C0/C1 validation reports for all three seeds. |
| `plan-c-frozen-test` | test | not consumed | `f9e2c39` | no | [protocol](../plan-c/protocol-v1.json) | Test identity is bound but remains unread until selection and every candidate identity are frozen. |

No Plan C candidate has been selected, no new formal test-split evaluation has been run, and no
promotion decision has been claimed. The product default remains `chroma-triad-viterbi-v1`.
