# BTC-170 Validation Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely integrate the official BTC-ISMIR19 170-class checkpoint as an ML-only candidate, compare it with `chroma-triad-viterbi-v1` on the frozen real-gold validation split, and produce immutable path-free evidence without accessing any test split or changing the product default.

**Architecture:** Add an isolated `museecho_ml.candidates.btc` package for artifact locking, model loading, feature extraction, label/timeline adaptation, and inference. Add a validation-only paired runner that loads each track once, evaluates BTC and legacy with the existing MuseEcho metrics and dataset/group stratification, records operational evidence, and emits a gate decision. The BTC package is never imported by `src/museecho` and the checkpoint remains in an ignored cache.

**Tech Stack:** Python 3.12, PyTorch 2.8+, librosa 0.11, NumPy 2.x, existing MuseEcho immutable JSON/evaluation infrastructure, pytest 9, Ruff 0.16, PowerShell on Windows.

**Spec:** `docs/superpowers/specs/2026-08-23-btc-170-validation-spike-design.md`

## Global Constraints

- Python must remain `>=3.12,<3.13`; do not create an old BTC Python environment.
- The runner accepts only `corpus_role="real-gold"` and `split="validation"`; it rejects train, calibration, and test before checkpoint or audio access.
- Never read, enumerate the contents of, replay, or authorize any frozen Plan C test manifest or test prediction artifact.
- `chroma-triad-viterbi-v1` remains the product default; no production package imports the BTC candidate.
- The official checkpoint is `jayg996/BTC-ISMIR19/test/btc_model_large_voca.pt`, size `12_229_576` bytes, Git blob SHA-1 `11c6edbaaaee33737aa7a41dcb9044191630326f`.
- Do not commit `.pt`, converted weight files, audio, raw feature caches, or prediction caches.
- Never call `torch.load(..., weights_only=False)` and never use `strict=False` when loading model parameters.
- `aug`, `min6`, `maj6`, `minmaj7`, and `dim7` map to `X`; they must not collapse to a supported quality.
- BTC supplies no bass head. Compatible known chords use `bass="1"`, and every report labels bass/turnaround ability as unavailable rather than successful.
- Validation confidence is uncalibrated max-softmax. It is diagnostic only and cannot drive the continuation gate.
- Every generated report must be path-free, SHA-bound, finite-valued, deterministic, and written immutably.
- Every production behavior follows RED → verify RED → GREEN → verify GREEN before refactoring or committing.

## File Structure

- `ml/configs/btc-170-source-v1.json`: immutable approved upstream source identity.
- `ml/configs/btc-170-artifact-lock-v1.json`: generated once from the downloaded official bytes and committed with the actual SHA-256.
- `ml/src/museecho_ml/candidates/__init__.py`: candidate package boundary.
- `ml/src/museecho_ml/candidates/btc_artifact.py`: source validation, download, Git blob/SHA-256 verification, lock writing.
- `ml/src/museecho_ml/candidates/btc_labels.py`: 170-class mapping and frame-to-event timeline construction.
- `ml/src/museecho_ml/candidates/btc_model.py`: current-PyTorch port of the MIT BTC inference network.
- `ml/src/museecho_ml/candidates/btc_checkpoint.py`: safe payload loading, strict tensor contract, normalization statistics.
- `ml/src/museecho_ml/candidates/btc_features.py`: upstream-compatible CQT extraction and normalization.
- `ml/src/museecho_ml/candidates/btc_inference.py`: chunked deterministic CPU recognizer.
- `ml/src/museecho_ml/evaluation/btc.py`: validation-only collection, paired evaluation, bootstrap delta, gate, CLI, immutable reports.
- `ml/tests/candidates/test_btc_artifact.py`: artifact and source security tests.
- `ml/tests/candidates/test_btc_labels.py`: complete vocabulary and timeline tests.
- `ml/tests/candidates/test_btc_checkpoint.py`: safe loader and strict contract tests.
- `ml/tests/candidates/test_btc_features.py`: feature compatibility and input rejection tests.
- `ml/tests/candidates/test_btc_inference.py`: chunking, padding, confidence, and determinism tests.
- `ml/tests/evaluation/test_btc.py`: split firewall, paired metrics, bootstrap, gate, and artifact tests.
- `docs/ml/btc-170/validation-report-v1.json`: sanitized validation comparison evidence.
- `docs/ml/btc-170/decision-v1.json`: continuation decision and predicate evidence.
- `docs/ml/btc-170/comparison-v1.md`: human-readable paired comparison.
- `docs/ml/MODEL_CARD_BTC_170.md`: result, limits, provenance, and follow-up model card.
- `THIRD_PARTY_NOTICES.md`: BTC code attribution and checkpoint distribution warning.

## Execution Prerequisite

Before Task 1, invoke `superpowers:using-git-worktrees`, create or reuse an isolated
workspace, install the already-locked development/train extras, and prove the starting branch is
clean:

