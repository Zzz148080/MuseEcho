# MuseEcho Data-Capped Chord Plan C Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic Plan C research machinery that admits the audited small-data corpus, freezes a train-only vocabulary and C0/C1/conditional-C2 curricula, compares three seeds with reproducible small-sample statistics, and prevents test leakage or unauthorized model promotion.

**Architecture:** Keep the historical A/B route and checkpoint-v2 behavior intact. Add focused modules for data gates, train-only vocabulary freezing, protocol freezing, staged training, validation selection, grouped statistics, and promotion/test receipts; every frozen artifact is canonical JSON whose SHA-256 is carried into downstream identities. The implementation authorizes research when G1a passes while continuously reporting G1b as not met, and leaves the legacy recognizer as the product default unless every promotion check passes.

**Tech Stack:** Python 3.12, dataclasses and strict JSON, NumPy 2.x, PyTorch 2.8+, pytest 9, Ruff 0.16, existing MuseEcho manifest/checkpoint/evaluation modules.

**Spec:** `docs/superpowers/specs/2026-08-21-data-capped-chord-plan-c-design.md`

## Global Constraints

- Work only in `D:\人工智能创新赛` on branch `competition/deep-chord-v2`.
- Preserve `decide_training_route()` and the frozen 41.487981-hour Route A report as historical evidence.
- Report `G1a PASS` and `G1b NOT MET` independently; G1b remains at 500 unique real-gold works, 80 hours, and 20 independent works per published non-`N/X` quality.
- Only `real-gold` may enter calibration, validation, or test; `synthetic-supervised` and `real-score-supervised` are pretrain/train-only roles.
- Plan C initial qualities are `maj`, `min`, `7`, `maj7`, `min7`, `dim`, `hdim7`, and `sus4`, plus `N` and `X`; `sus2` maps to `X`.
- The vocabulary may shrink only from real-gold train cover-group counts with a minimum of 20 groups; validation and test cannot add a quality.
- C0, C1, and an available C2 use seeds `20260821`, `20260822`, and `20260823` and the same real-gold finetune, calibration, validation, and test identities.
- Bootstrap uses 10,000 work/cover-group resamples and seed `20260821`.
- Course ranking uses unrounded values in this order: exact-vocabulary WCSR, public-quality Macro-F1, published-known precision, coverage, lower five-minute CPU wall time, then C0/C1/C2.
- The frozen test is readable exactly once after protocol, vocabulary, calibration, threshold, course, and checkpoint identities are frozen.
- Plan C completion does not imply promotion. Promotion requires maj/min WCSR at least legacy, exact-vocabulary WCSR strictly above legacy, seventh-quality Macro-F1 at least 0.55, precision at least 0.85, coverage at least 0.65, ECE at most 0.08, deterministic events, ONNX maximum absolute probability error at most `1e-4` with identical events, chord-stage time at most 30 seconds and RSS at most 2 GB for five minutes on 2 vCPU/4 GB, full analysis at most 90 seconds and 4 GB, and explicit weight-distribution approval for every training dataset.
- The legacy algorithm remains the default unless the machine-readable promotion decision is `passed`; the 8-point exact-WCSR improvement remains a strong-result target, not a Plan C completion gate.
- IDMT-SMT-Guitar V2 download auditing and MAESTRO feasibility remain separate specifications; this plan consumes only an approved inventory, manifest, or feasibility conclusion.
- Raw audio, manifests under `ml/data`, caches, runs, checkpoints, and ONNX binaries remain ignored by Git.
- Use `ml\.venv\Scripts\python.exe` and a workspace-local pytest base such as `--basetemp ..\tmp\plan-c-pytest`.
- Each behavior change follows RED, GREEN, focused regression, then commit. Do not rewrite unrelated user changes.

---

## File Structure

- `ml/src/museecho_ml/data/course.py`: corpus-role enum and unchanged historical A/B route selection.
- `ml/src/museecho_ml/artifacts.py`: canonical JSON bytes, SHA-256 helpers, and immutable atomic JSON writes shared by frozen artifacts.
- `ml/src/museecho_ml/data/gates.py`: compute G1a/G1b from approved registry records, frozen real-gold manifests, and split audit evidence.
- `ml/src/museecho_ml/data/vocabulary_freeze.py`: derive the shrinking Plan C vocabulary from only the frozen real-gold train manifest.
- `ml/src/museecho_ml/data/plan_c.py`: validate and freeze the C0/C1/conditional-C2 protocol and canonical JSON identity.
- `ml/src/museecho_ml/training/plan_c.py`: run one frozen course/stage/seed, transfer pretraining weights without transferring optimizer state, and preserve exact resume inside each stage.
- `ml/src/museecho_ml/evaluation/statistics.py`: grouped bootstrap, per-dataset reports, and dataset-macro aggregation.
- `ml/src/museecho_ml/evaluation/selection.py`: aggregate three seeds and deterministically freeze the winning course/checkpoint before test.
- `ml/src/museecho_ml/evaluation/promotion.py`: one-use frozen-test receipt, promotion gates, license checks, and legacy-default decision.
- `ml/configs/plan-c-v1.json`: versioned thresholds, seeds, curriculum IDs, metric order, and bootstrap settings.
- `docs/ml/plan-c/*.json`: path-free frozen G1, vocabulary, protocol, selection, test-receipt, and promotion evidence.
- `docs/ml/MODEL_CARD_PLAN_C.md`: data-capped applicability, unsupported qualities, confidence intervals, and final outcome.

---

### Task 1: Add the score-supervised role and split G1 into machine-readable G1a/G1b

**Files:**
- Modify: `ml/src/museecho_ml/data/course.py`
- Create: `ml/src/museecho_ml/artifacts.py`
- Create: `ml/src/museecho_ml/data/gates.py`
- Modify: `ml/tests/data/test_course.py`
- Create: `ml/tests/test_artifacts.py`
- Create: `ml/tests/data/test_gates.py`

**Interfaces:**
- Consumes: `DatasetRegistry`, four frozen manifest dictionaries keyed by `train`, `calibration`, `validation`, and `test`, and `docs/ml/split-audit-v1.json`-shaped evidence.
- Produces: `CorpusRole.REAL_SCORE_SUPERVISED`; `canonical_json_bytes(value: Any) -> bytes`; `canonical_sha256(value: Any) -> str`; `file_sha256(path: Path) -> str`; `write_immutable_json(path: Path, value: Mapping[str, Any]) -> None`; `evaluate_data_gates(registry: DatasetRegistry, manifests: Mapping[str, Mapping[str, Any]], split_audit: Mapping[str, Any], *, minimum_works: int = 500, minimum_seconds: float = 288000.0, minimum_quality_works: int = 20, production_scale_exclusions: Mapping[str, str] | None = None) -> dict[str, Any]`.

- [ ] **Step 1: Write failing role-isolation tests**

```python
def test_score_supervised_is_valid_but_cannot_enter_real_evaluation() -> None:
    assert CorpusRole.REAL_SCORE_SUPERVISED.value == "real-score-supervised"
    manifest = {"tracks": [{"track_id": "score", "corpus_role": "real-score-supervised"}]}
    with pytest.raises(ValueError, match="real-gold"):
        select_manifest_role(manifest, role=CorpusRole.REAL_GOLD)

def test_historical_route_a_ignores_score_supervised_hours() -> None:
    decision = decide_training_route([
        _inventory("idmt", role="synthetic-supervised", hours=41.487981),
        _inventory("maestro", role="real-score-supervised", hours=100.0),
    ])
    assert decision.route == "A"
    assert decision.usable_synthetic_seconds == pytest.approx(41.487981 * 3600)
```

