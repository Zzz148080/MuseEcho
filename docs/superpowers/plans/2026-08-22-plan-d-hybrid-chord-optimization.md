# Plan D 混合和弦优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在完全封存 Plan C 测试集的前提下，先定位失败原因，再实现以 legacy 根音和边界为基础、由神经网络高置信度修正 quality/bass 的确定性混合识别器，并依据验证集门禁决定是否进行重平衡训练。

**Architecture:** Plan D 复用现有 `ScoredChordInterval`、`RawTrackPrediction`、`ChordVocabulary` 和 Plan C checkpoint 接口。新增三条隔离边界：开发清单加载器永久拒绝 test，诊断模块只生成无路径聚合证据，混合解码器以 legacy 时间线为权威并对神经覆盖执行精度优先门禁。只有 replay 产生可验证增益时，才启用分层损失、均衡采样和确定性合成域增强。

**Tech Stack:** Python 3.12、dataclasses、NumPy 2.x、PyTorch 2.8+、pytest 9、Ruff 0.16、现有 MuseEcho CQT/CRNN/评估与 immutable JSON 基础设施。

**Spec:** `docs/superpowers/specs/2026-08-22-plan-d-hybrid-chord-optimization-design.md`

## Global Constraints

- 禁止读取、解析或重新授权 Plan C test manifest；测试 SHA-256 固定为 `06b92ce1bd46a1c432cefb9fe32f641095cfb081ac998e7772a66c20a686cddc`。
- 允许开发使用的 split 只有 `train`、`calibration` 和 `validation`。
- Plan C 协议、词表、selection、receipt、promotion 和实验报告不可修改。
- `chroma-triad-viterbi-v1` 在新 test v2 promotion 通过前保持产品默认算法。
- 不下载新数据、不接受新许可证、不使用付费算力、不发布模型权重。
- 原始音频、logits、checkpoint、cache 和 run 输出只能位于 Git 忽略路径；提交的 JSON 必须无本地路径并带 canonical SHA-256。
- replay 阶段不得修改训练代码；只有 `advance-to-retraining` 决策通过后才执行训练任务。
- 所有代码改动先写失败测试，再做最小实现；每个任务单独提交。
- Windows 上涉及 `librosa`/`soxr` 的完整 ML 测试若在沙箱阻塞，使用已批准的非沙箱 pytest 前缀运行；不得以超时代替结果。

---

## 文件职责图

| 文件 | 单一职责 |
| --- | --- |
| `ml/src/museecho_ml/data/plan_d.py` | 加载并校验 Plan D 协议和开发清单，拒绝任何 test 身份 |
| `ml/src/museecho_ml/diagnostics/plan_d.py` | 计算对齐、混淆、事件数、类别支持和 seed/domain 诊断 |
| `ml/src/museecho_ml/postprocess/hybrid.py` | 纯函数式 legacy-rooted hybrid 解码 |
| `ml/src/museecho_ml/postprocess/hybrid_calibration.py` | 精度优先的全局/逐 quality 阈值拟合 |
| `ml/src/museecho_ml/evaluation/plan_d.py` | validation replay、指标聚合、bootstrap 和开发门禁 |
| `ml/src/museecho_ml/model/plan_d_loss.py` | known/N/X 分层损失和 effective-number 权重 |
| `ml/src/museecho_ml/features/domain_augment.py` | 仅 synthetic-supervised 使用的确定性音频域增强 |
| `ml/src/museecho_ml/training/plan_d_sampling.py` | 数据集/quality 均衡且可复现的训练采样 |
| `ml/src/museecho_ml/training/plan_d.py` | replay 决策约束下的三 seed Plan D 训练入口 |
| `docs/ml/plan-d/*.json` | 无路径、哈希绑定的协议、审计和开发决策 |
| `docs/ml/MODEL_CARD_PLAN_D.md` | 数据上限、实验结果、限制和 legacy fallback |

### Task 1：冻结 Plan D 协议与 test 拒绝边界

**Files:**
- Create: `ml/src/museecho_ml/data/plan_d.py`
- Create: `ml/tests/data/test_plan_d.py`
- Create: `ml/configs/plan-d-v1.json`
- Create: `docs/ml/plan-d/protocol-v1.json`
- Modify: `ml/tests/data/test_plan_c_artifacts.py`

**Interfaces:**
- Consumes: Plan C `protocol-v1.json`、`selection-v1.json` 和 Plan D 配置。
- Produces: `load_plan_d_protocol(path: Path) -> dict[str, Any]`、`load_plan_d_development_manifest(path: Path, *, expected_split: str, expected_sha256: str, protocol: Mapping[str, Any]) -> dict[str, Any]`、不可变 `plan-d-protocol-v1`。

- [ ] **Step 1: 写出 test 身份在文件读取前被拒绝的失败测试**

```python
def test_plan_d_rejects_test_identity_before_manifest_read(tmp_path: Path) -> None:
    unreadable = tmp_path / "must-not-read.json"
    unreadable.write_text("not-json", encoding="utf-8")
    protocol = _protocol_fixture()

    with pytest.raises(ValueError, match="Plan D forbids test split"):
        load_plan_d_development_manifest(
            unreadable,
            expected_split="test",
            expected_sha256=PLAN_C_TEST_MANIFEST_SHA256,
            protocol=protocol,
        )
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/data/test_plan_d.py -q --basetemp "$env:TEMP\plan-d-task1-red" -p no:cacheprovider`

Expected: collection fails with `ModuleNotFoundError: museecho_ml.data.plan_d`.

- [ ] **Step 3: 实现最小 fail-closed 加载器**

```python
PLAN_C_TEST_MANIFEST_SHA256 = (
    "06b92ce1bd46a1c432cefb9fe32f641095cfb081ac998e7772a66c20a686cddc"
)
_DEVELOPMENT_SPLITS = frozenset({"train", "calibration", "validation"})

def load_plan_d_development_manifest(
    path: Path,
    *,
    expected_split: str,
    expected_sha256: str,
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    if expected_split not in _DEVELOPMENT_SPLITS:
        raise ValueError("Plan D forbids test split")
    if expected_sha256 == PLAN_C_TEST_MANIFEST_SHA256:
        raise ValueError("Plan D forbids the Plan C test manifest")
    allowed = protocol["development_splits"][expected_split]["manifest_sha256"]
    if expected_sha256 != allowed:
        raise ValueError("Plan D development manifest identity drift")
    if file_sha256(path) != expected_sha256:
        raise ValueError("Plan D development manifest SHA-256 mismatch")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("split") != expected_split:
        raise ValueError("Plan D development manifest split drift")
    return payload
```