```powershell
uv sync --project ml --extra dev --extra train
uv pip install --python ml\.venv\Scripts\python.exe --no-deps --editable .
cd ml
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "btc-baseline-$PID"
.\.venv\Scripts\python.exe -m pytest -q --basetemp $tempRoot -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check --no-cache src tests
cd ..
git status --short --branch
```

Expected: baseline tests and Ruff pass, and the worktree has no changes. If the pre-existing
baseline fails, stop and ask whether to diagnose it; do not begin Task 1 or attribute the failure
to BTC.

---

### Task 1: Lock the official upstream artifact without trusting downloaded bytes

**Files:**
- Create: `ml/configs/btc-170-source-v1.json`
- Create: `ml/src/museecho_ml/candidates/__init__.py`
- Create: `ml/src/museecho_ml/candidates/btc_artifact.py`
- Create: `ml/tests/candidates/test_btc_artifact.py`
- Modify: `THIRD_PARTY_NOTICES.md`
- Generated during this task: `ml/configs/btc-170-artifact-lock-v1.json`

**Interfaces:**
- Produces: `BtcArtifactSource`, `BtcArtifactLock`, `load_btc_source(path)`, `verify_btc_artifact(path, source)`, and `acquire_btc_artifact(source, destination, lock_output)`.
- The lock exposes `sha256`, `size_bytes`, `git_blob_sha1`, `repository`, `repository_ref`, and `source_url` for Task 3.

- [ ] **Step 1: Write failing source and byte-integrity tests**

```python
from hashlib import sha1, sha256
from pathlib import Path

import pytest

from museecho_ml.candidates.btc_artifact import (
    BtcArtifactSource,
    verify_btc_artifact,
)


def _git_blob_sha1(payload: bytes) -> str:
    return sha1(b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload).hexdigest()


def test_verify_btc_artifact_binds_size_git_blob_and_sha256(tmp_path: Path) -> None:
    payload = b"official-checkpoint-fixture"
    checkpoint = tmp_path / "btc.pt"
    checkpoint.write_bytes(payload)
    source = BtcArtifactSource(
        repository="jayg996/BTC-ISMIR19",
        repository_ref="master",
        source_url=(
            "https://raw.githubusercontent.com/jayg996/BTC-ISMIR19/"
            "master/test/btc_model_large_voca.pt"
        ),
        size_bytes=len(payload),
        git_blob_sha1=_git_blob_sha1(payload),
        license_spdx="MIT",
    )

    lock = verify_btc_artifact(checkpoint, source)

    assert lock.sha256 == sha256(payload).hexdigest()
    assert lock.size_bytes == len(payload)


def test_btc_source_rejects_unapproved_host() -> None:
    with pytest.raises(ValueError, match="approved GitHub raw host"):
        BtcArtifactSource(
            repository="jayg996/BTC-ISMIR19",
            repository_ref="master",
            source_url="https://example.com/btc.pt",
            size_bytes=1,
            git_blob_sha1="0" * 40,
            license_spdx="MIT",
        )
```

- [ ] **Step 2: Run the artifact tests and verify RED**

Run:

```powershell
cd ml
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "btc-task1-red-$PID"
.\.venv\Scripts\python.exe -m pytest tests/candidates/test_btc_artifact.py -q --basetemp $tempRoot -p no:cacheprovider
```

Expected: collection fails because `museecho_ml.candidates.btc_artifact` does not exist.

- [ ] **Step 3: Implement the source/lock dataclasses and verifier**

The verifier must compute both ordinary SHA-256 and the Git object identity:

```python
def git_blob_sha1(payload: bytes) -> str:
    header = b"blob " + str(len(payload)).encode("ascii") + b"\0"
    return hashlib.sha1(header + payload).hexdigest()


def verify_btc_artifact(path: Path, source: BtcArtifactSource) -> BtcArtifactLock:
    payload = path.resolve(strict=True).read_bytes()
    if len(payload) != source.size_bytes:
        raise ValueError("BTC checkpoint size does not match approved source")
    if git_blob_sha1(payload) != source.git_blob_sha1:
        raise ValueError("BTC checkpoint Git blob identity does not match")
    return BtcArtifactLock(
        repository=source.repository,
        repository_ref=source.repository_ref,
        source_url=source.source_url,
        size_bytes=len(payload),
        git_blob_sha1=source.git_blob_sha1,
        sha256=hashlib.sha256(payload).hexdigest(),
        license_spdx=source.license_spdx,
    )
```

`acquire_btc_artifact` must stream to a temporary file under `ml/cache/btc`, reject redirects whose final hostname is not `raw.githubusercontent.com`, fsync, verify, atomically replace the destination, and use `write_immutable_json` for the lock. It must delete the temporary file after every failure.

- [ ] **Step 4: Add the exact source descriptor**

Create `ml/configs/btc-170-source-v1.json` with these exact values:

```json
{
  "schema_version": 1,
  "candidate_version": "btc-ismir19-large-voca-v1",
  "repository": "jayg996/BTC-ISMIR19",
  "repository_ref": "master",
  "source_url": "https://raw.githubusercontent.com/jayg996/BTC-ISMIR19/master/test/btc_model_large_voca.pt",
  "size_bytes": 12229576,
  "git_blob_sha1": "11c6edbaaaee33737aa7a41dcb9044191630326f",
  "license_spdx": "MIT"
}
```