- [ ] **Step 2: Run the role tests and confirm RED**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/data/test_course.py -q --basetemp ..\tmp\plan-c-course-red`

Expected: failure because `REAL_SCORE_SUPERVISED` does not exist.

- [ ] **Step 3: Add only the new enum value and keep route logic unchanged**

```python
class CorpusRole(StrEnum):
    REAL_GOLD = "real-gold"
    REAL_SCORE_SUPERVISED = "real-score-supervised"
    SYNTHETIC_SUPERVISED = "synthetic-supervised"
    WEAK_LABEL_VALIDATION = "weak-label-validation"
```

- [ ] **Step 4: Write failing canonical-artifact and dual-gate tests**

```python
def test_canonical_json_is_order_independent_and_rejects_nan() -> None:
    assert canonical_json_bytes({"b": 2, "a": 1}) == b'{"a":1,"b":2}'
    with pytest.raises(ValueError):
        canonical_json_bytes({"value": float("nan")})

def test_audited_small_data_passes_g1a_but_not_g1b() -> None:
    status = evaluate_data_gates(
        _approved_registry(), _four_real_gold_manifests(), _passed_split_audit()
    )
    assert status["g1a"]["status"] == "passed"
    assert status["g1b"]["status"] == "not-met"
    assert status["g1b"]["observed"]["work_count"] == 124
    assert status["g1b"]["required"]["work_count"] == 500

def test_g1a_rejects_non_gold_eval_and_failed_fingerprint_audit() -> None:
    manifests = _four_real_gold_manifests()
    manifests["validation"]["corpus_role"] = "synthetic-supervised"
    with pytest.raises(ValueError, match="validation.*real-gold"):
        evaluate_data_gates(_approved_registry(), manifests, _passed_split_audit())
```

- [ ] **Step 5: Run the artifact and gate tests and confirm RED**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/test_artifacts.py tests/data/test_gates.py -q --basetemp ..\tmp\plan-c-gates-red`

Expected: collection failure because `museecho_ml.data.gates` does not exist.

- [ ] **Step 6: Implement shared canonical artifact helpers and strict gate computation**

```python
def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")

def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
```

`write_immutable_json()` appends one newline to `canonical_json_bytes()`, writes through a temporary file in the destination directory, flushes and `fsync`s, uses `os.replace`, accepts an identical existing file, and rejects a different existing file. `file_sha256()` streams the file and returns lowercase hexadecimal. Keeping the newline outside `canonical_sha256()` preserves the existing frozen split-hash convention.

```python
_SPLITS = ("train", "calibration", "validation", "test")

def evaluate_data_gates(
    registry: DatasetRegistry,
    manifests: Mapping[str, Mapping[str, Any]],
    split_audit: Mapping[str, Any],
    *,
    minimum_works: int = 500,
    minimum_seconds: float = 80 * 3600,
    minimum_quality_works: int = 20,
    production_scale_exclusions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    _require_four_real_gold_splits(manifests, split_audit)
    tracks = [track for split in _SPLITS for track in manifests[split]["tracks"]]
    dataset_ids = sorted({str(track["dataset_id"]) for track in tracks})
    for dataset_id in dataset_ids:
        registry.require_training_approval(dataset_id)
    exclusions = _validated_exclusions(production_scale_exclusions, dataset_ids)
    scale_tracks = [track for track in tracks if track["dataset_id"] not in exclusions]
    work_ids = {str(track["work_id"]) for track in scale_tracks}
    annotated_seconds = math.fsum(
        float(interval["end_seconds"]) - float(interval["start_seconds"])
        for track in scale_tracks for interval in track["intervals"]
    )
    quality_works = _quality_work_counts(tracks)
    return _path_free_gate_report(
        dataset_ids, work_ids, annotated_seconds, quality_works,
        split_audit, minimum_works, minimum_seconds, minimum_quality_works,
    )
```

The helper must verify split names, `split_sha256`, per-split manifest hashes, `near_duplicate_audit.status == "passed"`, non-empty tracks, no repeated track across splits, and no work or cover group crossing splits. G1a always audits every real-gold dataset. G1b may exclude a named dataset only through a non-empty path-free reason; the current GuitarSet reason is `lead-sheet-domain-augmentation-not-independent-musical-works`, preserving the approved Winterreise/RWC-P production-scale facts without hiding GuitarSet from training or evaluation. It must output explicit reason codes instead of using G1b to reject Plan C.

- [ ] **Step 7: Run focused data tests and confirm GREEN**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/test_artifacts.py tests/data/test_course.py tests/data/test_gates.py tests/data/test_split.py tests/data/test_split_freeze.py -q --basetemp ..\tmp\plan-c-gates-green`

Expected: all selected tests pass; the historical Route A assertion remains unchanged.

- [ ] **Step 8: Commit the role and gate unit**

```powershell
git add ml/src/museecho_ml/artifacts.py ml/src/museecho_ml/data/course.py ml/src/museecho_ml/data/gates.py ml/tests/test_artifacts.py ml/tests/data/test_course.py ml/tests/data/test_gates.py
git commit -m "feat: split plan c data readiness gates"
```

---

### Task 2: Freeze a train-only shrinking vocabulary and map unsupported qualities to X

**Files:**
- Modify: `ml/src/museecho_ml/vocabulary.py`
- Create: `ml/src/museecho_ml/data/vocabulary_freeze.py`
- Create: `ml/tests/data/test_vocabulary_freeze.py`
- Modify: `ml/tests/test_labels.py`

**Interfaces:**
- Consumes: one `split == "train"`, `corpus_role == "real-gold"` manifest.
- Produces: `ChordVocabulary.from_dict(value: Mapping[str, Any]) -> ChordVocabulary`; `freeze_plan_c_vocabulary(train_manifest: Mapping[str, Any], *, minimum_group_count: int = 20) -> dict[str, Any]`; `map_to_frozen_vocabulary(chord: CanonicalChord, vocabulary: ChordVocabulary) -> CanonicalChord`.

- [ ] **Step 1: Write failing train-only and `sus2` tests**

```python
def test_vocabulary_counts_cover_groups_only_from_real_gold_train() -> None:
    frozen = freeze_plan_c_vocabulary(_train_manifest_with_quality_groups())
    assert frozen["quality_group_counts"]["sus2"] == 19
    assert "sus2" not in frozen["quality_labels"]
    assert frozen["quality_labels"][-2:] == ["N", "X"]

@pytest.mark.parametrize("split", ["calibration", "validation", "test"])
def test_vocabulary_refuses_non_train_split(split: str) -> None:
    with pytest.raises(PermissionError, match="train"):
        freeze_plan_c_vocabulary(_manifest(split=split, role="real-gold"))

def test_sus2_maps_to_full_x_state() -> None:
    vocabulary = ChordVocabulary.from_dict(_frozen_without_sus2())
    assert map_to_frozen_vocabulary(
        CanonicalChord("D", "sus2", "1"), vocabulary
    ) == CanonicalChord("X", "X", "X", "plan-c-unsupported-quality:sus2")
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/data/test_vocabulary_freeze.py -q --basetemp ..\tmp\plan-c-vocab-red`

Expected: collection failure because the freeze module and constructor do not exist.

- [ ] **Step 3: Implement canonical vocabulary loading and hashing**

```python
PLAN_C_INITIAL_QUALITIES = ("maj", "min", "7", "maj7", "min7", "dim", "hdim7", "sus4")