- [ ] **Step 4: 增加协议/config 字段和 canonical hash 测试**

`ml/configs/plan-d-v1.json` 必须固定：三个 seed、10,000 次 cover-group bootstrap、
replay continuation gate、完整 development gate、event ratio `[0.75, 1.50]`、CPU 15 秒上限，
以及 Plan C train/calibration/validation SHA。`docs/ml/plan-d/protocol-v1.json` 还要绑定
Plan C protocol、selection、vocabulary、selected checkpoint 和 legacy algorithm SHA/版本。

```python
def test_plan_d_protocol_excludes_test_and_binds_plan_c() -> None:
    payload = _read_plan_d("protocol-v1.json")
    assert set(payload["development_splits"]) == {
        "train", "calibration", "validation"
    }
    assert "test" not in canonical_json_bytes(payload).decode("utf-8")
    body = dict(payload)
    embedded = body.pop("protocol_sha256")
    assert canonical_sha256(body) == embedded
```

- [ ] **Step 5: 运行 Task 1 测试**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/data/test_plan_d.py tests/data/test_plan_c_artifacts.py -q --basetemp "$env:TEMP\plan-d-task1-green" -p no:cacheprovider`

Expected: PASS；测试源代码不得导入 `FrozenTestSession` 或 `open_frozen_test_session`。

- [ ] **Step 6: 提交协议边界**

```powershell
git add ml/src/museecho_ml/data/plan_d.py ml/tests/data/test_plan_d.py ml/configs/plan-d-v1.json docs/ml/plan-d/protocol-v1.json ml/tests/data/test_plan_c_artifacts.py
git commit -m "feat: freeze plan d development boundary"
```

### Task 2：实现对齐、类别与事件失败审计

**Files:**
- Create: `ml/src/museecho_ml/diagnostics/__init__.py`
- Create: `ml/src/museecho_ml/diagnostics/plan_d.py`
- Create: `ml/tests/diagnostics/test_plan_d.py`

**Interfaces:**
- Consumes: `RawTrackPrediction`、`ScoredChordInterval`、`ChordVocabulary`。
- Produces: `PlanDAuditTrack`、`audit_frame_alignment()`、`build_plan_d_failure_audit()`，返回 schema `plan-d-failure-audit-v1` 的可哈希字典。

- [ ] **Step 1: 写对齐和持续时间加权混淆矩阵失败测试**

```python
def test_audit_finds_boundary_offset_and_duration_weighted_quality_confusion() -> None:
    track = _audit_track(
        frame_times=np.array([0.0, 0.5, 1.0, 1.5]),
        reference=(interval(0.0, 1.0, "C:maj"), interval(1.0, 2.0, "D:min")),
        prediction=(interval(0.0, 1.5, "C:maj"), interval(1.5, 2.0, "D:maj")),
    )
    report = build_plan_d_failure_audit((track,), supported_qualities=("maj", "min"))
    assert report["alignment"]["maximum_boundary_frame_error_seconds"] == 0.0
    assert report["quality_confusion_seconds"]["min"]["maj"] == 0.5
    assert report["event_counts"] == {
        "prediction": 2, "reference": 2, "ratio": 1.0
    }
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/diagnostics/test_plan_d.py -q --basetemp "$env:TEMP\plan-d-task2-red" -p no:cacheprovider`

Expected: FAIL because diagnostics module is absent.

- [ ] **Step 3: 定义最小审计类型与函数**

```python
@dataclass(frozen=True)
class PlanDAuditTrack:
    track_id: str
    dataset_id: str
    cover_group_id: str
    split: str
    duration_seconds: float
    frame_times: NDArray[np.float64]
    reference: tuple[ScoredChordInterval, ...]
    prediction: tuple[ScoredChordInterval, ...]

def audit_frame_alignment(
    frame_times: NDArray[np.floating],
    reference: Sequence[ScoredChordInterval],
) -> dict[str, float]:
    times = np.asarray(frame_times, dtype=np.float64)
    boundaries = np.asarray(
        sorted({item.start_seconds for item in reference} | {item.end_seconds for item in reference}),
        dtype=np.float64,
    )
    errors = np.min(np.abs(times[:, None] - boundaries[None, :]), axis=0)
    return {
        "maximum_boundary_frame_error_seconds": float(errors.max(initial=0.0)),
        "mean_boundary_frame_error_seconds": float(errors.mean() if len(errors) else 0.0),
    }

def build_plan_d_failure_audit(
    tracks: Sequence[PlanDAuditTrack],
    *,
    supported_qualities: Sequence[str],
) -> dict[str, Any]:
    validated = _validate_audit_tracks(tracks, supported_qualities)
    body = {
        "schema_version": 1,
        "audit_version": "plan-d-failure-audit-v1",
        "alignment": _aggregate_alignment(validated),
        "quality_confusion_seconds": _quality_confusion_seconds(validated, supported_qualities),
        "event_counts": _event_count_report(validated),
        "quality_support": _quality_support_report(validated, supported_qualities),
        "datasets": _dataset_reports(validated, supported_qualities),
    }
    return {**body, "audit_sha256": canonical_sha256(body)}
```

实现必须复用 `evaluation.metrics` 的时间线对齐语义，按区间交集秒数累积 root/quality/bass
混淆；按 dataset、cover group 和 seed 分层；拒绝 `split == "test"`、非有限时间、重叠
区间及缺失 group。

- [ ] **Step 4: 增加类别支持、置信度曲线和非法组合测试**

```python
def test_audit_counts_independent_groups_and_rejects_illegal_states() -> None:
    report = build_plan_d_failure_audit(
        (_audit_track(group="g1", quality="min7"), _audit_track(group="g2", quality="min7")),
        supported_qualities=("min7",),
    )
    assert report["quality_support"]["min7"]["cover_groups"] == 2
    with pytest.raises(ValueError, match="illegal chord state"):
        build_plan_d_failure_audit((_illegal_special_mix_track(),), supported_qualities=("maj",))
