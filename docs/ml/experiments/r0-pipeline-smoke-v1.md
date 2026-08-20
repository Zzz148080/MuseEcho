# R0 pipeline smoke v1

Status: **PASSED** on source commit `72cc4904952af44a0b915a5f093e2be56cf19255`.

R0 reads two GuitarSet tracks from the frozen real-gold train split and two from the frozen
real-gold validation split, extracts four-second CQT segments, executes one training step per epoch,
evaluates validation, and writes versioned checkpoints and reports. It is deliberately tiny and is
not a model or competition score.

The first run stopped after epoch 0 with `operational_limit`. Its last checkpoint SHA-256 was
`048ee117d49ac82f87d9970f392c5ada3081d00e11ea958550bcac1a8b8fe7d1`. Resuming that checkpoint
completed epochs 1 and 2. The combined partial-plus-resume curve exactly matched an independent
uninterrupted three-epoch run, field for field. Initial and final train summaries, best validation,
checkpoint identity, device metadata, selected tracks and offsets, best epoch, and best model state
also matched exactly.

The best epoch was 1, and both paths produced best model-state SHA-256
`1f7c63433ec3c971a8b14f19b2517185faa08839701f0ba856d311e04c8b1b61`. Full checkpoint container
hashes are expected to differ because they preserve interruption-history state; equality is asserted
on the restored execution curve and model state rather than on history-bearing container bytes.

The experiment used deterministic CPU float32 execution with seed `20260820`. A fresh verification
run passed all 179 ML tests and Ruff checks. The host pytest temporary directory has restrictive ACLs,
so verification used an explicit workspace-local `--basetemp`.

G1 remains `NOT READY`: 124 real-gold works and 8.9408 hours remain below the 500-work and 80-hour
targets. Route A is frozen, so synthetic B0 is not applicable. The local PyTorch runtime is CPU-only;
formal R1/R2 candidate training remains blocked and was not attempted.
