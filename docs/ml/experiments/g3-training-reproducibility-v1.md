# G3 training reproducibility v1

Status: **PASSED** on source commit `2fcbdb222076cacf886b3591537ddec404cf4f2d`.

This gate uses two GuitarSet tracks from the frozen real-gold train split. It selects a four-second
window beginning at the first fully supervised root/quality/bass interval in each track
(`11.162790697674419` seconds). The same tiny batch is used only to prove that the training chain
can learn and resume; these numbers are not validation or competition scores.

The initial total loss was `6.449569225311279`. The validation-selected checkpoint at epoch 46 had
total loss `0.13007207214832306`, a ratio of `0.02016755966241223`, with root and quality accuracy
both equal to `1.0`. This passes the frozen gates of loss ratio at most `0.05` and root/quality
accuracy at least `0.95`.

Two independent CPU float32 runs with seed `20260820` produced byte-identical reports, artifact
indexes, best checkpoints, and last checkpoints. The best model-state SHA-256 is
`549bbe117bc2a5823b4e1fb0ffa1accc76832b1b8888810a60b4bc5301f5f32f`; the best checkpoint SHA-256
is `98d36196f4877eadf31cbe609b9e29e5c30b6a66c27ead7bd6d35cba88ed06eb`. A separate automated
partial-run/resume test reaches the same best parameter hash as an uninterrupted run while
restoring model, optimizer, scheduler, early-stop, RNG, counters, configuration, and data identity.

G1 remains `NOT READY`: the available real-gold data contains 124 works and 8.9408 hours, below the
500-work and 80-hour targets. The local PyTorch runtime is CPU-only, so this report does not claim a
GPU run or candidate-model quality.