```

- [ ] **Step 5: 运行诊断测试和 Ruff**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/diagnostics/test_plan_d.py -q --basetemp "$env:TEMP\plan-d-task2-green" -p no:cacheprovider; .\.venv\Scripts\python.exe -m ruff check --no-cache src/museecho_ml/diagnostics tests/diagnostics`

Expected: PASS and `All checks passed!`.

- [ ] **Step 6: 提交诊断核心**

```powershell
git add ml/src/museecho_ml/diagnostics ml/tests/diagnostics
git commit -m "feat: audit plan d chord failures"
```

### Task 3：实现 legacy-rooted hybrid 解码核心

**Files:**
- Create: `ml/src/museecho_ml/postprocess/hybrid.py`
- Create: `ml/tests/postprocess/test_hybrid.py`

**Interfaces:**
- Consumes: legacy `tuple[ScoredChordInterval, ...]`、校准神经逐帧概率、`ChordVocabulary`、`HybridDecodeConfig`。
- Produces: `HybridFrameProbabilities`、`HybridDecodeConfig`、`decode_hybrid() -> tuple[ScoredChordInterval, ...]`。

- [ ] **Step 1: 写 high-confidence quality override 与低置信度 fallback 测试**

```python
def test_hybrid_keeps_legacy_root_and_only_overrides_high_confidence_quality() -> None:
    legacy = (scored(0.0, 2.0, "C:maj", confidence=0.8),)
    neural = frame_probabilities(
        times=[0.0, 0.5, 1.0, 1.5],
        root="D", quality="min7", bass="b7", confidence=0.95,
    )
    result = decode_hybrid(legacy, neural, vocabulary=VOCAB, config=CONFIG)
    assert [item.chord.display_symbol for item in result] == ["Cm7/A#"]

    low = replace(neural, quality_probabilities=low_confidence_quality())
    assert decode_hybrid(legacy, low, vocabulary=VOCAB, config=CONFIG) == legacy
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/postprocess/test_hybrid.py -q --basetemp "$env:TEMP\plan-d-task3-red" -p no:cacheprovider`

Expected: FAIL because `museecho_ml.postprocess.hybrid` is absent.

- [ ] **Step 3: 定义严格类型和主接口**

```python
@dataclass(frozen=True)
class HybridFrameProbabilities:
    frame_times: NDArray[np.float64]
    valid_mask: NDArray[np.bool_]
    root: NDArray[np.float64]
    quality: NDArray[np.float64]
    bass: NDArray[np.float64]
    low_energy_mask: NDArray[np.bool_]

@dataclass(frozen=True)
class HybridDecodeConfig:
    known_threshold: float
    quality_thresholds: tuple[tuple[str, float], ...]
    bass_threshold: float
    minimum_support_fraction: float
    minimum_event_seconds: float
    hysteresis_frames: int
    maximum_event_ratio: float

def decode_hybrid(
    legacy: Sequence[ScoredChordInterval],
    neural: HybridFrameProbabilities,
    *,
    vocabulary: ChordVocabulary,
    config: HybridDecodeConfig,
) -> tuple[ScoredChordInterval, ...]:
    timeline, probabilities = _validated_hybrid_inputs(legacy, neural, vocabulary, config)
    decoded = tuple(
        _decode_legacy_interval(item, probabilities, vocabulary, config)
        for item in timeline
    )
    merged = _merge_adjacent_identical(decoded, config.minimum_event_seconds)
    _require_event_ratio(merged, timeline, config.maximum_event_ratio)
    return merged
```

第一版对每个 legacy 区间聚合其覆盖帧；root 始终来自 legacy。quality 采用持续时间加权
平均概率；未达到 quality 阈值或支持帧比例时完全保留 legacy。bass 只允许以下相对
音程：`maj=(1,3,5)`、`min=(1,b3,5)`、`7=(1,3,5,b7)`、`maj7=(1,3,5,7)`、
`min7=(1,b3,5,b7)`、`dim=(1,b3,b5)`、`hdim7=(1,b3,b5,b7)`、
`sus4=(1,4,5)`。

- [ ] **Step 4: 增加 unknown、bass、合并和事件数量保护测试**

```python
def test_hybrid_unknown_requires_all_known_gates_and_event_ratio_is_bounded() -> None:
    assert decode_hybrid(unknown_legacy(), low_known_frames(), vocabulary=VOCAB, config=CONFIG)[0].chord.root == "X"
    assert decode_hybrid(unknown_legacy(), high_known_frames("G", "7", "b7"), vocabulary=VOCAB, config=CONFIG)[0].chord.display_symbol == "G7/F"
    with pytest.raises(ValueError, match="event-count ratio"):
        decode_hybrid(one_legacy_event(), fragmenting_frames(), vocabulary=VOCAB, config=replace(CONFIG, maximum_event_ratio=1.0))
```

- [ ] **Step 5: 验证确定性序列化**

```python
def test_hybrid_replay_is_byte_deterministic() -> None:
    first = serialize_events(decode_hybrid(LEGACY, NEURAL, vocabulary=VOCAB, config=CONFIG))
    second = serialize_events(decode_hybrid(LEGACY, NEURAL, vocabulary=VOCAB, config=CONFIG))
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
```

- [ ] **Step 6: 运行 hybrid 测试和已有 decoder 回归**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/postprocess/test_hybrid.py tests/postprocess/test_decode.py -q --basetemp "$env:TEMP\plan-d-task3-green" -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 7: 提交解码核心**

```powershell
git add ml/src/museecho_ml/postprocess/hybrid.py ml/tests/postprocess/test_hybrid.py
git commit -m "feat: decode legacy rooted hybrid chords"
```

### Task 4：实现精度优先的 hybrid 校准

**Files:**
- Create: `ml/src/museecho_ml/postprocess/hybrid_calibration.py`
- Create: `ml/tests/postprocess/test_hybrid_calibration.py`

**Interfaces:**
- Consumes: 仅 calibration split 的 `HybridCalibrationSample`。
- Produces: `HybridCalibrationParameters`、`fit_hybrid_calibration()`；逐 quality group 不足时回退全局 threshold。