- [ ] **Step 5: Acquire the checkpoint and generate the versioned SHA-256 lock**

Run:

```powershell
cd ml
.\.venv\Scripts\python.exe -m museecho_ml.candidates.btc_artifact acquire `
  --source configs/btc-170-source-v1.json `
  --destination cache/btc/btc_model_large_voca.pt `
  --lock-output configs/btc-170-artifact-lock-v1.json
```

Expected: exit 0; the ignored `.pt` exists at the destination; the tracked lock JSON contains a 64-character SHA-256 and repeats the approved size and Git blob SHA-1. If network acquisition is unavailable, stop this task as `blocked-artifact-integrity`; do not substitute another mirror.

- [ ] **Step 6: Add BTC attribution and the distribution warning**

Append to `THIRD_PARTY_NOTICES.md`: repository URL, upstream MIT license, the ported files, checkpoint filename, and the restriction that the checkpoint is research-only pending a separate training-data/redistribution audit. Do not claim that MIT source licensing resolves checkpoint-training-data rights.

- [ ] **Step 7: Verify GREEN and commit**

Run:

```powershell
cd ml
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "btc-task1-green-$PID"
.\.venv\Scripts\python.exe -m pytest tests/candidates/test_btc_artifact.py -q --basetemp $tempRoot -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check --no-cache src/museecho_ml/candidates tests/candidates
cd ..
git diff --check
git add ml/configs/btc-170-source-v1.json ml/configs/btc-170-artifact-lock-v1.json ml/src/museecho_ml/candidates ml/tests/candidates/test_btc_artifact.py THIRD_PARTY_NOTICES.md
git commit -m "feat: lock official btc 170 artifact"
```

Expected: tests and Ruff pass; `.pt` is absent from `git status`; the commit contains source, lock, code, tests, and notices only.

---

### Task 2: Freeze all 170 label mappings and construct legal timelines

**Files:**
- Create: `ml/src/museecho_ml/candidates/btc_labels.py`
- Create: `ml/tests/candidates/test_btc_labels.py`

**Interfaces:**
- Produces: `BTC_ROOTS`, `BTC_QUALITIES`, `decode_btc_class(index) -> CanonicalChord`, and `frames_to_intervals(class_ids, confidences, frame_seconds, duration_seconds) -> tuple[ScoredChordInterval, ...]`.
- Task 4 consumes these interfaces without parsing string labels.

- [ ] **Step 1: Write failing exhaustive mapping tests**

```python
import numpy as np
import pytest

from museecho_ml.candidates.btc_labels import decode_btc_class, frames_to_intervals


@pytest.mark.parametrize("quality_offset", [3, 4, 5, 7, 10])
def test_unsupported_btc_qualities_map_strictly_to_x(quality_offset: int) -> None:
    chord = decode_btc_class(4 * 14 + quality_offset)
    assert (chord.root, chord.quality, chord.bass) == ("X", "X", "X")
    assert chord.mapping_reason is not None
    assert chord.mapping_reason.startswith("unsupported-quality:")


def test_btc_special_classes_are_frozen() -> None:
    assert decode_btc_class(168).root == "X"
    assert decode_btc_class(169).root == "N"


def test_frame_events_cover_the_track_and_merge_equal_states() -> None:
    events = frames_to_intervals(
        np.asarray([1, 1, 169, 15], dtype=np.int64),
        np.asarray([0.8, 0.6, 0.9, 0.7], dtype=np.float64),
        frame_seconds=0.5,
        duration_seconds=2.0,
    )
    assert [(event.start_seconds, event.end_seconds) for event in events] == [
        (0.0, 1.0),
        (1.0, 1.5),
        (1.5, 2.0),
    ]
    assert events[0].confidence == pytest.approx(0.7)
```

Also iterate indices `0..169` and assert every returned `CanonicalChord` is displayable, supported or special, with supported acoustic chords using `bass="1"`.

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
cd ml
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "btc-task2-red-$PID"
.\.venv\Scripts\python.exe -m pytest tests/candidates/test_btc_labels.py -q --basetemp $tempRoot -p no:cacheprovider
```

Expected: import fails because `btc_labels.py` does not exist.

- [ ] **Step 3: Implement the exact upstream order and strict mapping**

Use these exact constants:

```python
BTC_ROOTS = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
BTC_QUALITIES = (
    "min", "maj", "dim", "aug", "min6", "maj6", "min7",
    "minmaj7", "maj7", "7", "dim7", "hdim7", "sus2", "sus4",
)
UNSUPPORTED_QUALITIES = frozenset(("aug", "min6", "maj6", "minmaj7", "dim7"))
```

For indices below 168, compute `root_index, quality_index = divmod(index, 14)`. Unsupported qualities return `CanonicalChord("X", "X", "X", f"unsupported-quality:{quality}")`; compatible qualities return `CanonicalChord(root, quality, "1")`. Reject booleans, negative indices, and indices above 169.

