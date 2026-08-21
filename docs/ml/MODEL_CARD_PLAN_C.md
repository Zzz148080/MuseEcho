# MuseEcho Plan C chord model card

Status: research comparison completed; frozen test consumed exactly once; promotion rejected.
The product default remains `chroma-triad-viterbi-v1`.

## Intended use

Plan C compares a real-gold-only course (C0) with approved synthetic auxiliary pretraining plus
the same real-gold finetune (C1). It is intended for a bounded, non-commercial competition
research comparison on GuitarSet, RWC Popular Music, and Schubert Winterreise. C2 is skipped
because no `real-score-supervised` manifest has passed a separate feasibility and license review.

This protocol is not evidence of general production readiness, universal genre coverage, or
permission to distribute combined model weights.

## Data ceiling and gates

- G1a: `passed`; the real-gold manifests, cover/work groups, four-way split, and near-duplicate
  audit are frozen and internally consistent.
- G1b: `not-met`; 124 independent works, 32,186.891633 annotated seconds (8.940803 hours), and
  17,795 intervals are below the 500-work/80-hour target.
- Auxiliary synthetic supervision: 41.487981 usable hours from IDMT-SMT-Chord-Sequences and
  Jazznet. These data are train-only and cannot enter calibration, validation, or test.
- RWC-P and Winterreise weight-distribution permission is unresolved, so promotion is blocked
  unless separate evidence changes the registry.

## Frozen vocabulary

Published qualities are `maj`, `min`, `7`, `maj7`, `min7`, `dim`, `hdim7`, and `sus4`, with
internal `N` and `X`. The vocabulary is derived only from real-gold train cover-group counts at a
20-group minimum. `sus2` has insufficient support and maps deterministically to `X`; validation
and test cannot expand the vocabulary.

## Comparison protocol

Each ready course uses seeds `20260821`, `20260822`, and `20260823` with identical real-gold
finetune, calibration, validation, and test identities. Course selection uses unrounded
three-seed medians and deterministic lexicographic ranking. Uncertainty uses 10,000 whole-cover-
group bootstrap resamples with PCG64 seed `20260821`; dataset macro gives GuitarSet, RWC-P, and
Winterreise equal weight.

The test was authorized only after protocol, vocabulary, calibration, threshold, course, seed,
and checkpoint identities were frozen. C1 won the validation-only course comparison and seed
`20260821` was the closest-to-median selected run. Selection SHA-256 is
`5bb7ad3bc46e251756ac7f9e8c1de1a2280976912a3cc9a1fd17dc664f2bf262`.

## Measured results

The six formal runs all completed. C0's median validation exact-vocabulary WCSR was 0.116977;
C1's was 0.136838. The selected C1 seed had validation exact WCSR 0.136838, public-quality
Macro-F1 0.042597, known precision 0.029095, and coverage 0.293014. Its grouped-bootstrap exact
WCSR 95% interval was [0.072317, 0.210590]. Quality support remained incomplete in individual
dataset strata, so the strict dataset macro was unavailable.

The one-use frozen-test comparison produced:

| Metric | Plan C candidate | Frozen legacy |
| --- | ---: | ---: |
| Exact-vocabulary WCSR | 0.171727 | 0.211910 |
| Maj/min WCSR | 0.002261 | 0.006626 |
| Published-known precision | 0.005218 | 0.799263 |
| Coverage | 0.246738 | 0.006209 |
| ECE | 0.072034 | 0.207795 |
| Seventh-quality Macro-F1 | 0.003324 | 0.000000 |

The candidate exact-WCSR grouped-bootstrap 95% interval was [0.074549, 0.273325]. Test
exact-vocabulary WCSR by dataset was 0.463712 on GuitarSet, 0.053552 on RWC-P, and 0.113449 on
Winterreise; GuitarSet's large `X` share makes its exact score non-representative of known-chord
quality. The candidate did not exceed the unchanged legacy recognizer on exact or maj/min WCSR.

## Promotion and fallback

Plan C experiment completion does not imply product promotion. The candidate passed ECE,
deterministic-event, five-minute chord wall-time (2.959743 seconds), and measured process peak
working-set (862,597,120 bytes) checks. It failed the exact/maj-min comparison, seventh-quality,
known-precision, and coverage gates. ONNX parity and full-analysis resource evidence were not run
and were recorded as conservative failures. RWC-P and Winterreise weight-distribution permission
also remains unresolved. The strong-result target was not met; promotion status is `rejected`.

## Frozen evidence

- `docs/ml/plan-c/g1-status-v1.json`
- `docs/ml/plan-c/vocabulary-v1.json`
- `docs/ml/plan-c/protocol-v1.json`
- `docs/ml/plan-c/selection-v1.json`
- `docs/ml/plan-c/test-receipt-v1.json`
- `docs/ml/plan-c/promotion-v1.json`
- `docs/ml/experiments/plan-c-C0-seed-*.json`
- `docs/ml/experiments/plan-c-C1-seed-*.json`
- `docs/ml/experiments/plan-c-frozen-test-v1.json`
- `docs/ml/split-audit-v1.json`

The consumed receipt binds the selected checkpoint, calibration, threshold, vocabulary, test
manifest, and both candidate/legacy report hashes. A second authorization or evaluation attempt
is rejected by both the persisted access marker and the consumed public receipt.