- [ ] **Step 1: 写逐 quality 支持度与全局回退失败测试**

```python
def test_quality_threshold_requires_independent_group_support() -> None:
    samples = calibration_samples(quality="min7", groups=("g1", "g1", "g2"))
    result = fit_hybrid_calibration(
        samples,
        minimum_precision=0.60,
        minimum_coverage=0.20,
        minimum_quality_groups=3,
    )
    assert result.threshold_for("min7") == result.global_quality_threshold
    assert result.source_for("min7") == "global-insufficient-groups"
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/postprocess/test_hybrid_calibration.py -q --basetemp "$env:TEMP\plan-d-task4-red" -p no:cacheprovider`

Expected: import failure.

- [ ] **Step 3: 实现参数类型和精度优先拟合**

```python
@dataclass(frozen=True)
class HybridCalibrationSample:
    cover_group_id: str
    quality: str
    confidence: float
    correct: bool
    duration_seconds: float

@dataclass(frozen=True)
class HybridCalibrationParameters:
    global_quality_threshold: float
    quality_thresholds: tuple[tuple[str, float], ...]
    quality_threshold_sources: tuple[tuple[str, str], ...]
    known_threshold: float
    bass_threshold: float
    minimum_support_fraction: float

    def threshold_for(self, quality: str) -> float:
        return dict(self.quality_thresholds).get(quality, self.global_quality_threshold)

    def source_for(self, quality: str) -> str:
        return dict(self.quality_threshold_sources).get(
            quality, "global-insufficient-groups"
        )

def fit_hybrid_calibration(
    samples: Sequence[HybridCalibrationSample],
    *,
    minimum_precision: float,
    minimum_coverage: float,
    minimum_quality_groups: int,
) -> HybridCalibrationParameters:
    evidence = _validated_calibration_samples(samples)
    global_threshold = _precision_first_threshold(
        evidence, minimum_precision=minimum_precision, minimum_coverage=minimum_coverage
    )
    thresholds, sources = _quality_thresholds(
        evidence,
        global_threshold=global_threshold,
        minimum_precision=minimum_precision,
        minimum_coverage=minimum_coverage,
        minimum_quality_groups=minimum_quality_groups,
    )
    return HybridCalibrationParameters(
        global_quality_threshold=global_threshold,
        quality_thresholds=thresholds,
        quality_threshold_sources=sources,
        known_threshold=global_threshold,
        bass_threshold=global_threshold,
        minimum_support_fraction=0.60,
    )
```

候选阈值按 `(是否达到 minimum_precision, precision, coverage, exact-duration, threshold)`
字典序确定；只允许 calibration split 输入。`to_dict()`/`from_dict()` 使用
`hybrid-calibration-v1` 和 canonical hash。

- [ ] **Step 4: 增加 split、非有限值、hash drift 与 byte determinism 测试**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/postprocess/test_hybrid_calibration.py tests/postprocess/test_hybrid.py -q --basetemp "$env:TEMP\plan-d-task4-green" -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 5: 提交校准实现**

```powershell
git add ml/src/museecho_ml/postprocess/hybrid_calibration.py ml/tests/postprocess/test_hybrid_calibration.py
git commit -m "feat: calibrate plan d hybrid overrides"
```

### Task 5：实现 validation replay、bootstrap 与开发门禁

**Files:**
- Create: `ml/src/museecho_ml/evaluation/plan_d.py`
- Create: `ml/tests/evaluation/test_plan_d.py`

**Interfaces:**
- Consumes: 同身份的 legacy、deep-only、hybrid validation reports，三个 seed，以及 Plan D gate 配置。
- Produces: `PlanDDevelopmentGates`、`evaluate_plan_d_replay()`、`decide_plan_d_development()`。

- [ ] **Step 1: 写完整门禁边界失败测试**

```python
def test_development_gate_passes_only_at_all_exact_boundaries() -> None:
    decision = decide_plan_d_development(
        legacy=report(exact=0.27, majmin=0.30, boundary=0.40),
        deep_by_seed=three_seed_reports(exact=(0.24, 0.25, 0.26)),
        hybrid_by_seed=three_seed_reports(
            exact=(0.30, 0.32, 0.35), precision=0.60, coverage=0.20,
            boundary=0.40, event_ratio=1.50, dataset_floor_delta=-0.02,
        ),
        gates=GATES,
    )
    assert decision["status"] == "development-candidate-frozen"
    assert all(decision["checks"].values())
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/evaluation/test_plan_d.py -q --basetemp "$env:TEMP\plan-d-task5-red" -p no:cacheprovider`

Expected: import failure.

- [ ] **Step 3: 实现 gate 类型和三状态决策**

```python
@dataclass(frozen=True)
class PlanDDevelopmentGates:
    minimum_exact: float = 0.30
    minimum_exact_gain: float = 0.03
    minimum_known_precision: float = 0.60
    minimum_coverage: float = 0.20
    minimum_event_ratio: float = 0.75
    maximum_event_ratio: float = 1.50
    maximum_dataset_regression: float = 0.02
    maximum_seed_span: float = 0.05
    maximum_cpu_seconds: float = 15.0

def decide_plan_d_development(
    *,
    legacy: Mapping[str, Any],
    deep_by_seed: Sequence[Mapping[str, Any]],
    hybrid_by_seed: Sequence[Mapping[str, Any]],
    gates: PlanDDevelopmentGates,
) -> dict[str, Any]:
    evidence = _validated_three_way_reports(legacy, deep_by_seed, hybrid_by_seed)
    checks = _development_checks(evidence, gates)
    continuation = _replay_continuation_checks(evidence)
    status = (
        "development-candidate-frozen"
        if all(checks.values())
        else "advance-to-retraining"
        if all(continuation.values())
        else "data-first-required"
    )
    body = {"schema_version": 1, "decision_version": "plan-d-development-v1", "status": status, "checks": checks, "continuation_checks": continuation}
    return {**body, "decision_sha256": canonical_sha256(body)}
```

