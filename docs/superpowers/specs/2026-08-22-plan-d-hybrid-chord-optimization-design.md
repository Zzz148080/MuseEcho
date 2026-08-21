# Plan D hybrid chord optimization design

Status: written design awaiting user review. The user approved the Plan D direction in chat on
2026-08-22. No implementation starts until this document is reviewed.

## Context

Plan C completed an honest three-seed comparison and consumed its frozen test exactly once. The
selected C1 model did not earn promotion. Its frozen-test exact-vocabulary WCSR was 0.171727
against 0.211910 for the unchanged legacy recognizer; maj/min WCSR was 0.002261 against 0.006626.
The candidate emitted 6,454 events for 1,723 reference events, published known chords with only
0.005218 precision at 0.246738 coverage, and learned almost no useful `min`, `min7`, `maj7`,
`dim`, or `hdim7` behavior. Three-seed validation results were also unstable.

The data ceiling remains the dominant external constraint: 124 independent real-gold works,
8.940803 annotated hours, and 17,795 intervals, plus 41.487981 hours of train-only synthetic
supervision. This is sufficient for bounded research, not for claiming production readiness.

Plan D therefore treats the Plan C outcome as diagnostic evidence. It does not reopen the Plan C
test or assume that a larger neural model will fix the result.

## Decision and alternatives

Plan D will use a **legacy-rooted hybrid recognizer** as the primary approach.

1. **Recommended: legacy-rooted hybrid.** Keep the deterministic chroma recognizer's root and
   initial segmentation, then allow a calibrated neural head to refine quality and bass only when
   it passes precision-first gates. Low-confidence output falls back to the legacy chord. This
   reduces the learning burden and makes every neural override measurable and reversible.
2. **Pure neural repair.** Improve loss weighting, decoding, and the current CRNN without a legacy
   prior. This remains an ablation, not the primary product path, because Plan C showed severe
   class collapse and seed instability.
3. **Data-first pause.** Acquire and annotate substantially more lawful real audio before changing
   the model. This is the correct fallback if the bounded hybrid and rebalanced-training stages do
   not pass their development gates. No new download or license acceptance is implied by this
   design.

Plan D deliberately excludes a large generative music model. Such a model is expensive, is not
designed for frame-aligned chord recognition, and would add distribution and reproducibility risk
before the current pipeline failures are understood.

## Non-negotiable invariants

- The consumed Plan C test manifest, raw test predictions, and access session are never opened by
  Plan D. The committed aggregate Plan C report may be cited as historical evidence only.
- Plan C protocol, vocabulary, selection, receipt, promotion decision, and experiment reports are
  immutable.
- Train fits model parameters. Calibration fits temperatures and publication thresholds.
  Validation selects Plan D variants. No other split may influence those choices.
- A Plan D model cannot be promoted from the existing test result. Promotion requires a new,
  independently grouped and legally approved frozen test v2.
- `chroma-triad-viterbi-v1` remains the product default until a future promotion gate passes.
- No external download, paid compute, license acceptance, model-weight distribution, or user audio
  reuse is authorized by this design.
- Raw audio, local paths, features, logits, checkpoints, and run logs stay under ignored paths.
  Public evidence is path-free, compact, hash-bound JSON.

## Stage 0: failure audit

Plan D first creates a reproducible development-only audit from train, calibration, and validation
artifacts. It must answer whether the dominant failure comes from labels, frame alignment,
calibration, segmentation, class collapse, domain shift, or seed instability before training is
changed.

The audit contains:

- frame-to-interval alignment probes at the first frame, final frame, and every annotation
  boundary, including resampling and hop-length rounding;
- augmentation invariants proving that transposition updates root and bass while time stretch
  updates all interval boundaries consistently;
- duration-weighted root, quality, bass, `N`, and `X` confusion matrices;
- reference/predicted event counts, event-duration histograms, boundary precision/recall, and
  over-segmentation ratios by dataset and cover group;