`frames_to_intervals` validates one-dimensional, equal-length, non-empty arrays; finite confidences in `[0, 1]`; positive finite frame duration; and a positive finite track duration. It uses frame start boundaries `index * frame_seconds`, clamps only the final boundary to the exact manifest duration, rejects impossible extra frames, merges adjacent equal canonical states, and computes duration-weighted mean confidence.

- [ ] **Step 4: Verify GREEN and commit**

Run:

```powershell
cd ml
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "btc-task2-green-$PID"
.\.venv\Scripts\python.exe -m pytest tests/candidates/test_btc_labels.py tests/test_labels.py -q --basetemp $tempRoot -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check --no-cache src/museecho_ml/candidates/btc_labels.py tests/candidates/test_btc_labels.py
cd ..
git add ml/src/museecho_ml/candidates/btc_labels.py ml/tests/candidates/test_btc_labels.py
git commit -m "feat: adapt btc 170 chord labels"
```

---

### Task 3: Port the BTC inference network and enforce safe strict checkpoint loading

**Files:**
- Create: `ml/src/museecho_ml/candidates/btc_model.py`
- Create: `ml/src/museecho_ml/candidates/btc_checkpoint.py`
- Create: `ml/tests/candidates/test_btc_checkpoint.py`
- Modify: `ml/src/museecho_ml/candidates/__init__.py`

**Interfaces:**
- Produces: `BtcModelConfig`, `BtcModel`, `BtcCheckpoint`, `load_btc_checkpoint(path, lock, config)`, and `checkpoint_contract(checkpoint) -> dict[str, object]`.
- `BtcCheckpoint` contains the eval-mode CPU model and the finite scalar normalization values `mean` and `std` stored by the official checkpoint.

- [ ] **Step 1: Write failing safety, shape, and strictness tests**

```python
from pathlib import Path

import numpy as np
import pytest
import torch

from museecho_ml.artifacts import file_sha256
from museecho_ml.candidates.btc_artifact import BtcArtifactLock
from museecho_ml.candidates.btc_checkpoint import load_btc_checkpoint
from museecho_ml.candidates.btc_model import BtcModel, BtcModelConfig


def test_btc_model_emits_170_logits_per_frame() -> None:
    model = BtcModel(BtcModelConfig.small_test_config())
    output = model(torch.zeros((2, 8, model.config.feature_size)))
    assert output.shape == (2, 8, 170)


def test_btc_checkpoint_refuses_missing_tensor(tmp_path: Path) -> None:
    model = BtcModel(BtcModelConfig.small_test_config())
    state = model.state_dict()
    state.pop(next(iter(state)))
    path = tmp_path / "bad.pt"
    torch.save({"model": state, "mean": 0.0, "std": np.float64(1.0)}, path)
    artifact_lock = BtcArtifactLock(
        repository="fixture/btc",
        repository_ref="fixture",
        source_url="https://raw.githubusercontent.com/fixture/btc/fixture/btc.pt",
        size_bytes=path.stat().st_size,
        git_blob_sha1="0" * 40,
        sha256=file_sha256(path),
        license_spdx="MIT",
    )

    with pytest.raises(ValueError, match="tensor contract"):
        load_btc_checkpoint(path, artifact_lock, model.config)
```

Add a malicious-pickle fixture whose reducer would create a marker file. Assert loading raises `ValueError("BTC checkpoint cannot be loaded safely")` and the marker is never created. Add tests for extra keys, wrong shapes, zero/negative standard deviation, non-finite values, and SHA-256 mismatch.

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
cd ml
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "btc-task3-red-$PID"
.\.venv\Scripts\python.exe -m pytest tests/candidates/test_btc_checkpoint.py -q --basetemp $tempRoot -p no:cacheprovider
```

Expected: imports fail because the model and checkpoint modules do not exist.

- [ ] **Step 3: Port only the upstream inference architecture**

Port the encoder self-attention stack and output projection from upstream `btc_model.py`, preserving layer names so the official `state_dict` loads strictly. Do not port the training decoder, CRF baselines, MIDI writer, dataset classes, or command-line code. The production constructor must be:

```python
@dataclass(frozen=True)
class BtcModelConfig:
    feature_size: int
    hidden_size: int
    num_layers: int
    num_heads: int
    total_key_depth: int
    total_value_depth: int
    filter_size: int
    timestep: int
    num_chords: int = 170


class BtcModel(torch.nn.Module):
    def forward(self, features: torch.Tensor) -> torch.Tensor:
        if features.ndim != 3 or features.shape[-1] != self.config.feature_size:
            raise ValueError("BTC feature tensor shape is invalid")
        encoded, _ = self.self_attn_layers(features)
        logits, _ = self.output_layer(encoded)
        return logits
