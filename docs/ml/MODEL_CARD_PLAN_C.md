# MuseEcho Plan C chord model card

Status: research protocol frozen; C0/C1 experiments not yet completed; frozen test not consumed;
promotion not evaluated. The product default remains `chroma-triad-viterbi-v1`.

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

The test may be authorized and consumed once only after protocol, vocabulary, calibration,
threshold, course, seed, and checkpoint identities are frozen. No test metric is present in this
card because that access has not occurred.

## Promotion and fallback

Plan C experiment completion does not imply product promotion. Promotion additionally requires
all frozen accuracy, calibration, determinism, ONNX parity, CPU/RSS, and per-training-dataset
weight-distribution checks to pass. An exact-vocabulary WCSR improvement of at least 0.08 is
recorded as a strong-result target but is not a completion gate. Any failed or unavailable check
keeps `chroma-triad-viterbi-v1` as the default.

## Frozen evidence

- `docs/ml/plan-c/g1-status-v1.json`
- `docs/ml/plan-c/vocabulary-v1.json`
- `docs/ml/plan-c/protocol-v1.json`
- `docs/ml/split-audit-v1.json`

Selection, one-use test receipt, promotion decision, confidence intervals, and measured
dataset-stratum results will be added only after the corresponding protocol steps actually run.