def freeze_plan_c_vocabulary(
    train_manifest: Mapping[str, Any], *, minimum_group_count: int = 20
) -> dict[str, Any]:
    _require_real_gold_train(train_manifest)
    counts = _quality_cover_group_counts(train_manifest["tracks"])
    kept = tuple(q for q in PLAN_C_INITIAL_QUALITIES if counts.get(q, 0) >= minimum_group_count)
    payload = {
        "schema_version": 1,
        "vocabulary_version": "plan-c-v1",
        "source_split": "train",
        "source_split_sha256": train_manifest["split_sha256"],
        "minimum_group_count": minimum_group_count,
        "quality_group_counts": dict(sorted(counts.items())),
        "root_labels": list(ROOT_LABELS),
        "quality_labels": [*kept, "N", "X"],
        "bass_labels": list(BASS_LABELS),
        "mapped_to_x": sorted(set(PLAN_C_INITIAL_QUALITIES) - set(kept) | {"sus2"}),
    }
    return {**payload, "vocabulary_sha256": canonical_sha256(payload)}
```

`ChordVocabulary.from_dict()` must reject duplicates, labels outside the canonical root/quality/bass universes, special labels not in the final two positions, and a hash mismatch when a hash is supplied.

- [ ] **Step 4: Route batch encoding through the frozen mapping**

```python
def map_to_frozen_vocabulary(
    chord: CanonicalChord, vocabulary: ChordVocabulary
) -> CanonicalChord:
    if chord.root in {"N", "X"}:
        return chord
    if chord.quality not in vocabulary.quality_labels:
        return CanonicalChord(
            "X", "X", "X", f"plan-c-unsupported-quality:{chord.quality}"
        )
    return chord
```

Use this function before `vocabulary.encode()` so every unsupported quality becomes one valid full `X` state and never a mixed special state.

- [ ] **Step 5: Run vocabulary, labels, and full-N/X regressions**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/data/test_vocabulary_freeze.py tests/test_labels.py tests/model/test_batch.py tests/model/test_loss.py -q --basetemp ..\tmp\plan-c-vocab-green`

Expected: all tests pass, including finite all-`N/X` loss and bass-mask behavior.

- [ ] **Step 6: Commit the vocabulary unit**

```powershell
git add ml/src/museecho_ml/vocabulary.py ml/src/museecho_ml/data/vocabulary_freeze.py ml/tests/data/test_vocabulary_freeze.py ml/tests/test_labels.py
git commit -m "feat: freeze train-only plan c vocabulary"
```

---

### Task 3: Freeze the C0/C1/conditional-C2 protocol without changing Route A

**Files:**
- Create: `ml/src/museecho_ml/data/plan_c.py`
- Create: `ml/tests/data/test_plan_c.py`
- Create: `ml/configs/plan-c-v1.json`
- Modify: `ml/configs/training-route-v1.json`

**Interfaces:**
- Consumes: G1 report, vocabulary report, four real-gold manifests, two required synthetic manifests, optional score manifest, optional MAESTRO feasibility report, and dataset registry.
- Produces: `freeze_plan_c_protocol(config: Mapping[str, Any], *, g1_report: Mapping[str, Any], vocabulary_report: Mapping[str, Any], real_manifests: Mapping[str, Path], synthetic_manifests: Sequence[Path], registry: DatasetRegistry, historical_route_report: Mapping[str, Any], score_manifest: Path | None = None, score_feasibility: Mapping[str, Any] | None = None) -> dict[str, Any]` and `write_frozen_protocol(path: Path, protocol: Mapping[str, Any]) -> None`.

- [ ] **Step 1: Add the versioned protocol config**

```json
{
  "schema_version": 1,
  "plan_version": "plan-c-v1",
  "seeds": [20260821, 20260822, 20260823],
  "minimum_quality_train_groups": 20,
  "bootstrap": {"resamples": 10000, "seed": 20260821, "unit": "cover_group_id"},
  "courses": ["C0", "C1", "C2"],
  "required_synthetic_datasets": ["idmt-smt-chord-sequences", "jazznet"],
  "selection_metrics": [
    "exact_vocabulary_wcsr", "public_quality_macro_f1",
    "published_known_precision", "coverage", "five_minute_cpu_wall_seconds"
  ],
  "course_tie_order": ["C0", "C1", "C2"]
}
```

Also add `real-score-supervised` to `forbidden_evaluation_roles` in `training-route-v1.json` without changing its threshold or default route.

- [ ] **Step 2: Write failing deterministic curriculum tests**

```python
def test_plan_c_always_freezes_c0_and_c1_and_structurally_skips_c2() -> None:
    protocol = freeze_plan_c_protocol(
        _config(), g1_report=_g1a_pass(), vocabulary_report=_vocabulary(),
        real_manifests=_real_paths(), synthetic_manifests=_synthetic_paths(),
        registry=_registry(), score_feasibility={"status": "not-approved"},
    )
    assert protocol["courses"]["C0"]["status"] == "ready"
    assert protocol["courses"]["C1"]["status"] == "ready"
    assert protocol["courses"]["C2"] == {
        "status": "skipped", "reason_code": "score-supervision-not-approved"
    }

def test_plan_c_rejects_mixed_roles_before_audio_access() -> None:
    mixed = _synthetic_paths_with_track_role("real-gold")
    with pytest.raises(ValueError, match="role-pure"):
        freeze_plan_c_protocol(
            _config(), g1_report=_g1a_pass(), vocabulary_report=_vocabulary(),
            real_manifests=_real_paths(), synthetic_manifests=mixed,
            registry=_registry(), score_feasibility={"status": "not-approved"},
        )
```