```

Keep dropout modules but force `eval()` for inference. `small_test_config()` returns feature size 144, hidden size 16, two layers, two heads, total key/value depth 16, filter size 32, timestep eight, and 170 output classes; it exists to exercise the real implementation without a large fixture.

- [ ] **Step 4: Implement the safe loader**

The only permitted deserialization call is:

```python
payload = torch.load(
    checkpoint_path,
    map_location="cpu",
    weights_only=True,
)
```

Catch all safe-unpickler failures and raise the explicit blocked error. Do not retry with `weights_only=False`. The official legacy file requires only the exact safe-global allowlist for `numpy.core.multiarray.scalar`, `numpy.dtype`, and `numpy.dtypes.Float64DType`; do not broaden that list. Validate the artifact SHA first, validate payload keys, coerce normalization values to Python `float` scalars, validate finite values and strictly positive `std`, then call `model.load_state_dict(payload["model"], strict=True)`. Finally set `requires_grad_(False)` and `eval()`.

- [ ] **Step 5: Verify the official checkpoint contract**

Run:

```powershell
cd ml
.\.venv\Scripts\python.exe -m museecho_ml.candidates.btc_checkpoint inspect `
  --checkpoint cache/btc/btc_model_large_voca.pt `
  --lock configs/btc-170-artifact-lock-v1.json
```

Expected: exit 0 with JSON containing `num_chords: 170`, `feature_size: 144`, a model tensor count, a tensor-contract SHA-256, finite normalization statistics, and `safe_loader: true`. If the safe loader cannot read the official file, stop as `blocked-unsafe-checkpoint`; do not weaken the policy.

- [ ] **Step 6: Verify GREEN and commit**

Run:

```powershell
cd ml
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "btc-task3-green-$PID"
.\.venv\Scripts\python.exe -m pytest tests/candidates/test_btc_checkpoint.py -q --basetemp $tempRoot -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check --no-cache src/museecho_ml/candidates tests/candidates
cd ..
git add ml/src/museecho_ml/candidates ml/tests/candidates/test_btc_checkpoint.py
git commit -m "feat: load btc checkpoint safely"
```

---

### Task 4: Reproduce BTC features and deterministic chunked inference

**Files:**
- Create: `ml/src/museecho_ml/candidates/btc_features.py`
- Create: `ml/src/museecho_ml/candidates/btc_inference.py`
- Create: `ml/tests/candidates/test_btc_features.py`
- Create: `ml/tests/candidates/test_btc_inference.py`

**Interfaces:**
- Produces: `BtcFeatureConfig`, `extract_btc_features(samples, sample_rate, config)`, `BtcEvent`, and `BtcRecognizer.recognize(samples, sample_rate)`.
- `BtcRecognizer` returns full-track events with algorithm `btc-ismir19-large-voca-v1` and exposes CPU/wall timing through `BtcInferenceResult`.

- [ ] **Step 1: Write failing feature tests**

```python
import numpy as np
import pytest

from museecho_ml.candidates.btc_features import BtcFeatureConfig, extract_btc_features


def test_btc_features_are_deterministic_144_bin_log_cqt() -> None:
    config = BtcFeatureConfig.official()
    time = np.arange(22_050, dtype=np.float32) / 22_050
    samples = np.sin(2 * np.pi * 220 * time).astype(np.float32)
    first = extract_btc_features(samples, 22_050, config)
    second = extract_btc_features(samples, 22_050, config)
    assert first.shape[1] == 144
    np.testing.assert_array_equal(first, second)


@pytest.mark.parametrize("samples", [np.asarray([], dtype=np.float32), np.asarray([np.nan])])
def test_btc_features_reject_empty_or_nonfinite_audio(samples: np.ndarray) -> None:
    with pytest.raises(ValueError, match="BTC audio"):
        extract_btc_features(samples, 22_050, BtcFeatureConfig.official())
```

- [ ] **Step 2: Write failing inference chunk/padding tests**

Use a deterministic fake `torch.nn.Module` that returns a known 170-logit class sequence. Assert that a non-multiple-of-108 feature length is padded once, padded outputs are discarded, adjacent classes merge, confidence is max-softmax, the output ends at the exact audio duration, and two runs are byte-identical after serialization.

- [ ] **Step 3: Run and verify RED**

Run:

```powershell
cd ml
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "btc-task4-red-$PID"
.\.venv\Scripts\python.exe -m pytest tests/candidates/test_btc_features.py tests/candidates/test_btc_inference.py -q --basetemp $tempRoot -p no:cacheprovider
```

Expected: imports fail because feature and inference modules do not exist.

- [ ] **Step 4: Implement upstream-compatible feature extraction**

`BtcFeatureConfig.official()` freezes sample rate 22,050 Hz, 144 CQT bins, 24 bins per octave, hop length 2,048, 10-second source chunks, 108 inference timesteps, and log floor `1e-6`. Downmix has already occurred at the audio loader boundary; this function accepts one-dimensional finite float32 audio only, resamples with librosa when needed, computes chunked CQT, concatenates on time, then applies `np.log(np.abs(cqt) + 1e-6).T` and returns contiguous float32 frames.

Standardization is `(features - mean) / std`; reject any non-finite result.

- [ ] **Step 5: Implement deterministic CPU inference**

The public shape is:

```python
@dataclass(frozen=True)
class BtcInferenceResult:
    events: tuple[BtcEvent, ...]
    cpu_seconds: float
    wall_seconds: float
    frame_count: int