- confidence/accuracy and precision/coverage curves globally and per supported quality;
- class support and effective sample size by independent work, not just frame count;
- per-dataset and per-seed metrics with whole-cover-group bootstrap intervals;
- explicit checks for illegal chord combinations and label-normalization drift.

If a label, timing, or metric defect is found, it is fixed and re-audited before any architecture
experiment. The audit never reads the old test split.

## Stage 1: deterministic hybrid decoder

The first retained implementation adds a pure, replayable hybrid decoder. It consumes:

- legacy chord events with root, maj/min quality, boundaries, and confidence;
- calibrated neural frame probabilities for root, quality, bass, boundary, `N`, and `X`;
- a frozen Plan D decoder configuration and vocabulary.

Version 1 follows conservative rules:

1. Legacy event boundaries and root are authoritative.
2. Neural quality can replace the legacy maj/min quality only when the proposed quality is legal,
   its calibrated precision gate is satisfied, and supporting frames cover a configured fraction
   of the legacy event.
3. Neural bass is published only when it is a legal chord tone or an explicitly supported slash
   bass and passes its own confidence gate.
4. When the legacy recognizer returns unknown, the neural model may publish a known chord only if
   root, quality, energy, and event-support gates all pass; otherwise the output remains `X`.
5. Adjacent identical outputs are merged. Minimum duration and hysteresis are applied
   deterministically. The decoder may not create more events than its configured ratio relative
   to the legacy timeline.
6. A neural root override is disabled in version 1. It can become a separately measured ablation
   only after quality refinement is stable.

The decoder is side-effect free: identical legacy events, logits, calibration, vocabulary, and
configuration produce byte-identical events. Every override records a reason code, supporting
confidence, and fallback source in ignored diagnostic output.

## Stage 2: precision-first calibration and decoding

Plan D separates three decisions that Plan C combined too aggressively:

- known-versus-`N/X` publication;
- quality selection conditional on a trusted root;
- boundary acceptance and event merging.

Calibration starts with global temperatures and thresholds. A per-quality threshold is permitted
only when calibration contains enough independent cover groups for that quality; otherwise it
must fall back to the global threshold. Threshold selection is precision-first, then coverage,
then exact WCSR. Validation, never calibration, decides whether a threshold scheme advances.

The boundary path uses hysteresis, a minimum event duration, and an event-count ratio guard. A
neural boundary cannot split a legacy event in the primary variant; neural splitting remains an
ablation and must prove a boundary-F1 gain without over-segmentation.

## Stage 3: rebalanced neural training

Only after the replayable hybrid baseline is frozen does Plan D retrain the neural component.
The existing root, quality, bass, and boundary heads remain to preserve checkpoint and evaluation
interfaces. Changes are bounded to:

- a hierarchical known/`N/X` gate before known-quality publication;
- clipped effective-number class weights computed from train groups only;
- duration-aware, dataset-balanced, and quality-balanced sampling without duplicating evaluation
  groups;
- synthetic-domain randomization using deterministic EQ, compression, noise, reverb, and
  instrument mixing already lawful for train-only data;
- gradual encoder unfreezing during real-gold finetuning;
- loss and sampling artifacts that serialize every weight and class count.

Three seeds remain mandatory. A larger TCN or Conformer encoder is not introduced unless the
hybrid decoder plus rebalanced current encoder fails for a diagnosed representation reason. Model
size is not used as a substitute for data.

## Data flow and artifact identities

Plan D creates a versioned protocol that binds the Plan C train/calibration/validation manifest
hashes, vocabulary, legacy algorithm version, checkpoint lineage, calibration method, decoder
configuration, seed list, and code identity.

Development flow:

1. Reproduce legacy and C1 predictions on train/calibration/validation only.
2. Generate the Stage 0 audit and freeze its hash.
3. Replay legacy, deep-only, and hybrid variants from the same validation identities.
4. Fit calibration using calibration groups only.
5. Rank variants by the predeclared validation gates and whole-group bootstrap results.
6. Retrain three seeds only for variants that survive the replay gate.
7. Freeze a Plan D development candidate or record an honest stop decision.
8. Wait for new lawful data and a new frozen test v2 before any promotion claim.

