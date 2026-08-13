# Task 2 recovery report

## Status

Implemented encrypted pipeline suffix restoration in
`D:\智软工程师大项目\format-recovery`.

## Implementation

- The coordinator resolves persisted canonical media types only from the shared immutable
  `AUDIO_FORMATS` registry and materializes plaintext using the selected registry suffix.
- Unknown persisted media types now raise `AnalysisInputUnavailableError` before plaintext
  materialization/decode invocation.
- Integration coverage writes bytes through the real encrypted store and observes the
  coordinator's temporary decoder input for WAV, MP3, FLAC, M4A/AAC, M4A/ALAC, raw AAC,
  Ogg/Vorbis, and Ogg/Opus. It also proves unknown persisted metadata cannot call the
  decoder.

## TDD evidence

RED was observed before production changes:

- `tests/integration/test_analysis_pipeline.py -k canonical_suffix` produced 6 failures:
  FLAC, M4A, AAC, Ogg/Vorbis, and Ogg/Opus were materialized as `.wav` by the old
  MP3-or-WAV branch; WAV and MP3 passed.
- `test_coordinator_rejects_unknown_persisted_media_type_before_decoder` failed because
  the unknown persisted media type reached the decoder.

GREEN verification:

- Focused coordinator materialization and unknown-type tests: `8 passed, 4 deselected in
  3.38s`; the unknown-type test was also rerun explicitly: `1 passed in 2.03s`.
- Ruff check and format check for the two Task 2 files: `All checks passed!` and
  `2 files already formatted`.
- `git diff --check` exited successfully with no output.

## Self-review

- The coordinator contains no local media-type-to-suffix mapping; it iterates the Task 1
  registry, which remains the sole mapping authority.
- The unknown media-type guard precedes both temporary source creation and `decode_audio`.
- No upload/decode/UI/result/algorithm code or existing security, size, or duration limits
  changed.

## Verification concern

The full pipeline module was run in the cached disposable Python test image and reached the
two existing real-decode integration cases. The Task 2 tests passed, but those two unrelated
WAV end-to-end cases failed because that image lacks `ffmpeg` and `ffprobe`
(`AudioToolUnavailableError` / resulting 503 upload response). The host checkout has a Linux
virtual environment but no executable host or WSL Python 3.12, so a host run was unavailable.
No dependencies or project files were changed to work around this environment limitation.

## Review fix round 1

Reviewer feedback identified a duplicated test-only canonical-media-type-to-suffix table, including
two identical `audio/mp4` rows. The materialization test now parametrizes once from `AUDIO_FORMATS`.
Each registry entry supplies its persisted canonical media type and expected materialized suffix, so
the test covers each canonical persisted media type exactly once without creating a second mapping
authority. It still writes through `ChunkedEncryptedAudioStore` and reads the actual temporary file
at the decoder boundary.

The old static table was removed rather than retained alongside the registry-driven cases. The
previous Task 2 RED run already demonstrated that the MP3-or-WAV coordinator branch failed all
non-WAV/MP3 registry cases; this round is a test refactor and requires no production change.

Round 1 verification:

- Registry-derived materialization command: `7 passed, 4 deselected in 3.10s`.
- Explicit unknown-type pre-decode command: `1 passed in 2.00s`.
- Ruff check passed; formatter was applied, then rechecked before commit.