三状态：全部开发门禁通过为 `development-candidate-frozen`；未通过完整门禁但达到 replay
continuation gate 为 `advance-to-retraining`；否则为 `data-first-required`。continuation
gate 固定为：hybrid exact 中位数分别高于 legacy 和 deep-only 至少 0.01、precision 至少
0.40、coverage 至少 0.10、event ratio 位于 `[0.75, 1.50]`，且单数据集回退不超过 0.05。

- [ ] **Step 4: 增加每个 predicate 的参数化失败测试和 test split 拒绝测试**

```python
@pytest.mark.parametrize("field", ALL_DEVELOPMENT_PREDICATES)
def test_each_failed_gate_prevents_candidate_freeze(field: str) -> None:
    decision = decide_plan_d_development(**failed_fixture(field))
    assert decision["status"] != "development-candidate-frozen"

def test_plan_d_replay_rejects_test_track() -> None:
    with pytest.raises(ValueError, match="forbids test split"):
        evaluate_plan_d_replay(
            (_raw_prediction(split="test"),),
            legacy_by_track={"fixture": legacy_fixture()},
            vocabulary=VOCAB,
            calibration=CALIBRATION,
            config=HYBRID_CONFIG,
        )
```

- [ ] **Step 5: 复用 `evaluate_dataset_strata()` 和 `group_bootstrap_ci()` 聚合结果**

每个 variant/seed 输出 dataset、cover-group、aggregate、10,000-resample CI、event ratio、
CPU wall 和全部 identity hash。不能在此模块导入 promotion/FrozenTestSession。

- [ ] **Step 6: 运行评估、统计和 package boundary 回归**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/evaluation/test_plan_d.py tests/evaluation/test_statistics.py tests/test_package_boundary.py -q --basetemp "$env:TEMP\plan-d-task5-green" -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 7: 提交 replay 和门禁**

```powershell
git add ml/src/museecho_ml/evaluation/plan_d.py ml/tests/evaluation/test_plan_d.py
git commit -m "feat: evaluate plan d development gates"
```

### Task 6：运行阶段 0 审计并冻结公开证据

**Files:**
- Modify: `ml/src/museecho_ml/diagnostics/plan_d.py`
- Modify: `ml/tests/diagnostics/test_plan_d.py`
- Create: `docs/ml/plan-d/audit-v1.json`
- Create: `docs/ml/experiments/plan-d-stage-0-audit.json`

**Interfaces:**
- Consumes: 三个 C1 checkpoint 在 calibration/validation 的 raw predictions、相同 split 的 legacy replay；绝不消费 test。
- Produces: `plan-d-failure-audit-v1` 和结构化 `passed`/`defect-found` 决策。

- [ ] **Step 1: 为 CLI 写失败测试**

```python
def test_audit_cli_writes_path_free_immutable_report(tmp_path: Path) -> None:
    result = run_plan_d_audit(FIXTURE_INPUT, tmp_path / "audit.json")
    assert result["status"] == "completed"
    assert "audio_path" not in canonical_json_bytes(result).decode("utf-8")
    assert (tmp_path / "audit.json").exists()
```

- [ ] **Step 2: 实现 CLI 参数和 immutable writer**

CLI 只接受 `--protocol`、`--vocabulary`、`--legacy-predictions`、三个
`--deep-predictions seed=path`、`--split calibration|validation` 和 `--output`；出现 `test`
字符串、Plan C test SHA 或非 development manifest 时在打开 prediction 文件前失败。

- [ ] **Step 3: 运行 calibration/validation 预测收集**

```powershell
cd ml
$seeds = 20260821,20260822,20260823
foreach ($seed in $seeds) {
  .\.venv\Scripts\python.exe -m museecho_ml.evaluation.plan_d collect-deep `
    --protocol ..\docs\ml\plan-d\protocol-v1.json `
    --split calibration `
    --manifest data\manifests\splits-v1\real-gold-calibration.manifest.json `
    --checkpoint "runs\plan-c\C1\$seed\finetune\checkpoint-best.pt" `
    --seed $seed --output "runs\plan-d\stage-0\deep-calibration-$seed.npz"
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
  .\.venv\Scripts\python.exe -m museecho_ml.evaluation.plan_d collect-deep `
    --protocol ..\docs\ml\plan-d\protocol-v1.json `
    --split validation `
    --manifest data\manifests\splits-v1\real-gold-validation.manifest.json `
    --checkpoint "runs\plan-c\C1\$seed\finetune\checkpoint-best.pt" `
    --seed $seed --output "runs\plan-d\stage-0\deep-validation-$seed.npz"
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
}
```

- [ ] **Step 4: 收集相同 validation 身份的 legacy 预测并生成审计**

Run: `cd ml; .\.venv\Scripts\python.exe -m museecho_ml.evaluation.plan_d collect-legacy --protocol ..\docs\ml\plan-d\protocol-v1.json --split validation --manifest data\manifests\splits-v1\real-gold-validation.manifest.json --output runs\plan-d\stage-0\legacy-validation.json`

Run: `cd ml; .\.venv\Scripts\python.exe -m museecho_ml.diagnostics.plan_d --protocol ..\docs\ml\plan-d\protocol-v1.json --legacy-predictions runs\plan-d\stage-0\legacy-validation.json --deep-predictions 20260821=runs\plan-d\stage-0\deep-validation-20260821.npz --deep-predictions 20260822=runs\plan-d\stage-0\deep-validation-20260822.npz --deep-predictions 20260823=runs\plan-d\stage-0\deep-validation-20260823.npz --split validation --output ..\docs\ml\plan-d\audit-v1.json`

- [ ] **Step 5: 审计分支判断**

若状态为 `defect-found`，停止 Task 7，使用 systematic-debugging 对具体标签/时间/指标缺陷
建立 RED 测试、修复、重新生成 audit，且保留原始 defect 证据。只有 audit 状态为
`completed` 且 alignment/identity checks 全部通过，才继续 replay。

