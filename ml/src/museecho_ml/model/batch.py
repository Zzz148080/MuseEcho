from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
from torch import Tensor

from museecho_ml.data.manifest import ChordInterval
from museecho_ml.features.cqt import FeatureSequence
from museecho_ml.model.loss import ChordTargets
from museecho_ml.vocabulary import ChordVocabulary


@dataclass(frozen=True)
class TrainingExample:
    features: FeatureSequence
    intervals: tuple[ChordInterval, ...]


@dataclass(frozen=True)
class ModelBatch:
    main: Tensor
    bass: Tensor
    sequence_mask: Tensor
    targets: ChordTargets


def collate_examples(
    examples: tuple[TrainingExample, ...], vocabulary: ChordVocabulary
) -> ModelBatch:
    if not examples:
        raise ValueError("training batch requires at least one example")
    for example in examples:
        _validate_example(example)
    main_bins = examples[0].features.main_cqt.shape[0]
    bass_bins = examples[0].features.bass_cqt.shape[0]
    if any(
        example.features.main_cqt.shape[0] != main_bins
        or example.features.bass_cqt.shape[0] != bass_bins
        for example in examples
    ):
        raise ValueError("training batch feature frequency dimensions must match")
    batch_size = len(examples)
    maximum_frames = max(len(example.features.frame_times) for example in examples)
    main = torch.zeros((batch_size, 1, main_bins, maximum_frames), dtype=torch.float32)
    bass = torch.zeros((batch_size, 1, bass_bins, maximum_frames), dtype=torch.float32)
    sequence_mask = torch.zeros((batch_size, maximum_frames), dtype=torch.bool)
    target_mask = torch.zeros_like(sequence_mask)
    bass_mask = torch.zeros_like(sequence_mask)
    root = torch.zeros((batch_size, maximum_frames), dtype=torch.int64)
    quality = torch.zeros_like(root)
    bass_target = torch.zeros_like(root)
    boundary = torch.zeros((batch_size, maximum_frames), dtype=torch.float32)

    for batch_index, example in enumerate(examples):
        frame_count = len(example.features.frame_times)
        main[batch_index, 0, :, :frame_count] = torch.from_numpy(
            example.features.main_cqt
        )
        bass[batch_index, 0, :, :frame_count] = torch.from_numpy(
            example.features.bass_cqt
        )
        sequence_mask[batch_index, :frame_count] = torch.from_numpy(
            example.features.valid_mask
        )
        interval_index = 0
        previous_labeled_interval: int | None = None
        for frame_index, frame_time in enumerate(example.features.frame_times):
            if not example.features.valid_mask[frame_index]:
                continue
            while (
                interval_index < len(example.intervals)
                and frame_time >= example.intervals[interval_index].end_seconds
            ):
                interval_index += 1
            if interval_index >= len(example.intervals):
                continue
            interval = example.intervals[interval_index]
            if frame_time < interval.start_seconds:
                continue
            encoded = vocabulary.encode(interval.chord)
            root[batch_index, frame_index] = encoded.root
            quality[batch_index, frame_index] = encoded.quality
            bass_target[batch_index, frame_index] = encoded.bass
            target_mask[batch_index, frame_index] = True
            if interval.chord.root not in {"N", "X"}:
                bass_mask[batch_index, frame_index] = True
            if previous_labeled_interval != interval_index:
                boundary[batch_index, frame_index] = 1.0
            previous_labeled_interval = interval_index

    return ModelBatch(
        main=main,
        bass=bass,
        sequence_mask=sequence_mask,
        targets=ChordTargets(
            root=root,
            quality=quality,
            bass=bass_target,
            boundary=boundary,
            mask=target_mask,
            bass_mask=bass_mask,
        ),
    )


def _validate_example(example: TrainingExample) -> None:
    features = example.features
    frame_count = len(features.frame_times)
    if (
        features.main_cqt.dtype != np.float32
        or features.bass_cqt.dtype != np.float32
        or features.frame_times.dtype != np.float64
        or features.valid_mask.dtype != np.bool_
        or features.main_cqt.ndim != 2
        or features.bass_cqt.ndim != 2
        or features.frame_times.ndim != 1
        or features.valid_mask.ndim != 1
        or features.main_cqt.shape[1] != frame_count
        or features.bass_cqt.shape[1] != frame_count
        or len(features.valid_mask) != frame_count
        or frame_count == 0
    ):
        raise ValueError("training example feature axes or dtypes are invalid")
    if (
        not np.isfinite(features.main_cqt).all()
        or not np.isfinite(features.bass_cqt).all()
        or not np.isfinite(features.frame_times).all()
        or np.any(np.diff(features.frame_times) <= 0)
    ):
        raise ValueError("training example features and times must be finite and ordered")
    if not features.valid_mask.any() or np.any(
        np.maximum.accumulate(~features.valid_mask) & features.valid_mask
    ):
        raise ValueError("training example valid mask must be non-empty and prefix-contiguous")
    previous_end = 0.0
    for interval in example.intervals:
        if (
            interval.start_seconds < previous_end
            or interval.start_seconds >= interval.end_seconds
        ):
            raise ValueError("training example intervals must be ordered and non-overlapping")
        previous_end = interval.end_seconds