A dedicated Plan D development-manifest loader rejects `split: test`, the Plan C test manifest
hash, and any attempt to construct a `FrozenTestSession`. This failure is tested explicitly.

## Development gates

These gates decide whether Plan D continues; they do not authorize production promotion.

The primary hybrid variant must satisfy all of the following on validation:

- median exact-vocabulary WCSR across three seeds is at least 0.30 and at least 0.03 absolute above
  both the unchanged legacy validation result and the corresponding deep-only result;
- maj/min WCSR is not below legacy;
- published-known precision is at least 0.60 at coverage of at least 0.20;
- boundary F1 is not below legacy and predicted/reference event ratio is within [0.75, 1.50];
- no dataset's exact WCSR is more than 0.02 below its legacy result;
- the maximum-minus-minimum three-seed exact WCSR is at most 0.05;
- deterministic replay is byte-identical and five-minute chord CPU wall time is at most 15
  seconds on the reference CPU environment.

The strong development target is exact WCSR at least 0.40, known precision at least 0.70,
coverage at least 0.35, and no unsupported quality silently published.

If Stage 1 and Stage 3 both remain below 0.30 exact WCSR or fail stability, Plan D stops model
expansion and records `data-first-required`. The next action is then a separately approved data
program targeting at least 30--50 real-gold hours and 300 independent works, followed eventually
by the existing 80-hour/500-work production-scale target.

## Error handling and safety

- Missing hashes, changed split identities, unsupported qualities, non-finite logits, invalid
  time axes, and event-count guard violations fail closed.
- Immutable artifacts are written atomically and refuse overwrite.
- A failed or interrupted experiment remains failed or interrupted; it is never silently resumed
  under a different identity.
- Checkpoint resume continues to restore optimizer, scheduler, early-stop, RNG, and generator
  state exactly.
- License decisions for training and weight distribution remain separate gates.
- The product runtime receives no Plan D dependency or default change until promotion is approved.

## Testing strategy

Implementation follows test-driven development.

- Unit tests cover alignment, class-support calculations, confusion matrices, effective-number
  weights, hybrid fallback/override rules, legal bass combinations, hysteresis, event merging,
  event-count guards, per-quality calibration fallback, and deterministic serialization.
- Mutation tests prove that test manifests, Plan C test hashes, direct frozen-session creation,
  split leakage, and changed artifact identities are rejected.
- Regression tests keep Plan C artifacts interpretable, preserve the legacy default, and preserve
  exact checkpoint resume and CPU reproducibility.
- Integration tests replay fixed synthetic legacy events and logits without audio or checkpoints.
- Validation experiments produce three-seed and per-dataset reports plus 10,000 whole-group
  bootstrap resamples.
- Performance tests cover five-minute CPU time, peak memory, and event-count bounds.
- Full ML pytest, Ruff, and legacy runtime tests remain final gates.

## Expected files

The implementation plan may refine names, but the intended boundaries are:

- `docs/ml/plan-d/`: protocol, audit schema, selection, and development decision;
- `docs/ml/MODEL_CARD_PLAN_D.md`: data ceiling, intended use, results, and fallback;
- `ml/configs/plan-d-v1.json`: frozen audit, hybrid, calibration, and gate configuration;
- `ml/src/museecho_ml/diagnostics/plan_d.py`: development-only failure audit;
- `ml/src/museecho_ml/postprocess/hybrid.py`: pure deterministic hybrid decoder;
- `ml/src/museecho_ml/evaluation/plan_d.py`: split-restricted replay and selection;
- focused tests under `ml/tests/diagnostics`, `ml/tests/postprocess`, and
  `ml/tests/evaluation`;
- training and loss files only after the replay stage demonstrates that retraining is warranted.

## Completion states

Plan D has three honest terminal states:

1. `development-candidate-frozen`: all development gates pass; wait for test v2.
2. `data-first-required`: bounded optimization fails or is unstable; expand lawful real-gold data
   before further architecture work.
3. `blocked`: required data, license, compute, or user authorization is unavailable.

None of these states changes the product default by itself.