- [ ] **Step 6: 运行证据测试并提交**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/diagnostics/test_plan_d.py tests/data/test_plan_d.py -q --basetemp "$env:TEMP\plan-d-task6-green" -p no:cacheprovider`

```powershell
git add ml/src/museecho_ml/diagnostics/plan_d.py ml/tests/diagnostics/test_plan_d.py docs/ml/plan-d/audit-v1.json docs/ml/experiments/plan-d-stage-0-audit.json
git commit -m "docs: record plan d failure audit"
```

### Task 7：执行三 seed hybrid replay 并作首次门禁决策

**Files:**
- Modify: `ml/src/museecho_ml/evaluation/plan_d.py`
- Modify: `ml/tests/evaluation/test_plan_d.py`
- Create: `docs/ml/plan-d/replay-decision-v1.json`
- Create: `docs/ml/experiments/plan-d-D1-seed-20260821.json`
- Create: `docs/ml/experiments/plan-d-D1-seed-20260822.json`
- Create: `docs/ml/experiments/plan-d-D1-seed-20260823.json`

**Interfaces:**
- Consumes: Task 6 ignored raw predictions、Task 4 calibration、Task 3 decoder。
- Produces: 每 seed deep/legacy/hybrid validation report 和 replay decision。

- [ ] **Step 1: 写 replay CLI 的 identity/hash 失败测试**

```python
def test_replay_requires_same_manifest_vocabulary_and_seed_checkpoint() -> None:
    with pytest.raises(ValueError, match="replay identity drift"):
        replay_plan_d_variant(deep=deep_fixture(seed=20260821), legacy=legacy_fixture(), protocol=protocol_with_other_manifest())