class BtcRecognizer:
    def recognize(self, samples: np.ndarray, sample_rate: int) -> BtcInferenceResult:
        started_cpu = time.process_time()
        started_wall = time.perf_counter()
        duration_seconds = samples.size / sample_rate
        features = extract_btc_features(samples, sample_rate, self.feature_config)
        normalized = standardize_btc_features(features, self.checkpoint.mean, self.checkpoint.std)
        logits = self._predict_chunks(normalized)
        probabilities = torch.softmax(logits, dim=-1)
        classes = probabilities.argmax(dim=-1).cpu().numpy()
        confidences = probabilities.max(dim=-1).values.cpu().numpy()
        events = frames_to_intervals(
            classes,
            confidences,
            self.feature_config.frame_seconds,
            duration_seconds,
        )
        return BtcInferenceResult(
            events=events,
            cpu_seconds=time.process_time() - started_cpu,
            wall_seconds=time.perf_counter() - started_wall,
            frame_count=len(classes),
        )
```

Use `torch.inference_mode()`, CPU only, one inference thread unless the experiment config explicitly records another value, and fixed deterministic algorithms. Restore the caller's PyTorch thread count after inference. Do not seed or alter global NumPy random state.

- [ ] **Step 6: Verify GREEN and commit**

Run:

```powershell
cd ml
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "btc-task4-green-$PID"
.\.venv\Scripts\python.exe -m pytest tests/candidates -q --basetemp $tempRoot -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check --no-cache src/museecho_ml/candidates tests/candidates
cd ..
git add ml/src/museecho_ml/candidates ml/tests/candidates
git commit -m "feat: run deterministic btc inference"
```

---

### Task 5: Build a validation-only paired BTC/legacy evaluator

**Files:**
- Create: `ml/src/museecho_ml/evaluation/btc.py`
- Create: `ml/tests/evaluation/test_btc.py`
- Modify: `ml/src/museecho_ml/evaluation/__init__.py`

**Interfaces:**
- Produces: `load_btc_validation_manifest`, `run_btc_validation_experiment`, `paired_group_bootstrap_delta`, and `decide_btc_continuation`.
- Consumes the existing `manifest_reference_intervals`, `evaluate_dataset_strata`, `EvaluationConfig`, `estimate_chords`, `canonical_sha256`, and BTC recognizer interfaces.

- [ ] **Step 1: Write the failing split-firewall test**

```python
import json
from pathlib import Path

import pytest

from museecho_ml.evaluation.btc import load_btc_validation_manifest


