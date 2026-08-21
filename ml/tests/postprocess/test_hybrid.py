from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from museecho_ml.artifacts import canonical_json_bytes
from museecho_ml.evaluation.metrics import ScoredChordInterval
from museecho_ml.labels import parse_annotation
from museecho_ml.postprocess.events import serialize_events
from museecho_ml.postprocess.hybrid import (
    HybridDecodeConfig,
    HybridFrameProbabilities,
    decode_hybrid,
)
from museecho_ml.vocabulary import BASS_LABELS, ROOT_LABELS, ChordVocabulary

QUALITY_LABELS = (
    "maj",
    "min",
    "7",
    "maj7",
    "min7",
    "dim",
    "hdim7",
    "sus4",
    "N",
    "X",
)
VOCABULARY = ChordVocabulary(ROOT_LABELS, QUALITY_LABELS, BASS_LABELS)
CONFIG = HybridDecodeConfig(
    known_threshold=0.8,
    quality_thresholds=tuple((quality, 0.8) for quality in QUALITY_LABELS[:-2]),
    bass_threshold=0.8,
    minimum_support_fraction=0.5,
    minimum_event_seconds=0.0,
    hysteresis_frames=1,
    maximum_event_ratio=1.5,
)


def _scored(
    start: float, end: float, symbol: str, confidence: float = 0.8
) -> ScoredChordInterval:
    return ScoredChordInterval(start, end, parse_annotation(symbol), confidence)


def _probabilities(labels: tuple[str, ...], value: str, count: int = 4) -> np.ndarray:
    probabilities = np.full((count, len(labels)), 0.001, dtype=np.float64)
    probabilities[:, labels.index(value)] = 0.99
    return probabilities / probabilities.sum(axis=1, keepdims=True)


def _frames(
    *,
    root: str = "D",
    quality: str = "min7",
    bass: str = "b7",
) -> HybridFrameProbabilities:
    return HybridFrameProbabilities(
        frame_times=np.array([0.0, 0.5, 1.0, 1.5], dtype=np.float64),
        valid_mask=np.ones(4, dtype=np.bool_),
        root=_probabilities(ROOT_LABELS, root),
        quality=_probabilities(QUALITY_LABELS, quality),
        bass=_probabilities(BASS_LABELS, bass),
        low_energy_mask=np.zeros(4, dtype=np.bool_),
    )


def test_hybrid_keeps_legacy_root_and_only_overrides_high_confidence_quality() -> None:
    legacy = (_scored(0.0, 2.0, "C:maj"),)
    neural = _frames(root="D", quality="min7", bass="b7")

    result = decode_hybrid(legacy, neural, vocabulary=VOCABULARY, config=CONFIG)

    assert [item.chord.display_symbol for item in result] == ["Cm7/A#"]
    low_quality = np.full_like(neural.quality, 1.0 / neural.quality.shape[1])
    assert decode_hybrid(
        legacy,
        replace(neural, quality=low_quality),
        vocabulary=VOCABULARY,
        config=CONFIG,
    ) == legacy


def test_hybrid_unknown_requires_all_known_gates_and_n_never_becomes_known() -> None:
    unknown = (_scored(0.0, 2.0, "X"),)
    high = _frames(root="G", quality="7", bass="b7")

    restored = decode_hybrid(unknown, high, vocabulary=VOCABULARY, config=CONFIG)

    assert restored[0].chord.display_symbol == "G7/F"
    low_root = np.full_like(high.root, 1.0 / high.root.shape[1])
    assert decode_hybrid(
        unknown,
        replace(high, root=low_root),
        vocabulary=VOCABULARY,
        config=CONFIG,
    ) == unknown
    no_chord = (_scored(0.0, 2.0, "N"),)
    assert decode_hybrid(
        no_chord, high, vocabulary=VOCABULARY, config=CONFIG
    ) == no_chord


def test_hybrid_bass_must_be_a_quality_tone_and_low_energy_falls_back() -> None:
    legacy = (_scored(0.0, 2.0, "C:maj"),)
    illegal_bass = _frames(root="C", quality="maj", bass="b2")

    assert decode_hybrid(
        legacy, illegal_bass, vocabulary=VOCABULARY, config=CONFIG
    ) == legacy
    low_energy = np.ones(4, dtype=np.bool_)
    assert decode_hybrid(
        legacy,
        replace(_frames(), low_energy_mask=low_energy),
        vocabulary=VOCABULARY,
        config=CONFIG,
    ) == legacy


def test_hybrid_merges_identical_legacy_events_and_enforces_event_ratio() -> None:
    legacy = (
        _scored(0.0, 1.0, "C:maj"),
        _scored(1.0, 2.0, "C:maj"),
    )
    fallback = replace(
        _frames(), quality=np.full((4, len(QUALITY_LABELS)), 0.1, dtype=np.float64)
    )

    merged = decode_hybrid(legacy, fallback, vocabulary=VOCABULARY, config=CONFIG)

    assert len(merged) == 1
    assert (merged[0].start_seconds, merged[0].end_seconds) == (0.0, 2.0)
    with pytest.raises(ValueError, match="event-count ratio"):
        decode_hybrid(
            (_scored(0.0, 2.0, "C:maj"),),
            fallback,
            vocabulary=VOCABULARY,
            config=replace(CONFIG, maximum_event_ratio=0.5),
        )


def test_hybrid_replay_is_byte_deterministic() -> None:
    legacy = (_scored(0.0, 2.0, "C:maj"),)
    neural = _frames()

    first = serialize_events(
        decode_hybrid(legacy, neural, vocabulary=VOCABULARY, config=CONFIG)
    )
    second = serialize_events(
        decode_hybrid(legacy, neural, vocabulary=VOCABULARY, config=CONFIG)
    )

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