```

- [ ] **Step 2: 实现 `replay` 与 `decide` CLI**

`replay` 先在 calibration 上拟合 Task 4 参数，再在 validation 上解码并调用 Task 5 聚合。
CLI 输出 ignored raw report 和 path-free public experiment JSON；`decide` 只读取三个 public
report 并写 immutable replay decision。

- [ ] **Step 3: 对三个 seed 执行 replay**

```powershell
cd ml
$seeds = 20260821,20260822,20260823
foreach ($seed in $seeds) {
  .\.venv\Scripts\python.exe -m museecho_ml.evaluation.plan_d replay `
    --protocol ..\docs\ml\plan-d\protocol-v1.json `
    --seed $seed `
    --deep-calibration "runs\plan-d\stage-0\deep-calibration-$seed.npz" `
    --deep-validation "runs\plan-d\stage-0\deep-validation-$seed.npz" `
    --legacy-validation runs\plan-d\stage-0\legacy-validation.json `
    --run-output "runs\plan-d\D1\$seed\replay.json" `
    --public-output "..\docs\ml\experiments\plan-d-D1-seed-$seed.json"
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
}
.\.venv\Scripts\python.exe -m museecho_ml.evaluation.plan_d decide `
  --protocol ..\docs\ml\plan-d\protocol-v1.json `
  --report ..\docs\ml\experiments\plan-d-D1-seed-20260821.json `
  --report ..\docs\ml\experiments\plan-d-D1-seed-20260822.json `
  --report ..\docs\ml\experiments\plan-d-D1-seed-20260823.json `
  --output ..\docs\ml\plan-d\replay-decision-v1.json
```

- [ ] **Step 4: 按决策执行显式分支**

- `development-candidate-frozen`：跳过 Tasks 8--10，直接进入 Task 11 文档收尾并记录等待 test v2。
- `advance-to-retraining`：继续 Task 8。
- `data-first-required`：跳过 Tasks 8--10，直接进入 Task 11，并记录当前数据不足。

- [ ] **Step 5: 提交 replay 结果**

```powershell
git add ml/src/museecho_ml/evaluation/plan_d.py ml/tests/evaluation/test_plan_d.py docs/ml/plan-d/replay-decision-v1.json docs/ml/experiments/plan-d-D1-seed-*.json
git commit -m "docs: record plan d hybrid replay"
```

### Task 8：实现 known/N/X 分层损失和 effective-number 权重（仅 `advance-to-retraining`）

**Files:**
- Create: `ml/src/museecho_ml/model/plan_d_loss.py`
- Create: `ml/tests/model/test_plan_d_loss.py`

**Interfaces:**
- Consumes: 未修改的 `ChordLogits`、`ChordTargets`。
- Produces: `PlanDLossConfig`、`hierarchical_multitask_loss()`、`effective_number_weights()`。

- [ ] **Step 1: 写 special gate 与 known-only quality loss 失败测试**

```python
def test_hierarchical_loss_separates_known_n_x_and_masks_known_heads() -> None:
    logits, targets = mixed_known_n_x_batch()
    result = hierarchical_multitask_loss(logits, targets, PlanDLossConfig())
    assert torch.isfinite(result.total)
    result.total.backward()
    assert result.gate.item() > 0
    assert result.quality.item() == pytest.approx(expected_known_only_quality_loss())
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/model/test_plan_d_loss.py -q --basetemp "$env:TEMP\plan-d-task8-red" -p no:cacheprovider`

- [ ] **Step 3: 实现三类 gate 与已知帧损失**

```python
known_logit = torch.logsumexp(logits.root[..., :-2], dim=-1, keepdim=True)
gate_logits = torch.cat((known_logit, logits.root[..., -2:]), dim=-1)
gate_targets = torch.where(
    targets.root == root_n_index, 1,
    torch.where(targets.root == root_x_index, 2, 0),
)
gate_loss = F.cross_entropy(gate_logits[valid], gate_targets[valid])
known = valid & (gate_targets == 0)
root_loss = F.cross_entropy(logits.root[known][:, :-2], targets.root[known], weight=weights.root[:-2])
quality_loss = F.cross_entropy(logits.quality[known][:, :-2], targets.quality[known], weight=weights.quality[:-2])
```

保留 bass known mask 和全帧 boundary loss；配置包含 `gate_weight`、四个原有 head 权重、
`effective_beta`、`minimum_class_weight`、`maximum_class_weight`。

- [ ] **Step 4: 实现并测试截断 effective-number 权重**

```python
def effective_number_weights(
    counts: Tensor, *, beta: float, minimum: float, maximum: float
) -> Tensor:
    present = counts > 0
    effective = (1.0 - beta) / (1.0 - torch.pow(beta, counts[present]))
    normalized = effective / effective.mean()
    result = torch.zeros_like(counts, dtype=torch.float32)
    result[present] = normalized.to(torch.float32).clamp(min=minimum, max=maximum)
    return result
```

测试缺失类别权重为 0、present 类均值归一、极少数类不超过 maximum、非有限配置拒绝。

- [ ] **Step 5: 运行 loss 回归和全 N/X batch 测试**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/model/test_plan_d_loss.py tests/model/test_loss.py -q --basetemp "$env:TEMP\plan-d-task8-green" -p no:cacheprovider`

- [ ] **Step 6: 提交分层损失**

```powershell
git add ml/src/museecho_ml/model/plan_d_loss.py ml/tests/model/test_plan_d_loss.py
git commit -m "feat: add plan d hierarchical loss"
```

### Task 9：实现确定性均衡采样和 synthetic-only 域增强（仅 `advance-to-retraining`）

**Files:**
- Create: `ml/src/museecho_ml/features/domain_augment.py`
- Create: `ml/src/museecho_ml/training/plan_d_sampling.py`
- Create: `ml/tests/features/test_domain_augment.py`
- Create: `ml/tests/training/test_plan_d_sampling.py`

**Interfaces:**
- Consumes: train manifest rows、corpus role、音频段、seed。
- Produces: `DomainAugmentConfig`、`augment_synthetic_audio()`、`compute_track_sampling_weights()`、`deterministic_weighted_indices()`。

- [ ] **Step 1: 写 synthetic-only、确定性和有限值失败测试**

```python
def test_domain_augmentation_is_deterministic_and_forbids_real_gold() -> None:
    first = augment_synthetic_audio(AUDIO, 22050, seed=7, corpus_role="synthetic-supervised", config=CONFIG)
    second = augment_synthetic_audio(AUDIO, 22050, seed=7, corpus_role="synthetic-supervised", config=CONFIG)
    np.testing.assert_array_equal(first, second)
    with pytest.raises(ValueError, match="synthetic-supervised"):
        augment_synthetic_audio(AUDIO, 22050, seed=7, corpus_role="real-gold", config=CONFIG)
```

- [ ] **Step 2: 实现音频级 EQ、压缩、噪声和短混响**

只使用 NumPy、有限长度 FIR 和 seeded `np.random.default_rng`。输出 float32、单声道、
长度不变、有限且峰值不超过 1。可选 secondary audio 仅在同为 synthetic-supervised 且
长度一致时按冻结比例混合。

- [ ] **Step 3: 写 group/dataset/quality 权重与可复现采样测试**

```python
def test_balanced_sampler_is_seeded_and_caps_track_ratio() -> None:
    weights = compute_track_sampling_weights(ROWS, maximum_ratio=5.0)
    assert max(weights) / min(value for value in weights if value > 0) <= 5.0
    assert deterministic_weighted_indices(weights, seed=11, batch_index=3, batch_size=8) == deterministic_weighted_indices(weights, seed=11, batch_index=3, batch_size=8)
```

- [ ] **Step 4: 运行增强、采样和现有 augmentation 回归**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/features/test_domain_augment.py tests/features/test_augment.py tests/training/test_plan_d_sampling.py tests/training/test_plan_c.py -q --basetemp "$env:TEMP\plan-d-task9-green" -p no:cacheprovider`

- [ ] **Step 5: 提交增强和采样**

```powershell
git add ml/src/museecho_ml/features/domain_augment.py ml/src/museecho_ml/training/plan_d_sampling.py ml/tests/features/test_domain_augment.py ml/tests/training/test_plan_d_sampling.py
git commit -m "feat: rebalance plan d training data"
```

### Task 10：实现并运行三 seed Plan D 重训（仅 `advance-to-retraining`）

**Files:**
- Create: `ml/src/museecho_ml/training/plan_d.py`
- Create: `ml/tests/training/test_plan_d.py`
- Create: `ml/configs/train-plan-d-v1.json`
- Create: `docs/ml/experiments/plan-d-D2-seed-20260821.json`
- Create: `docs/ml/experiments/plan-d-D2-seed-20260822.json`
- Create: `docs/ml/experiments/plan-d-D2-seed-20260823.json`
- Create: `docs/ml/plan-d/development-decision-v1.json`

**Interfaces:**
- Consumes: Task 7 `advance-to-retraining` SHA、同 seed C1 pretrain checkpoint、Plan D loss/sampler/augmentation。
- Produces: `build_plan_d_stage_identity()`、`run_plan_d_stage()`、三 seed 报告和最终 development decision。

- [ ] **Step 1: 写 replay 授权、same-seed 初始化和 checkpoint identity 失败测试**

```python
def test_plan_d_training_requires_advance_decision_and_same_seed_pretrain() -> None:
    with pytest.raises(ValueError, match="advance-to-retraining"):
        run_plan_d_stage(
            protocol_path=PROTOCOL,
            replay_decision=decision(status="data-first-required"),
            config_path=CONFIG,
            seed=20260821,
            run_dir=RUN_DIR,
            initialization_checkpoint_path=checkpoint(seed=20260821),
        )
    with pytest.raises(ValueError, match="same-seed C1 pretrain"):
        run_plan_d_stage(
            protocol_path=PROTOCOL,
            replay_decision=decision(status="advance-to-retraining"),
            config_path=CONFIG,
            seed=20260821,
            run_dir=RUN_DIR,
            initialization_checkpoint_path=checkpoint(seed=20260822),
        )
```

- [ ] **Step 2: 实现 runner 并复用 checkpoint-v2 精确恢复**

runner 把 protocol、replay decision、loss config、sampling artifact、augmentation config、
seed、train/validation manifest 和 initialization checkpoint SHA 全部写入
`CheckpointIdentity.run_config_sha256`。逐步解冻固定为：epoch 0--1 只训练 heads；epoch
2--3 解冻 GRU；epoch 4 起解冻 CQT 两个 encoder。恢复时 epoch 与可训练参数集合必须一致。

- [ ] **Step 3: 运行 runner 单元、resume、CPU smoke 与两首 overfit**

Run: `cd ml; .\.venv\Scripts\python.exe -m pytest tests/training/test_plan_d.py tests/training/test_checkpoint.py tests/training/test_seed.py tests/training/test_train.py -q --basetemp "$env:TEMP\plan-d-task10-runner" -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 4: 执行三个 seed 训练**

```powershell
cd ml
$seeds = 20260821,20260822,20260823
foreach ($seed in $seeds) {
  .\.venv\Scripts\python.exe -m museecho_ml.training.plan_d `
    --protocol ..\docs\ml\plan-d\protocol-v1.json `
    --replay-decision ..\docs\ml\plan-d\replay-decision-v1.json `
    --config configs\train-plan-d-v1.json `
    --seed $seed `
    --initial-checkpoint "runs\plan-c\C1\$seed\pretrain\checkpoint-best.pt" `
    --run-dir "runs\plan-d\D2\$seed\finetune"
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
}
```

- [ ] **Step 5: calibration/validation replay 与最终开发决策**

对三个 D2 checkpoint 重复 Task 6 prediction collection 和 Task 7 replay；输入
`decide_plan_d_development()`。输出只能是 `development-candidate-frozen` 或
`data-first-required`，不能读取 test 或调用 promotion。

- [ ] **Step 6: 提交训练实现和公开结果**

```powershell
git add ml/src/museecho_ml/training/plan_d.py ml/tests/training/test_plan_d.py ml/configs/train-plan-d-v1.json docs/ml/experiments/plan-d-D2-seed-*.json docs/ml/plan-d/development-decision-v1.json
git commit -m "feat: train plan d hybrid refinements"
```

### Task 11：模型卡、实验索引与最终防泄漏验证

**Files:**
- Create: `docs/ml/MODEL_CARD_PLAN_D.md`
- Modify: `docs/ml/experiments/EXPERIMENT_INDEX.md`
- Modify: `ml/tests/data/test_plan_c_artifacts.py`
- Modify: `ml/tests/data/test_plan_d.py`

**Interfaces:**
- Consumes: 实际执行到的 audit、D1 和可选 D2 决策。
- Produces: 诚实的 Plan D 终态说明，不改变产品默认算法。

- [ ] **Step 1: 写文档/产物失败测试**

```python
def test_plan_d_public_evidence_is_hashed_and_never_claims_old_test() -> None:
    for name, hash_field in PLAN_D_PUBLIC_ARTIFACTS:
        payload = _read_plan_d(name)
        body = dict(payload)
        embedded_hash = body.pop(hash_field)
        assert canonical_sha256(body) == embedded_hash
    model_card = (REPOSITORY_ROOT / "docs/ml/MODEL_CARD_PLAN_D.md").read_text("utf-8")
    assert "chroma-triad-viterbi-v1" in model_card
    assert "不重新使用 Plan C test" in model_card
```

- [ ] **Step 2: 更新中文模型卡和实验索引**

必须记录：数据上限、Stage 0 结论、D1/D2 实际运行或结构化跳过、三 seed 范围、各数据集
结果、precision/coverage、event ratio、CPU、终态、旧 test 封存和新 test v2 需求。没有
达到 0.30 时明确写 `data-first-required`，不得使用“接近生产可用”等措辞。

- [ ] **Step 3: 运行完整 ML 测试**

Run: `cd ml; $fullTemp = Join-Path ([System.IO.Path]::GetTempPath()) "museecho-plan-d-full-$PID"; .\.venv\Scripts\python.exe -m pytest -q --basetemp $fullTemp -p no:cacheprovider`

Expected: all collected tests pass. If sandbox stalls at CQT/soxr, rerun the identical command using the approved non-sandbox pytest prefix and report that environmental distinction.

- [ ] **Step 4: 运行 Ruff 与 legacy runtime 回归**

Run: `cd ml; .\.venv\Scripts\python.exe -m ruff check --no-cache src tests`

Run: `cd ..; .\.venv\Scripts\python.exe -m pytest tests\unit\analysis\test_chords.py -q --basetemp "$env:TEMP\plan-d-runtime" -p no:cacheprovider`

Expected: Ruff clean；legacy runtime 32 tests pass；产品默认仍为 `chroma-triad-viterbi-v1`。

- [ ] **Step 5: 检查追踪边界和工作区**

```powershell
git diff --check
git check-ignore ml/data ml/runs ml/checkpoints
git ls-files ml | Where-Object { $_ -match '\.(pt|pth|ckpt|onnx|wav|mp3|flac|ogg|m4a|zip|tar|gz|7z)$' }
git status --short
```

Expected: binary query returns empty；`ml/data` 和 `ml/runs` ignored；只有计划内代码、测试、
配置和 path-free JSON 等待提交。

- [ ] **Step 6: 提交 Plan D 终态证据**

```powershell
git add docs/ml/MODEL_CARD_PLAN_D.md docs/ml/experiments/EXPERIMENT_INDEX.md docs/ml/plan-d docs/ml/experiments/plan-d-*.json ml/tests/data/test_plan_c_artifacts.py ml/tests/data/test_plan_d.py
git commit -m "docs: record plan d development result"
git status --short
git log -5 --oneline
```

---

## 最终验收清单

- [ ] Plan D 所有入口在读取文件前拒绝 `test` 和 Plan C test SHA。
- [ ] Plan C 冻结证据字节可解释，receipt 仍为 consumed，promotion 仍为 rejected。
- [ ] Stage 0 对齐、标签、混淆、事件数、类别支持、seed 和 dataset 诊断已形成哈希证据。
- [ ] hybrid root 与初始边界来自 legacy，低置信度 quality/bass 必然 fallback。
- [ ] bass 只能发布合法和弦音或批准的转位音。
- [ ] per-quality threshold 缺少独立 group 时必然回退全局 threshold。
- [ ] replay 对三个 C1 seed 使用相同 calibration/validation 身份，排序与输入顺序无关。
- [ ] 只有 `advance-to-retraining` 才能执行 Plan D loss、sampling、augmentation 和 runner。
- [ ] hierarchical loss 将 known/N/X gate 与 known-only root/quality/bass loss 分离。
- [ ] synthetic 域增强可复现且拒绝 real-gold 输入。
- [ ] D2 如执行则具备精确 checkpoint resume、三 seed、CPU smoke 和 overfit 证据。
- [ ] 终态只能是 `development-candidate-frozen`、`data-first-required` 或明确授权 blocker。
- [ ] 没有新 test v2 就不得 promotion，产品默认算法保持 legacy。
- [ ] 全量 ML pytest、Ruff 和 legacy runtime 回归通过。
- [ ] Git 不追踪数据、音频、checkpoint、run、cache 或模型二进制。