@pytest.mark.parametrize("split", ["train", "calibration", "test"])
def test_btc_runner_rejects_every_non_validation_split_before_artifact_or_audio(
    tmp_path: Path, split: str
) -> None:
    manifest = tmp_path / f"{split}.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "corpus_role": "real-gold",
                "split": split,
                "tracks": [{"track_id": "must-not-be-opened"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(PermissionError, match="validation only"):
        load_btc_validation_manifest(manifest)
```

The test must pass nonexistent checkpoint and audio paths to the next public collection function and prove the split error occurs first.

- [ ] **Step 2: Write failing paired-report and gate tests**

Inject two fake recognizers and an in-memory audio loader over three datasets. Assert the report contains the same manifest hash for both candidates; identical track IDs/durations; overall and per-dataset exact/root/boundary metrics; event ratios; unsupported-quality duration; CPU, wall and normalized five-minute timing; peak RSS; and a paired cover-group bootstrap delta.

Gate fixtures must prove:

```python
def test_btc_gate_requires_two_dataset_wins_and_no_root_or_boundary_regression() -> None:
    decision = decide_btc_continuation(_passing_report())
    assert decision["status"] == "continue-btc-research"
    one_dataset = _passing_report()
    one_dataset["comparison"]["dataset_exact_wins"] = 1
    assert decide_btc_continuation(one_dataset)["status"] == "btc-not-selected"
```

Also reject NaN/Infinity, missing predicates, mismatched track identities, and an input marked calibrated.

- [ ] **Step 3: Run and verify RED**

Run:

```powershell
cd ml
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "btc-task5-red-$PID"
.\.venv\Scripts\python.exe -m pytest tests/evaluation/test_btc.py -q --basetemp $tempRoot -p no:cacheprovider
```

Expected: import fails because `museecho_ml.evaluation.btc` does not exist.

- [ ] **Step 4: Implement one-pass paired collection**

Validate manifest metadata and resolve every dataset root before creating the checkpoint or recognizers. For each sorted track: resolve the audio path inside its root, load/downmix with librosa, verify manifest duration, construct references with `manifest_reference_intervals`, then time BTC and legacy separately on the same samples. Convert legacy events through the existing canonical parser and BTC events through `btc_labels`.

Build two track maps and one metadata map, then call `evaluate_dataset_strata` with the same `EvaluationConfig` for both. Measure CPU with `time.process_time()` and wall time with `time.perf_counter()`. Record peak process RSS using `GetProcessMemoryInfo(...).PeakWorkingSetSize` on Windows and `resource.getrusage` elsewhere; fail if unavailable rather than substituting Python-only allocation memory.

- [ ] **Step 5: Implement deterministic paired group bootstrap deltas**

Resample sorted `cover_group_id` values with NumPy `PCG64(20260823)` for 10,000 resamples. For each resample, recompute BTC minus legacy exact-quality WCSR, root WCSR, and boundary F1 from the selected complete group track maps. Return point estimate plus 2.5/97.5 percentiles and the group count. Never resample individual frames or annotation intervals.

- [ ] **Step 6: Implement the continuation decision**

The predicates are exact:

```python
predicates = {
    "exact_above_legacy_0_166596": btc_exact > 0.166596,
    "at_least_two_dataset_exact_wins": dataset_exact_wins >= 2,
    "root_not_below_legacy": btc_root >= legacy_root,
    "boundary_not_below_legacy": btc_boundary >= legacy_boundary,
    "deterministic_prediction_replay": deterministic_replay is True,
    "cpu_benchmark_completed": cpu_seconds > 0 and five_minute_cpu_seconds > 0,
    "checkpoint_security_passed": checkpoint_security_passed is True,
    "artifact_identity_passed": artifact_identity_passed is True,
}
```

Return `continue-btc-research` only when every predicate is true; otherwise return `btc-not-selected` with the failed predicate names. This decision never returns a promotion or default-algorithm change.

- [ ] **Step 7: Verify GREEN and commit**

Run:

```powershell
cd ml
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "btc-task5-green-$PID"
.\.venv\Scripts\python.exe -m pytest tests/evaluation/test_btc.py tests/evaluation/test_statistics.py tests/evaluation/test_metrics.py tests/test_package_boundary.py -q --basetemp $tempRoot -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check --no-cache src/museecho_ml/evaluation/btc.py tests/evaluation/test_btc.py
cd ..
git add ml/src/museecho_ml/evaluation ml/tests/evaluation/test_btc.py
git commit -m "feat: compare btc on validation only"
```

---

### Task 6: Add immutable CLI outputs and replay verification

**Files:**
- Modify: `ml/src/museecho_ml/evaluation/btc.py`
- Modify: `ml/tests/evaluation/test_btc.py`

**Interfaces:**
- Produces CLI subcommands `run` and `replay`.
- `run` writes path-free prediction JSONL, report JSON, decision JSON, and comparison Markdown immutably.
- `replay` recomputes metrics and the decision from the manifest plus path-free predictions without checkpoint or audio access.

- [ ] **Step 1: Write failing immutable/replay tests**

Use a fixture manifest and predictions to assert `run` never serializes `audio_path`, dataset roots, cache paths, or absolute paths. Run replay and assert report/decision canonical SHA-256 values match the original. Attempt a second write with changed content and assert `FileExistsError`.

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
cd ml
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "btc-task6-red-$PID"
.\.venv\Scripts\python.exe -m pytest tests/evaluation/test_btc.py -q --basetemp $tempRoot -p no:cacheprovider
```

Expected: new CLI/artifact assertions fail because serialization and replay are absent.

- [ ] **Step 3: Implement immutable outputs and CLI**

Prediction rows contain only split, track ID, dataset ID, cover group ID, duration, serialized BTC/legacy intervals, candidate timing, and hashes. Report identity includes source commit, validation manifest SHA-256, evaluation config SHA-256, source descriptor SHA-256, artifact lock SHA-256, checkpoint tensor-contract SHA-256, predictions SHA-256, Python/platform/library versions, PyTorch thread count, and `confidence_status="uncalibrated-diagnostic-only"`.

Use atomic immutable writes equivalent to `write_immutable_json`; add `write_immutable_bytes` to `ml/src/museecho_ml/artifacts.py` only if JSONL/Markdown cannot use the existing helper. Test the helper first in `ml/tests/test_artifacts.py` if it is added.

- [ ] **Step 4: Verify GREEN and commit**

Run:

```powershell
cd ml
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "btc-task6-green-$PID"
.\.venv\Scripts\python.exe -m pytest tests/evaluation/test_btc.py tests/test_artifacts.py -q --basetemp $tempRoot -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check --no-cache src tests/evaluation/test_btc.py tests/test_artifacts.py
cd ..
git add ml/src/museecho_ml/evaluation/btc.py ml/src/museecho_ml/artifacts.py ml/tests/evaluation/test_btc.py ml/tests/test_artifacts.py
git commit -m "feat: freeze btc validation evidence"
```

---

### Task 7: Run the official validation comparison and publish the evidence

**Files:**
- Create: `docs/ml/btc-170/validation-report-v1.json`
- Create: `docs/ml/btc-170/decision-v1.json`
- Create: `docs/ml/btc-170/comparison-v1.md`
- Create: `docs/ml/MODEL_CARD_BTC_170.md`
- Modify: `ml/README.md`

**Interfaces:**
- Consumes all prior tasks and the existing validation manifest at `ml/data/manifests/splits-v1/real-gold-validation.manifest.json`.
- Produces the final evidence and recommendation; it still cannot promote a model.

- [ ] **Step 1: Reconfirm the implemented candidate before touching real validation audio**

Run the candidate-complete tests immediately before the real experiment:

```powershell
uv sync --project ml --extra dev --extra train
uv pip install --python ml\.venv\Scripts\python.exe --no-deps --editable .
cd ml
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "btc-baseline-$PID"
.\.venv\Scripts\python.exe -m pytest -q --basetemp $tempRoot -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check --no-cache src tests
```

Expected: the complete candidate and unchanged ML regression suite pass before validation audio is opened.

- [ ] **Step 2: Run the official validation experiment**

```powershell
cd ml
.\.venv\Scripts\python.exe -m museecho_ml.evaluation.btc run `
  --manifest data/manifests/splits-v1/real-gold-validation.manifest.json `
  --dataset-root guitarset=data/sources `
  --dataset-root rwc-popular=data/sources `
  --dataset-root schubert-winterreise=data/sources/schubert-winterreise-2.1 `
  --evaluation-config configs/evaluation-v1.json `
  --source configs/btc-170-source-v1.json `
  --artifact-lock configs/btc-170-artifact-lock-v1.json `
  --checkpoint cache/btc/btc_model_large_voca.pt `
  --predictions-output runs/btc-170/validation-v1/predictions.jsonl `
  --report-output ../docs/ml/btc-170/validation-report-v1.json `
  --decision-output ../docs/ml/btc-170/decision-v1.json `
  --markdown-output ../docs/ml/btc-170/comparison-v1.md
```

Expected: 39 tracks complete; report identifies GuitarSet (24), RWC Popular (11), and Schubert Winterreise (4); no test path is opened; outputs contain no absolute paths.

- [ ] **Step 3: Prove deterministic inference and path-free replay**

Run the experiment a second time to a fresh ignored output directory and compare canonical prediction hashes. Then run:

```powershell
cd ml
.\.venv\Scripts\python.exe -m museecho_ml.evaluation.btc replay `
  --manifest data/manifests/splits-v1/real-gold-validation.manifest.json `
  --evaluation-config configs/evaluation-v1.json `
  --predictions runs/btc-170/validation-v1/predictions.jsonl `
  --expected-report ../docs/ml/btc-170/validation-report-v1.json `
  --expected-decision ../docs/ml/btc-170/decision-v1.json
```

Expected: prediction hashes match across inference runs; replay exits 0 and exactly reproduces metrics and decision without checkpoint or audio reads.

- [ ] **Step 4: Write the result model card from generated evidence**

`docs/ml/MODEL_CARD_BTC_170.md` must state the actual overall and per-dataset BTC/legacy scores, paired bootstrap intervals, unsupported-quality duration, event ratio, CPU/wall/real-time factor, peak RSS, determinism result, artifact/tensor identities, decision predicates, license warning, uncalibrated confidence warning, absence of bass prediction, permanent test prohibition, and unchanged product default. Copy numeric values from the immutable report; do not round values used by the gate.

Update `ml/README.md` with the validation-only command, artifact-cache location, safety rule, and report links. Do not add any test command or product-runtime installation step.

- [ ] **Step 5: Run complete verification**

Run:

```powershell
cd ml
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "btc-full-$PID"
.\.venv\Scripts\python.exe -m pytest -q --basetemp $tempRoot -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check --no-cache src tests
cd ..
$runtimeTemp = Join-Path ([System.IO.Path]::GetTempPath()) "btc-runtime-$PID"
.\.venv\Scripts\python.exe -m pytest tests/unit/analysis/test_chords.py tests/integration/test_analysis_pipeline.py -q --basetemp $runtimeTemp -p no:cacheprovider
git diff --check
git status --short --ignored | Select-String "btc_model_large_voca.pt|ml/cache|ml/runs"
```

Expected: all ML and selected product-runtime tests pass; Ruff and diff checks pass; the checkpoint and raw runs are ignored; source-controlled evidence and documentation are the only result files staged.

- [ ] **Step 6: Commit the evidence**

```powershell
git add docs/ml/btc-170 docs/ml/MODEL_CARD_BTC_170.md ml/README.md
git commit -m "docs: record btc 170 validation result"
git status --short --branch
```

Expected: clean worktree. The final report must lead with either `continue-btc-research` or `btc-not-selected`; neither outcome changes the default algorithm.

---

## Plan Self-Review Checklist

- [ ] Every design requirement maps to a task.
- [ ] No task authorizes frozen test access or production promotion.
- [ ] Artifact acquisition, checkpoint safety, label mapping, inference, evaluation, replay, and evidence have independent RED/GREEN cycles.
- [ ] Interfaces and filenames are consistent across tasks.
- [ ] No `.pt`, audio, path-bearing raw data, or ignored run output is committed.
- [ ] The final recommendation is evidence-driven and remains development-only.