- [ ] **Step 3: Run tests and confirm RED**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/data/test_plan_c.py -q --basetemp ..\tmp\plan-c-protocol-red`

Expected: collection failure because `museecho_ml.data.plan_c` does not exist.

- [ ] **Step 4: Implement the canonical path-free protocol**

```python
def freeze_plan_c_protocol(
    config: Mapping[str, Any],
    *,
    g1_report: Mapping[str, Any],
    vocabulary_report: Mapping[str, Any],
    real_manifests: Mapping[str, Path],
    synthetic_manifests: Sequence[Path],
    registry: DatasetRegistry,
    score_manifest: Path | None = None,
    score_feasibility: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if g1_report["g1a"]["status"] != "passed":
        raise PermissionError("Plan C requires G1a PASS")
    real = _bind_real_splits(real_manifests)
    synthetic = _bind_required_role_pure_manifests(
        synthetic_manifests, CorpusRole.SYNTHETIC_SUPERVISED, registry
    )
    c2 = _freeze_c2_or_skip(score_manifest, score_feasibility, registry)
    body = {
        "schema_version": 1,
        "plan_version": config["plan_version"],
        "g1_report_sha256": canonical_sha256(g1_report),
        "vocabulary_sha256": vocabulary_report["vocabulary_sha256"],
        "seeds": config["seeds"],
        "real_splits": real,
        "courses": {
            "C0": {"status": "ready", "pretrain": None},
            "C1": {"status": "ready", "pretrain": synthetic},
            "C2": c2,
        },
        "bootstrap": config["bootstrap"],
        "selection_metrics": config["selection_metrics"],
        "course_tie_order": config["course_tie_order"],
    }
    return {**body, "protocol_sha256": canonical_sha256(body)}
```

All stored manifest bindings must contain logical dataset/split IDs and content hashes, never local absolute paths. C1 missing either official synthetic dataset must fail; C2 missing approval must return the fixed skip object and must not create an empty manifest.

- [ ] **Step 5: Prove output-order independence and shared real identities**

Add tests that reverse manifest and seed input order, compare canonical bytes, and assert every ready course references the same `train`, `calibration`, `validation`, and `test` hashes. Add a fixture showing any synthetic or score hash in a real split is rejected.

- [ ] **Step 6: Run protocol and historical-route regressions**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/data/test_plan_c.py tests/data/test_course.py tests/data/test_route_freeze.py -q --basetemp ..\tmp\plan-c-protocol-green`

Expected: all tests pass and Route A remains frozen below 60 hours.

- [ ] **Step 7: Commit the protocol unit**

```powershell
git add ml/src/museecho_ml/data/plan_c.py ml/tests/data/test_plan_c.py ml/configs/plan-c-v1.json ml/configs/training-route-v1.json
git commit -m "feat: freeze plan c curricula"
```

---

### Task 4: Chain pretraining to real finetuning while preserving exact checkpoint resume

**Files:**
- Modify: `ml/src/museecho_ml/training/checkpoint.py`
- Modify: `ml/src/museecho_ml/training/train.py`
- Create: `ml/src/museecho_ml/training/plan_c.py`
- Create: `ml/configs/train-plan-c-v1.json`
- Modify: `ml/tests/training/test_checkpoint.py`
- Modify: `ml/tests/training/test_train.py`
- Create: `ml/tests/training/test_plan_c.py`

**Interfaces:**
- Consumes: frozen protocol path, frozen vocabulary path, base train config, course ID, stage, seed, optional exact-resume checkpoint.
- Produces: `load_model_initialization(path: Path, model: Any, *, expected_checkpoint_sha256: str) -> None`; `build_plan_c_stage_identity(*, base_config_sha256: str, protocol_sha256: str, vocabulary_sha256: str, course_id: str, stage: str, seed: int, train_manifest_sha256: str, validation_manifest_sha256: str, initialization_checkpoint_sha256: str | None) -> CheckpointIdentity`; `run_plan_c_stage(protocol_path: Path, vocabulary_path: Path, base_config_path: Path, *, course_id: str, stage: str, seed: int, run_dir: Path, resume_path: Path | None = None) -> dict[str, Any]`.

- [ ] **Step 1: Write failing weight-transfer and identity tests**

```python
def test_pretrain_transfer_loads_model_only_and_resets_optimizer(tmp_path: Path) -> None:
    source = _write_checkpoint_with_nonzero_optimizer(tmp_path)
    target_model, target_optimizer = _fresh_components()
    load_model_initialization(source, target_model, expected_checkpoint_sha256=_sha(source))
    assert _model_sha(target_model) == _checkpoint_model_sha(source)
    assert target_optimizer.state == {}

def test_plan_c_stage_identity_binds_protocol_vocabulary_course_stage_and_seed() -> None:
    common = {
        "base_config_sha256": "a" * 64,
        "protocol_sha256": "b" * 64,
        "vocabulary_sha256": "c" * 64,
        "course_id": "C1",
        "stage": "finetune",
        "train_manifest_sha256": "d" * 64,
        "validation_manifest_sha256": "e" * 64,
        "initialization_checkpoint_sha256": "f" * 64,
    }
    first = build_plan_c_stage_identity(**common, seed=20260821)
    second = build_plan_c_stage_identity(**common, seed=20260822)
    assert first.run_config_sha256 != second.run_config_sha256
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/training/test_plan_c.py tests/training/test_checkpoint.py -q --basetemp ..\tmp\plan-c-training-red`

Expected: failure because the initialization and stage-runner interfaces do not exist.

- [ ] **Step 3: Add safe model-only initialization without changing checkpoint-v2 resume**

```python
def load_model_initialization(
    path: Path, model: Any, *, expected_checkpoint_sha256: str
) -> None:
    source = path.resolve(strict=True)
    if file_sha256(source) != expected_checkpoint_sha256:
        raise ValueError("initialization checkpoint SHA-256 does not match")
    payload = torch.load(source, map_location="cpu", weights_only=False)
    if payload.get("checkpoint_version") != "checkpoint-v2":
        raise ValueError("initialization checkpoint version is unsupported")
    if payload.get("model_config") != asdict(model.config):
        raise ValueError("initialization checkpoint model config does not match")
    model.load_state_dict(payload["model_state"], strict=True)
```

Do not restore optimizer, scheduler, early-stop, or RNG state here. Leave `save_checkpoint()` and `load_checkpoint()` exact-resume semantics unchanged.

- [ ] **Step 4: Parameterize training with the frozen vocabulary and optional initialization**

Change `_load_manifest_batch(manifest: dict[str, Any], dataset_roots: dict[str, Path], *, limit: int | None, segment_seconds: float, segment_start_policy: str, feature_config: CqtConfig, vocabulary: ChordVocabulary) -> tuple[Sequence[str], Sequence[float], ModelBatch]` and `run_training_batches(config: TrainConfig, train_batch: ModelBatch, validation_batch: ModelBatch, identity: CheckpointIdentity, run_dir: Path, *, vocabulary: ChordVocabulary, initialization_checkpoint: tuple[Path, str] | None = None, resume_path: Path | None = None, epoch_limit: int | None = None) -> dict[str, Any]`. Validate:

```python
if config.model_config.root_classes != len(vocabulary.root_labels):
    raise ValueError("model root classes do not match frozen vocabulary")
if config.model_config.quality_classes != len(vocabulary.quality_labels):
    raise ValueError("model quality classes do not match frozen vocabulary")
if config.model_config.bass_classes != len(vocabulary.bass_labels):
    raise ValueError("model bass classes do not match frozen vocabulary")
```

Map intervals through `map_to_frozen_vocabulary()` before collation. Keep default-vocabulary behavior for existing smoke and reproducibility tests.

Create `train-plan-c-v1.json` from the current formal CRNN config with `seed: 20260821`, `purpose: "formal"`, and `model.quality_classes: 10`; keep all feature, convolution, GRU, augmentation boundary, optimizer, scheduler, early-stop, and real finetune settings identical. The stage runner replaces only the seed and output identity per invocation and must reject any model head dimension that differs from the frozen vocabulary. The historical `train-crnn-v1.json` remains unchanged.

- [ ] **Step 5: Implement strict stage semantics**

`run_plan_c_stage()` must enforce:

```python
_ALLOWED_STAGES = {
    "C0": ("finetune",),
    "C1": ("pretrain", "finetune"),
    "C2": ("pretrain", "finetune"),
}
```

- C0 finetune starts from fixed random initialization.
- C1 pretrain reads both required role-pure synthetic manifests and never real calibration/validation/test.
- C1 finetune requires the matching seed's C1 pretrain checkpoint hash and uses the same real train/validation hashes as C0.
- A ready C2 follows the same pattern with only `real-score-supervised`; a skipped C2 returns its existing structured skip report without opening audio.
- Stage identity is the canonical SHA-256 of base config hash, protocol hash, vocabulary hash, course, stage, seed, train/validation manifest hashes, and initialization checkpoint hash.
- Exact resume is permitted only when all stage identity fields match.
- The Plan C runner calls `load_train_config()` and the lower-level training functions only after verifying `g1a.status == "passed"`; it does not call the historical `run_from_config()` branch that still emits `G1 NOT READY` for the superseded formal route.

- [ ] **Step 6: Add stage-boundary tests**

Test all three seeds; missing C1 synthetic input; mixed-role pretrain; score data in validation; C1 finetune without pretrain checkpoint; C0 with an initialization checkpoint; and resume with a mismatched protocol/vocabulary hash. Assert failures occur before the fake audio loader is called.

- [ ] **Step 7: Run training regressions**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/training/test_checkpoint.py tests/training/test_train.py tests/training/test_trainer.py tests/training/test_plan_c.py tests/model/test_loss.py -q --basetemp ..\tmp\plan-c-training-green`

Expected: stage tests pass together with exact CPU resume, class weights, and full-`N/X` tests.

- [ ] **Step 8: Commit the staged-training unit**

```powershell
git add ml/src/museecho_ml/training/checkpoint.py ml/src/museecho_ml/training/train.py ml/src/museecho_ml/training/plan_c.py ml/configs/train-plan-c-v1.json ml/tests/training/test_checkpoint.py ml/tests/training/test_train.py ml/tests/training/test_plan_c.py
git commit -m "feat: chain plan c pretraining and finetuning"
```

---

### Task 5: Aggregate three seeds and freeze the validation-only course selection

**Files:**
- Create: `ml/src/museecho_ml/evaluation/selection.py`
- Create: `ml/tests/evaluation/test_selection.py`

**Interfaces:**
- Consumes: frozen protocol and exactly three validation reports for each ready course.
- Produces: `summarize_course_runs(reports: Sequence[Mapping[str, Any]], *, expected_seeds: Sequence[int]) -> dict[str, Any]`; `select_plan_c_candidate(protocol: Mapping[str, Any], reports_by_course: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]`.

- [ ] **Step 1: Write failing order-independent selection tests**

```python
def test_course_selection_uses_three_seed_median_not_best_seed() -> None:
    selected = select_plan_c_candidate(_protocol(), _reports_where_c1_has_one_outlier())
    assert selected["winning_course"] == "C0"
    assert selected["winning_seed"] == 20260822

def test_report_and_seed_order_do_not_change_frozen_selection_bytes() -> None:
    first = select_plan_c_candidate(_protocol(), _ordered_reports())
    second = select_plan_c_candidate(_protocol(), _reversed_reports())
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/evaluation/test_selection.py -q --basetemp ..\tmp\plan-c-selection-red`

Expected: collection failure because the selection module does not exist.

- [ ] **Step 3: Implement exact median/min/max summaries**

```python
_HIGHER_IS_BETTER = (
    "exact_vocabulary_wcsr", "public_quality_macro_f1",
    "published_known_precision", "coverage",
)

def summarize_course_runs(reports, *, expected_seeds):
    by_seed = _validate_one_report_per_seed(reports, expected_seeds)
    return {
        "seeds": list(sorted(by_seed)),
        "metrics": {
            metric: {
                "median": statistics.median(report["metrics"][metric] for report in by_seed.values()),
                "minimum": min(report["metrics"][metric] for report in by_seed.values()),
                "maximum": max(report["metrics"][metric] for report in by_seed.values()),
            }
            for metric in (*_HIGHER_IS_BETTER, "five_minute_cpu_wall_seconds")
        },
    }
```

Reject missing/duplicate/extra seeds, rounded display values used as source metrics, non-finite values, split/hash mismatches, and any report marked `test`.

- [ ] **Step 4: Implement deterministic lexicographic ranking**

Rank by `(-exact, -macro_f1, -precision, -coverage, cpu_seconds, course_tie_index)` using full Python floats. In the winning course, choose the seed minimizing `abs(seed_exact_wcsr - course_median_exact_wcsr)`, then the numeric seed. Bind the chosen checkpoint SHA-256, calibration SHA-256, threshold SHA-256, vocabulary SHA-256, protocol SHA-256, and validation manifest SHA-256 into the output.

- [ ] **Step 5: Add negative selection tests**

Cover missing C2 reports when C2 is ready, reports supplied when C2 is skipped, one seed bound to a different validation manifest, test-split input, and ties through every metric proving fixed C0/C1/C2 order.

- [ ] **Step 6: Run selection tests and confirm GREEN**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/evaluation/test_selection.py -q --basetemp ..\tmp\plan-c-selection-green`

Expected: all tests pass with byte-identical results under input reordering.

- [ ] **Step 7: Commit the selection unit**

```powershell
git add ml/src/museecho_ml/evaluation/selection.py ml/tests/evaluation/test_selection.py
git commit -m "feat: freeze plan c validation selection"
```

---

### Task 6: Add grouped bootstrap, per-dataset metrics, and dataset-macro reporting

**Files:**
- Create: `ml/src/museecho_ml/evaluation/statistics.py`
- Modify: `ml/src/museecho_ml/evaluation/report.py`
- Create: `ml/tests/evaluation/test_statistics.py`
- Modify: `ml/tests/evaluation/test_metrics.py`

**Interfaces:**
- Consumes: track evaluation reports plus `track_id -> {dataset_id, cover_group_id}` metadata.
- Produces: `evaluate_dataset_strata(tracks: Mapping[str, tuple[Sequence[ScoredChordInterval], Sequence[ScoredChordInterval]]], metadata: Mapping[str, Mapping[str, str]], config: EvaluationConfig) -> dict[str, Any]`; `dataset_macro(dataset_reports: Mapping[str, Mapping[str, Any]]) -> dict[str, float]`; `group_bootstrap_ci(group_reports: Mapping[str, Sequence[Mapping[str, float]]], *, resamples: int = 10_000, seed: int = 20260821) -> dict[str, Any]`.

- [ ] **Step 1: Write failing dataset-macro and grouped-bootstrap tests**

```python
def test_dataset_macro_weights_three_sources_equally() -> None:
    report = dataset_macro({
        "guitarset": _metrics(exact=0.9),
        "rwc-popular": _metrics(exact=0.6),
        "schubert-winterreise": _metrics(exact=0.3),
    })
    assert report["exact_vocabulary_wcsr"] == pytest.approx(0.6)

def test_bootstrap_resamples_whole_groups_and_is_byte_reproducible() -> None:
    first = group_bootstrap_ci(_group_reports(), resamples=10_000, seed=20260821)
    second = group_bootstrap_ci(dict(reversed(list(_group_reports().items()))), resamples=10_000, seed=20260821)
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert first["unit"] == "cover_group_id"
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/evaluation/test_statistics.py -q --basetemp ..\tmp\plan-c-statistics-red`

Expected: collection failure because the statistics module does not exist.

- [ ] **Step 3: Implement dataset strata and macro aggregation**

Require exactly the datasets present in the frozen manifest; for the current protocol assert the published report contains `guitarset`, `rwc-popular`, and `schubert-winterreise`. Compute each dataset using the same existing duration-weighted evaluator, then arithmetic-mean corresponding scalar metrics across datasets. Never pool tracks first for dataset-macro.

The Plan C scalar report must expose `exact_vocabulary_wcsr` from `weighted_scores.exact_quality`, `public_quality_macro_f1` as the arithmetic mean of per-quality F1 over only the frozen non-`N/X` quality labels, `published_known_precision`, `coverage`, `ece`, `majmin_wcsr`, and `seventh_quality_macro_f1` over `7`, `maj7`, `min7`, and `hdim7` that remain in the frozen vocabulary. Missing required support is reported explicitly and cannot be converted to a passing zero or omitted metric.

- [ ] **Step 4: Implement whole-group bootstrap**

```python
def group_bootstrap_ci(group_reports, *, resamples=10_000, seed=20260821):
    group_ids = tuple(sorted(group_reports))
    rng = np.random.default_rng(seed)
    samples = np.empty((resamples, len(_BOOTSTRAP_METRICS)), dtype=np.float64)
    for index in range(resamples):
        selected = rng.choice(len(group_ids), size=len(group_ids), replace=True)
        samples[index] = _aggregate_selected_groups(group_ids, selected, group_reports)
    return _percentile_report(samples, group_ids, resamples, seed)
```

Use NumPy's fixed `Generator(PCG64)` path, canonical group ordering, linear 2.5/97.5 percentiles, and `allow_nan=False`. A cover group's tracks must always be sampled together. Include point estimate, lower, upper, seed, resample count, unit, group count, and implementation version.

- [ ] **Step 5: Extend corpus reports without breaking schema-v1 consumers**

Add a Plan C wrapper report with `schema_version: 2`, retaining the existing `aggregate` and `tracks` keys and adding `datasets`, `dataset_macro`, and `bootstrap`. Keep `evaluate_track()` behavior unchanged.

- [ ] **Step 6: Add invalid-input tests**

Reject empty groups, duplicate track assignment, unknown dataset IDs, non-finite metrics, fewer than two groups, non-positive resample count, and metadata that maps one cover group to multiple frozen splits.

- [ ] **Step 7: Run evaluation regressions**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/evaluation/test_statistics.py tests/evaluation/test_metrics.py tests/evaluation/test_legacy_adapter.py -q --basetemp ..\tmp\plan-c-statistics-green`

Expected: all tests pass and existing legacy reports remain replayable.

- [ ] **Step 8: Commit the statistics unit**

```powershell
git add ml/src/museecho_ml/evaluation/statistics.py ml/src/museecho_ml/evaluation/report.py ml/tests/evaluation/test_statistics.py ml/tests/evaluation/test_metrics.py
git commit -m "feat: add grouped plan c evaluation statistics"
```

---

### Task 7: Enforce single test access, promotion licensing, and legacy default

**Files:**
- Modify: `ml/src/museecho_ml/data/registry.py`
- Create: `ml/src/museecho_ml/evaluation/promotion.py`
- Create: `ml/tests/evaluation/test_promotion.py`
- Modify: `ml/tests/data/test_adapters.py`
- Modify: `tests/unit/analysis/test_chords.py`

**Interfaces:**
- Consumes: frozen selection, candidate and legacy frozen-test reports, resource/parity/determinism evidence, dataset registry, and optional existing test receipt.
- Produces: `DatasetRegistry.require_weights_distribution_approval(dataset_id: str) -> DatasetRecord`; `authorize_frozen_test(selection: Mapping[str, Any], test_manifest: Mapping[str, Any], *, existing_receipt: Mapping[str, Any] | None) -> dict[str, Any]`; `decide_model_promotion(*, selection: Mapping[str, Any], candidate: Mapping[str, Any], legacy: Mapping[str, Any], operational: Mapping[str, Any], registry: DatasetRegistry) -> dict[str, Any]`.

- [ ] **Step 1: Write failing single-use test receipt tests**

```python
def test_test_authorization_binds_every_frozen_identity() -> None:
    receipt = authorize_frozen_test(_selection(), _test_manifest(), existing_receipt=None)
    assert receipt["status"] == "authorized"
    assert receipt["selection_sha256"] == _selection()["selection_sha256"]
    assert receipt["test_manifest_sha256"] == _test_hash()

def test_existing_receipt_forbids_second_test_access() -> None:
    with pytest.raises(PermissionError, match="already consumed"):
        authorize_frozen_test(_selection(), _test_manifest(), existing_receipt=_receipt())
```

- [ ] **Step 2: Write failing promotion tests**

```python
def test_unapproved_weight_distribution_keeps_legacy_default() -> None:
    result = decide_model_promotion(
        selection=_selection(), candidate=_passing_candidate(), legacy=_legacy(),
        operational=_passing_operational_evidence(), registry=_registry_with_unknown_distribution(),
    )
    assert result["status"] == "rejected"
    assert result["default_algorithm"] == "chroma-triad-viterbi-v1"
    assert "weights-distribution-not-approved" in result["failed_reason_codes"]
```

- [ ] **Step 3: Run tests and confirm RED**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/evaluation/test_promotion.py tests/data/test_adapters.py -q --basetemp ..\tmp\plan-c-promotion-red`

Expected: failure because receipt, promotion, and weight-distribution approval interfaces do not exist.

- [ ] **Step 4: Add the explicit distribution-license gate**

```python
def require_weights_distribution_approval(self, dataset_id: str) -> DatasetRecord:
    record = self.require_training_approval(dataset_id)
    if record.weights_distribution_allowed is not True:
        raise PermissionError(
            f"dataset {dataset_id!r} is not approved for weights distribution"
        )
    return record
```

Keep training approval and distribution approval separate so research can proceed while promotion remains blocked.

- [ ] **Step 5: Implement immutable test authorization**

Require selection status `frozen`, exact protocol/vocabulary/calibration/threshold/checkpoint hashes, `test` split, matching frozen split SHA, real-gold role, and no prior receipt. Return a path-free receipt with `status: authorized`, all input hashes, and a canonical `receipt_sha256`. After evaluation, convert it once to `status: consumed` with candidate/legacy report hashes; refuse any mutation or second consumption.

- [ ] **Step 6: Implement every promotion predicate explicitly**

```python
checks = {
    "majmin-not-below-legacy": candidate_majmin >= legacy_majmin,
    "exact-strictly-above-legacy": candidate_exact > legacy_exact,
    "seventh-macro-f1": candidate_seventh_macro_f1 >= 0.55,
    "published-known-precision": candidate_precision >= 0.85,
    "coverage": candidate_coverage >= 0.65,
    "ece": candidate_ece <= 0.08,
    "deterministic-events": operational["deterministic_events"] is True,
    "onnx-probability-parity": operational["onnx_max_abs_probability_error"] <= 1e-4,
    "onnx-event-parity": operational["onnx_events_identical"] is True,
    "chord-cpu-wall": operational["chord_five_minute_wall_seconds"] <= 30.0,
    "chord-peak-rss": operational["chord_peak_rss_bytes"] <= 2 * 1024**3,
    "full-analysis-wall": operational["full_five_minute_wall_seconds"] <= 90.0,
    "full-analysis-peak-rss": operational["full_peak_rss_bytes"] <= 4 * 1024**3,
}
```

Add one license check per training dataset. Status is `passed` only when every check passes. Otherwise return `rejected` and `default_algorithm: "chroma-triad-viterbi-v1"`. Record the 8-point exact improvement separately as `strong_result_target_met`; do not include it in Plan C completion or promotion status.

- [ ] **Step 7: Add mismatch and boundary tests**

Test exact equality for maj/min, strict equality failure for exact WCSR, every numeric threshold boundary, NaN rejection, mismatched test hash, mismatched vocabulary/calibration hash, `needs-review`/`blocked`/null distribution statuses, and a fully passing fixture. Assert the existing runtime default remains legacy when promotion is rejected.

- [ ] **Step 8: Run promotion and runtime regressions**

Run:

```powershell
cd ml
.\.venv\Scripts\python.exe -m pytest tests/evaluation/test_promotion.py tests/data/test_adapters.py -q --basetemp ..\tmp\plan-c-promotion-green
cd ..
.\.venv\Scripts\python.exe -m pytest tests\unit\analysis\test_chords.py -q --basetemp tmp\plan-c-runtime-green
```

Expected: all tests pass; no product code changes are needed because legacy is already the default.

- [ ] **Step 9: Commit the access and promotion unit**

```powershell
git add ml/src/museecho_ml/data/registry.py ml/src/museecho_ml/evaluation/promotion.py ml/tests/evaluation/test_promotion.py ml/tests/data/test_adapters.py tests/unit/analysis/test_chords.py
git commit -m "feat: gate plan c test access and promotion"
```

---

### Task 8: Generate frozen Plan C artifacts and update evidence documentation

**Files:**
- Create: `docs/ml/plan-c/g1-status-v1.json`
- Create: `docs/ml/plan-c/vocabulary-v1.json`
- Create: `docs/ml/plan-c/protocol-v1.json`
- Create when validation completes: `docs/ml/plan-c/selection-v1.json`
- Create when test is consumed: `docs/ml/plan-c/test-receipt-v1.json`
- Create when gates are evaluated: `docs/ml/plan-c/promotion-v1.json`
- Modify: `docs/ml/DATA_CARD.md`
- Modify: `docs/ml/PHASE_APPROVAL.md`
- Modify: `docs/ml/experiments/EXPERIMENT_INDEX.md`
- Create: `docs/ml/MODEL_CARD_PLAN_C.md`
- Modify: `docs/superpowers/specs/2026-08-21-data-capped-chord-plan-c-design.md`
- Create: `ml/tests/data/test_plan_c_artifacts.py`

**Interfaces:**
- Consumes: the functions from Tasks 1-7 and current local ignored manifests.
- Produces: canonical, path-free, hash-bound public evidence; documentation that distinguishes infrastructure readiness, experiment completion, and promotion.

- [ ] **Step 1: Write failing artifact consistency tests**

```python
def test_committed_plan_c_artifacts_recompute_their_hashes() -> None:
    for name in ("g1-status-v1.json", "vocabulary-v1.json", "protocol-v1.json"):
        payload = _read(PLAN_C_DOCS / name)
        assert embedded_hash_is_valid(payload)

def test_protocol_keeps_route_a_and_c2_skip_as_separate_facts() -> None:
    protocol = _read(PLAN_C_DOCS / "protocol-v1.json")
    assert protocol["historical_route"] == "A"
    assert protocol["courses"]["C1"]["status"] == "ready"
    assert protocol["courses"]["C2"]["status"] == "skipped"
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/data/test_plan_c_artifacts.py -q --basetemp ..\tmp\plan-c-artifacts-red`

Expected: failure because the public Plan C artifacts do not exist.

- [ ] **Step 3: Generate G1, vocabulary, and protocol artifacts from current evidence**

Run the module CLIs with:

```powershell
cd ml
.\.venv\Scripts\python.exe -m museecho_ml.data.gates --registry ..\docs\ml\dataset-registry.example.json --split-audit ..\docs\ml\split-audit-v1.json --manifest train=data\manifests\splits-v1\real-gold-train.manifest.json --manifest calibration=data\manifests\splits-v1\real-gold-calibration.manifest.json --manifest validation=data\manifests\splits-v1\real-gold-validation.manifest.json --manifest test=data\manifests\splits-v1\real-gold-test.manifest.json --output ..\docs\ml\plan-c\g1-status-v1.json
.\.venv\Scripts\python.exe -m museecho_ml.data.vocabulary_freeze --train-manifest data\manifests\splits-v1\real-gold-train.manifest.json --output ..\docs\ml\plan-c\vocabulary-v1.json
.\.venv\Scripts\python.exe -m museecho_ml.data.plan_c --config configs\plan-c-v1.json --g1 ..\docs\ml\plan-c\g1-status-v1.json --vocabulary ..\docs\ml\plan-c\vocabulary-v1.json --registry ..\docs\ml\dataset-registry.example.json --real-split-dir data\manifests\splits-v1 --synthetic-manifest data\manifests\idmt-synthetic-supervised.manifest.json --synthetic-manifest data\manifests\jazznet-synthetic-supervised.manifest.json --historical-route data\manifests\training-route.json --output ..\docs\ml\plan-c\protocol-v1.json
```

Expected current facts: G1a `passed`; G1b `not-met` at 124 works and approximately 8.9408 hours; train-only `sus2` is excluded; historical Route A remains unchanged; C0/C1 are ready; C2 is skipped with `score-supervision-not-approved`.

- [ ] **Step 4: Update documentation with evidence-first wording**

- `DATA_CARD.md`: list all roles, G1a/G1b separately, 124 works/8.9408 hours/17,795 intervals, 41.487981 synthetic hours, train-only vocabulary rule, and distribution-license limits.
- `PHASE_APPROVAL.md`: append the user's 2026-08-21 Plan C and design-document approval, explicitly excluding new external downloads, paid compute, and license acceptance.
- `EXPERIMENT_INDEX.md`: preserve old rows; replace the old G1-blocked interpretation with Plan C rows for C0/C1 as `ready`, C2 as `skipped`, validation selection as `not run`, and frozen test as `not consumed`. Change no result to `passed` before evidence exists.
- `MODEL_CARD_PLAN_C.md`: state data limits, supported qualities, unsupported `sus2`, intended research use, three-seed/bootstrap protocol, G1b not met, promotion status, and legacy fallback.
- Plan C design status: change only the status line to record that the user approved the design on 2026-08-21 and link this implementation plan.

- [ ] **Step 5: Run artifact and documentation tests**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/data/test_plan_c_artifacts.py tests/test_package_boundary.py -q --basetemp ..\tmp\plan-c-artifacts-green`

Expected: canonical hashes validate and no data, audio, checkpoint, cache, or ONNX artifact is tracked.

- [ ] **Step 6: Commit the frozen infrastructure evidence**

```powershell
git add docs/ml/plan-c docs/ml/DATA_CARD.md docs/ml/PHASE_APPROVAL.md docs/ml/experiments/EXPERIMENT_INDEX.md docs/ml/MODEL_CARD_PLAN_C.md docs/superpowers/specs/2026-08-21-data-capped-chord-plan-c-design.md ml/tests/data/test_plan_c_artifacts.py
git commit -m "docs: freeze plan c research protocol"
```

---

### Task 9: Run the research protocol, consume test once, and close with reproducible evidence

**Files:**
- Generate under ignored paths: `ml/runs/plan-c/**`
- Create after each completed run: `docs/ml/experiments/plan-c-<course>-seed-<seed>.json`
- Create after validation: `docs/ml/plan-c/selection-v1.json`
- Create after test: `docs/ml/plan-c/test-receipt-v1.json`
- Create after gate evaluation: `docs/ml/plan-c/promotion-v1.json`
- Modify: `docs/ml/experiments/EXPERIMENT_INDEX.md`
- Modify: `docs/ml/MODEL_CARD_PLAN_C.md`

**Interfaces:**
- Consumes: committed protocol/vocabulary artifacts, approved local manifests, stage runner, validation evaluator, statistics module, selection module, and promotion module.
- Produces: six C0/C1 finetune reports, three C1 pretrain reports, one C2 skip report, frozen validation selection, one candidate-vs-legacy test report, one consumed receipt, and one promotion/default decision.

- [ ] **Step 1: Re-run the existing safety baseline before long experiments**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/training/test_checkpoint.py tests/training/test_seed.py tests/model/test_loss.py tests/training/test_train.py -q --basetemp ..\tmp\plan-c-preflight`

Expected: exact checkpoint recovery, CPU reproducibility, class weights, all-`N/X`, and two-track overfit/smoke tests pass before formal runs begin.

- [ ] **Step 2: Execute or resume C0 for all three seeds**

```powershell
cd ml
$seeds = 20260821,20260822,20260823
foreach ($seed in $seeds) {
  .\.venv\Scripts\python.exe -m museecho_ml.training.plan_c --protocol ..\docs\ml\plan-c\protocol-v1.json --vocabulary ..\docs\ml\plan-c\vocabulary-v1.json --base-config configs\train-plan-c-v1.json --course C0 --stage finetune --seed $seed --run-dir "runs\plan-c\C0\$seed\finetune"
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
}
```

Expected: each run has checkpoint-best, checkpoint-last, artifact index, training report, and stage identity. If interrupted, rerun only that seed with its checkpoint-last through the explicit `--resume` option; never restart from a silently different identity.

- [ ] **Step 3: Execute or resume C1 pretrain and finetune for all three seeds**

```powershell
cd ml
$seeds = 20260821,20260822,20260823
foreach ($seed in $seeds) {
  .\.venv\Scripts\python.exe -m museecho_ml.training.plan_c --protocol ..\docs\ml\plan-c\protocol-v1.json --vocabulary ..\docs\ml\plan-c\vocabulary-v1.json --base-config configs\train-plan-c-v1.json --course C1 --stage pretrain --seed $seed --run-dir "runs\plan-c\C1\$seed\pretrain"
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
  .\.venv\Scripts\python.exe -m museecho_ml.training.plan_c --protocol ..\docs\ml\plan-c\protocol-v1.json --vocabulary ..\docs\ml\plan-c\vocabulary-v1.json --base-config configs\train-plan-c-v1.json --course C1 --stage finetune --seed $seed --initial-checkpoint "runs\plan-c\C1\$seed\pretrain\checkpoint-best.pt" --run-dir "runs\plan-c\C1\$seed\finetune"
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
}
```

Expected: C1 finetune reports bind their same-seed pretrain checkpoint hashes and the identical real train/validation/vocabulary hashes used by C0.

- [ ] **Step 4: Preserve the C2 structured skip**

Run the C2 command once. Expected: exit success with a path-free `skipped` report containing `score-supervision-not-approved`; no manifest, audio access, or checkpoint is created.

- [ ] **Step 5: Evaluate validation, bootstrap by group, and freeze selection**

For each of the six finetune checkpoints, invoke `evaluate_dataset_strata(tracks, metadata, config)` on the frozen validation predictions, then invoke `group_bootstrap_ci(group_reports, resamples=10_000, seed=20260821)`. The prediction producer must be the already-approved calibration/decoder work in `docs/superpowers/plans/2026-08-17-deep-chord-recognition.md`, Task 11; complete that task first if `ml/src/museecho_ml/postprocess/calibration.py` and `ml/src/museecho_ml/postprocess/decoder.py` are absent. Feed exactly three resulting validation reports per ready course to `select_plan_c_candidate()` and write `docs/ml/plan-c/selection-v1.json` through `write_immutable_json()`.

Expected: the selection records median/minimum/maximum for each course, the winning course, closest-to-median winning seed, and all checkpoint/protocol/vocabulary/calibration/threshold hashes. No test manifest is opened in this step.

- [ ] **Step 6: Audit the frozen selection before test authorization**

Run: `cd ml; .\.venv\Scripts\python.exe -m museecho_ml.evaluation.selection --verify ..\docs\ml\plan-c\selection-v1.json --protocol ..\docs\ml\plan-c\protocol-v1.json --vocabulary ..\docs\ml\plan-c\vocabulary-v1.json`

Expected: success and a statement that the test receipt does not yet exist. If any identity differs, stop without reading test and repair only the validation-side artifact chain.

- [ ] **Step 7: Authorize and consume the frozen test exactly once**

Create the authorization receipt, evaluate the selected candidate and unchanged legacy predictor on the same frozen real-gold test manifest, compute grouped/bootstrap/dataset reports, and atomically mark the receipt consumed with both report hashes.

Expected: subsequent authorization or evaluation attempts fail with `test receipt already consumed`. If test results influence a model or threshold change, mark this test identity degraded and stop promotion until a new legal test set exists.

- [ ] **Step 8: Evaluate promotion without forcing a positive result**

Run `decide_model_promotion()` with frozen test, deterministic inference, ONNX parity, CPU/RSS, full-analysis, and registry evidence. Current null weight-distribution permissions for RWC-P or Winterreise must yield `rejected` unless separately reviewed and changed with evidence; rejected status is a valid Plan C research result and keeps legacy default.

- [ ] **Step 9: Update the experiment index and model card from generated evidence**

Mark each actual run as passed, failed, or interrupted based only on its artifact. Record C2 skipped, the frozen selected candidate, the single consumed test, confidence intervals, data-strata results, unsupported qualities, G1b not met, strong-result target status, and promotion decision. State “did not exceed legacy” plainly if that is the measured result.

- [ ] **Step 10: Run the final full verification suite**

```powershell
cd ml
.\.venv\Scripts\python.exe -m pytest -q --basetemp ..\tmp\plan-c-full-pytest
.\.venv\Scripts\python.exe -m ruff check src tests
cd ..
.\.venv\Scripts\python.exe -m pytest tests\unit\analysis\test_chords.py -q --basetemp tmp\plan-c-runtime-pytest
git status --short
git check-ignore ml\data ml\runs ml\checkpoints
```

Expected: all tests pass, Ruff reports no violations, only intended code/docs are tracked, and large local artifacts remain ignored.

- [ ] **Step 11: Commit final reproducible evidence**

```powershell
git add docs/ml/experiments docs/ml/plan-c docs/ml/MODEL_CARD_PLAN_C.md
git commit -m "docs: record plan c frozen comparison"
```

Do not add `ml/data`, `ml/runs`, checkpoints, audio, caches, or ONNX binaries.

---

## Final Acceptance Checklist

- [ ] G1a and G1b are independently computed, serialized, and documented.
- [ ] `real-score-supervised` is legal for train-only pretraining and impossible in calibration/validation/test.
- [ ] Historical Route A remains byte-for-byte interpretable and `decide_training_route()` still returns A for 41.487981 hours.
- [ ] The Plan C vocabulary is derived from only real-gold train cover groups; `sus2` maps deterministically to `X`.
- [ ] C0/C1 and C2 ready-or-skip are canonical and bind the same real data identities.
- [ ] C1/C2 transfer only model weights; checkpoint-v2 exact resume still restores optimizer, scheduler, early-stop, RNG, and generator state inside a stage.
- [ ] Three-seed median selection is input-order independent and chooses the closest-to-median seed deterministically.
- [ ] Bootstrap is whole-group, 10,000-resample, seed-20260821, and byte-reproducible.
- [ ] Winterreise, RWC-P, GuitarSet, and dataset-macro results are all present.
- [ ] The test receipt prevents a second frozen-test access and binds every identity.
- [ ] Promotion checks every metric, operational constraint, and weight-distribution license; rejection preserves legacy default.
- [ ] C2 skip and failed/non-improving experiments count as honest Plan C outcomes.
- [ ] Existing checkpoint, CPU, class-weight, all-`N/X`, two-track overfit, smoke, legacy-evaluation, and package-boundary tests remain green.
- [ ] No raw data, audio, caches, checkpoints, runs, or model binaries are tracked.
