from __future__ import annotations

import json
from dataclasses import asdict
from types import SimpleNamespace

import numpy as np
import pytest
import torch

import museecho_ml.candidates.btc_inference as btc_inference_module
from museecho_ml.candidates.btc_features import BtcFeatureConfig
from museecho_ml.candidates.btc_inference import BtcRecognizer
from museecho_ml.candidates.btc_labels import decode_btc_class


class _ClassFromFirstFeature(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.call_shapes: list[tuple[int, ...]] = []

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        self.call_shapes.append(tuple(features.shape))
        classes = features[..., 0].round().to(torch.int64)
        logits = torch.zeros((*classes.shape, 170), dtype=torch.float32)
        return logits.scatter(-1, classes.unsqueeze(-1), 2.0)


def _serialized_events(result) -> bytes:
    return json.dumps(
        [asdict(event) for event in result.events],
        sort_keys=True,
        separators=(",", ":"),
        default=lambda value: asdict(value),
    ).encode("utf-8")


def test_btc_inference_chunks_once_discards_padding_and_merges_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = BtcFeatureConfig.official()
    features = np.zeros((110, 144), dtype=np.float32)
    features[:50, 0] = 1
    features[50:, 0] = 169
    monkeypatch.setattr(
        btc_inference_module,
        "extract_btc_features",
        lambda *_args, **_kwargs: features.copy(),
    )
    model = _ClassFromFirstFeature()
    checkpoint = SimpleNamespace(model=model, mean=0.0, std=1.0)
    recognizer = BtcRecognizer(checkpoint, config)
    sample_rate = 1_000
    samples = np.zeros(10_200, dtype=np.float32)
    original_threads = torch.get_num_threads()

    first = recognizer.recognize(samples, sample_rate)
    second = recognizer.recognize(samples, sample_rate)

    expected_confidence = np.exp(2.0) / (np.exp(2.0) + 169)
    assert first.frame_count == 110
    assert model.call_shapes == [(1, 108, 144), (1, 108, 144)] * 2
    assert len(first.events) == 2
    assert first.events[0].chord == decode_btc_class(1)
    assert first.events[1].chord == decode_btc_class(169)
    assert first.events[0].confidence == pytest.approx(expected_confidence)
    assert first.events[-1].end_seconds == pytest.approx(10.2)
    assert all(event.algorithm == "btc-ismir19-large-voca-v1" for event in first.events)
    assert _serialized_events(first) == _serialized_events(second)
    assert first.cpu_seconds >= 0
    assert first.wall_seconds >= 0
    assert torch.get_num_threads() == original_threads
