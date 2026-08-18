from __future__ import annotations

import numpy as np
import torch

from museecho_ml.data.manifest import ChordInterval
from museecho_ml.features.cqt import FeatureSequence
from museecho_ml.labels import parse_annotation
from museecho_ml.model.batch import TrainingExample, collate_examples
from museecho_ml.vocabulary import ChordVocabulary


def _features(times: list[float], valid: list[bool]) -> FeatureSequence:
    frames = len(times)
    return FeatureSequence(
        main_cqt=np.ones((6, frames), dtype=np.float32),
        bass_cqt=np.ones((3, frames), dtype=np.float32),
        frame_times=np.asarray(times, dtype=np.float64),
        valid_mask=np.asarray(valid, dtype=np.bool_),
    )


def test_collate_pads_variable_sequences_and_aligns_half_open_intervals() -> None:
    examples = (
        TrainingExample(
            features=_features([0.0, 0.1, 0.2, 0.3], [True, True, True, True]),
            intervals=(
                ChordInterval(0.1, 0.2, parse_annotation("C:maj/3")),
                ChordInterval(0.2, 0.4, parse_annotation("D:min")),
            ),
        ),
        TrainingExample(
            features=_features([0.0, 0.1, 0.2], [True, True, False]),
            intervals=(ChordInterval(0.0, 0.2, parse_annotation("N")),),
        ),
    )

    batch = collate_examples(examples, ChordVocabulary.default())

    assert batch.main.shape == (2, 1, 6, 4)
    assert batch.bass.shape == (2, 1, 3, 4)
    torch.testing.assert_close(
        batch.sequence_mask,
        torch.tensor(
            [[True, True, True, True], [True, True, False, False]], dtype=torch.bool
        ),
    )
    torch.testing.assert_close(
        batch.targets.mask,
        torch.tensor(
            [[False, True, True, True], [True, True, False, False]], dtype=torch.bool
        ),
    )
    vocabulary = ChordVocabulary.default()
    c_major = vocabulary.encode(parse_annotation("C:maj/3"))
    d_minor = vocabulary.encode(parse_annotation("D:min"))
    assert batch.targets.root[0].tolist() == [0, c_major.root, d_minor.root, d_minor.root]
    assert batch.targets.quality[0].tolist() == [
        0,
        c_major.quality,
        d_minor.quality,
        d_minor.quality,
    ]
    assert batch.targets.bass[0].tolist() == [0, c_major.bass, d_minor.bass, d_minor.bass]
    assert batch.targets.boundary[0].tolist() == [0.0, 1.0, 1.0, 0.0]
    assert batch.targets.bass_mask[0].tolist() == [False, True, True, True]
    assert batch.targets.bass_mask[1].tolist() == [False, False, False, False]


def test_collate_outputs_finite_float32_model_inputs() -> None:
    example = TrainingExample(
        features=_features([0.0, 0.1], [True, True]),
        intervals=(ChordInterval(0.0, 0.2, parse_annotation("G:7")),),
    )

    batch = collate_examples((example,), ChordVocabulary.default())

    assert batch.main.dtype == torch.float32
    assert batch.bass.dtype == torch.float32
    assert torch.isfinite(batch.main).all()
    assert torch.isfinite(batch.bass).all()
