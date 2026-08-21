from __future__ import annotations

import numpy as np

from museecho_ml.artifacts import canonical_json_bytes
from museecho_ml.postprocess.calibration import (
    CalibrationParameters,
    fit_temperature,
    multiclass_nll,
    select_publication_threshold,
)
from museecho_ml.postprocess.decode import (
    _suppress_short_runs,
    decode_logits,
    serialize_events,
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


def _head_logits(labels: tuple[str, ...], values: list[str]) -> np.ndarray:
    logits = np.full((len(values), len(labels)), -8.0, dtype=np.float64)
    for index, value in enumerate(values):
        logits[index, labels.index(value)] = 8.0
    return logits


def _parameters(
    *, publication_threshold: float = 0.5, minimum_event_seconds: float = 0.0
) -> CalibrationParameters:
    return CalibrationParameters(
        root_temperature=1.0,
        quality_temperature=1.0,
        bass_temperature=1.0,
        publication_threshold=publication_threshold,
        boundary_threshold=0.5,
        minimum_event_seconds=minimum_event_seconds,
    )


def _decode(
    roots: list[str],
    qualities: list[str],
    *,
    basses: list[str] | None = None,
    frame_times: np.ndarray | None = None,
    duration_seconds: float | None = None,
    parameters: CalibrationParameters | None = None,
    low_energy_mask: np.ndarray | None = None,
    boundary_logits: np.ndarray | None = None,
):
    count = len(roots)
    return decode_logits(
        _head_logits(ROOT_LABELS, roots),
        _head_logits(QUALITY_LABELS, qualities),
        _head_logits(BASS_LABELS, basses or ["1"] * count),
        (
            np.full(count, -8.0, dtype=np.float64)
            if boundary_logits is None
            else boundary_logits
        ),
        (
            np.arange(count, dtype=np.float64) * 0.1
            if frame_times is None
            else frame_times
        ),
        np.ones(count, dtype=np.bool_),
        duration_seconds=0.1 * count if duration_seconds is None else duration_seconds,
        vocabulary=VOCABULARY,
        calibration=parameters or _parameters(),
        low_energy_mask=low_energy_mask,
    )


def test_temperature_fit_reduces_overconfident_negative_log_likelihood() -> None:
    logits = np.asarray([[10.0, 0.0], [10.0, 0.0]], dtype=np.float64)
    targets = np.asarray([0, 1], dtype=np.int64)

    temperature = fit_temperature(logits, targets)

    assert temperature > 1.0
    assert multiclass_nll(logits, targets, temperature=temperature) < multiclass_nll(
        logits, targets, temperature=1.0
    )


def test_publication_threshold_meets_precision_and_coverage_from_durations() -> None:
    threshold = select_publication_threshold(
        confidences=np.asarray([0.95, 0.9, 0.7, 0.4]),
        correct=np.asarray([True, True, False, False]),
        durations=np.asarray([2.0, 2.0, 1.0, 1.0]),
        minimum_precision=0.8,
        minimum_coverage=0.6,
    )

    assert threshold == 0.9


def test_publication_threshold_excludes_special_predictions_from_known_coverage() -> None:
    threshold = select_publication_threshold(
        confidences=np.asarray([0.99, 0.9, 0.7, 0.4]),
        correct=np.asarray([False, True, False, False]),
        durations=np.asarray([1.0, 1.0, 1.0, 1.0]),
        eligible=np.asarray([False, True, True, True]),
        minimum_precision=1.0,
        minimum_coverage=0.25,
    )

    assert threshold == 0.9


def test_conflicting_special_and_acoustic_heads_map_to_x() -> None:
    events = _decode(["C"], ["N"])

    assert events[0].chord.root == "X"
    assert events[0].chord.quality == "X"
    assert events[0].chord.bass == "X"


def test_root_silence_forces_one_n_event() -> None:
    events = _decode(["N", "N"], ["maj", "maj"])

    assert len(events) == 1
    assert events[0].chord.root == "N"
    assert (events[0].start_seconds, events[0].end_seconds) == (0.0, 0.2)


def test_short_jitter_and_same_label_boundary_are_merged_deterministically() -> None:
    events = _decode(
        ["C", "C", "D", "C", "C"],
        ["maj", "maj", "min", "maj", "maj"],
        parameters=_parameters(minimum_event_seconds=0.15),
        boundary_logits=np.asarray([-8.0, -8.0, -8.0, 8.0, -8.0]),
    )

    assert len(events) == 1
    assert events[0].chord.display_symbol == "C"
    assert (events[0].start_seconds, events[0].end_seconds) == (0.0, 0.5)


def test_low_energy_edge_becomes_n_and_final_event_covers_audio_tail() -> None:
    events = _decode(
        ["C", "C", "C"],
        ["maj", "maj", "maj"],
        duration_seconds=0.35,
        low_energy_mask=np.asarray([True, False, False]),
    )

    assert [(event.chord.root, event.start_seconds, event.end_seconds) for event in events] == [
        ("N", 0.0, 0.1),
        ("C", 0.1, 0.35),
    ]


def test_low_confidence_known_state_maps_to_x() -> None:
    root = np.zeros((1, len(ROOT_LABELS)), dtype=np.float64)
    root[0, ROOT_LABELS.index("C")] = 0.1
    events = decode_logits(
        root,
        _head_logits(QUALITY_LABELS, ["maj"]),
        _head_logits(BASS_LABELS, ["1"]),
        np.asarray([-8.0]),
        np.asarray([0.0]),
        np.asarray([True]),
        duration_seconds=0.1,
        vocabulary=VOCABULARY,
        calibration=_parameters(publication_threshold=0.5),
    )

    assert events[0].chord.root == "X"


def test_serialized_events_are_byte_deterministic() -> None:
    events = _decode(["C", "C", "G"], ["maj", "maj", "7"])

    first = serialize_events(events)
    second = serialize_events(events)

    assert canonical_json_bytes(first) == canonical_json_bytes(second)


class _CountingState:
    comparisons = 0

    def __init__(self, label: int) -> None:
        self.label = label

    def __eq__(self, other: object) -> bool:
        type(self).comparisons += 1
        return isinstance(other, _CountingState) and self.label == other.label


def test_short_run_suppression_does_not_rescan_every_frame_per_merge() -> None:
    count = 500
    states = [_CountingState(index % 2) for index in range(count)]
    times = np.arange(count, dtype=np.float64) * 0.05
    _CountingState.comparisons = 0

    result = _suppress_short_runs(
        states,
        np.linspace(0.1, 0.9, count),
        times,
        duration_seconds=count * 0.05,
        minimum_event_seconds=0.1,
    )

    assert len(result) == count
    assert _CountingState.comparisons < count * 20
