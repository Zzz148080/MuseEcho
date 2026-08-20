# Chord model experiment index

This index records successful, failed, skipped, and blocked experiments. Validation diagnostics from
training-chain gates are never presented as model or competition scores.

| ID | Stage | Status | Source SHA | Model score? | Evidence | Outcome |
| --- | --- | --- | --- | --- | --- | --- |
| `legacy-baseline-v1` | G2 | frozen | `e354f72` | yes, unified baseline | [JSON](legacy-baseline-v1.json), [Markdown](legacy-baseline-v1.md) | Frozen legacy validation/test baseline for later comparison. |
| `g3-training-reproducibility-v1` | G3 | passed | `2fcbdb2` | no | [JSON](g3-training-reproducibility-v1.json), [Markdown](g3-training-reproducibility-v1.md) | Tiny real-gold overfit, deterministic CPU reproduction, and checkpoint restore passed. |
| `r0-pipeline-smoke-v1` | R0 | passed | `72cc490` | no | [JSON](r0-pipeline-smoke-v1.json), [Markdown](r0-pipeline-smoke-v1.md) | Real data-to-feature-to-train-to-validation pipeline and exact CPU resume passed. |
| `b0-synthetic-pretrain` | B0 | skipped | `72cc490` | no | route decision in R0 evidence | Route A is frozen; 41.487981 synthetic-supervised hours are below the 60-hour Route B threshold. |
| `r1-root-quality` | R1 | blocked | — | no | G1 state in R0 evidence | Not started: G1 is `NOT READY` and this machine has no CUDA runtime. |
| `r2-multitask-augmentation` | R2 | blocked | — | no | G1 state in R0 evidence | Not started: G1 is `NOT READY` and this machine has no CUDA runtime. |
| `r3-temporal-ablation` | R3 | not started | — | no | conditional plan item | Runs only if a valid R2 stabilizes but misses its validation gate. |

No G4 candidate has been frozen and no new formal test-split evaluation has been run.
