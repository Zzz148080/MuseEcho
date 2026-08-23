from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import torch
from numpy.typing import NDArray

from museecho_ml.candidates.btc_checkpoint import BtcCheckpoint
from museecho_ml.candidates.btc_features import (
    BtcFeatureConfig,
    extract_btc_features,
    standardize_btc_features,
)
from museecho_ml.candidates.btc_labels import frames_to_intervals
from museecho_ml.labels import CanonicalChord

BTC_ALGORITHM = "btc-ismir19-large-voca-v1"


@dataclass(frozen=True)
class BtcEvent:
    start_seconds: float
    end_seconds: float
    chord: CanonicalChord
    confidence: float
    algorithm: str = BTC_ALGORITHM


@dataclass(frozen=True)
class BtcInferenceResult:
    events: tuple[BtcEvent, ...]
    cpu_seconds: float
    wall_seconds: float
    frame_count: int


class BtcRecognizer:
    def __init__(
        self,
        checkpoint: BtcCheckpoint,
        feature_config: BtcFeatureConfig | None = None,
    ) -> None:
        self.checkpoint = checkpoint
        self.feature_config = feature_config or BtcFeatureConfig.official()

    def recognize(
        self,
        samples: NDArray[np.float32],
        sample_rate: int,
    ) -> BtcInferenceResult:
        started_cpu = time.process_time()
        started_wall = time.perf_counter()
        if (
            not isinstance(samples, np.ndarray)
            or samples.ndim != 1
            or samples.dtype != np.float32
            or samples.size == 0
            or not np.isfinite(samples).all()
            or type(sample_rate) is not int
            or sample_rate <= 0
        ):
            raise ValueError("BTC inference audio must be finite mono float32 samples")
        duration_seconds = samples.size / sample_rate
        features = extract_btc_features(samples, sample_rate, self.feature_config)
        normalized = standardize_btc_features(
            features,
            self.checkpoint.mean,
            self.checkpoint.std,
        )

        previous_threads = torch.get_num_threads()
        previous_deterministic = torch.are_deterministic_algorithms_enabled()
        try:
            torch.set_num_threads(1)
            torch.use_deterministic_algorithms(True)
            logits = self._predict_chunks(normalized)
            probabilities = torch.softmax(logits, dim=-1)
            classes = probabilities.argmax(dim=-1).cpu().numpy()
            confidences = probabilities.max(dim=-1).values.cpu().numpy()
        finally:
            torch.use_deterministic_algorithms(previous_deterministic)
            torch.set_num_threads(previous_threads)

        intervals = frames_to_intervals(
            classes,
            confidences,
            self.feature_config.frame_seconds,
            duration_seconds,
        )
        events = tuple(
            BtcEvent(
                start_seconds=interval.start_seconds,
                end_seconds=interval.end_seconds,
                chord=interval.chord,
                confidence=interval.confidence,
            )
            for interval in intervals
        )
        return BtcInferenceResult(
            events=events,
            cpu_seconds=time.process_time() - started_cpu,
            wall_seconds=time.perf_counter() - started_wall,
            frame_count=len(classes),
        )

    def _predict_chunks(self, features: NDArray[np.float32]) -> torch.Tensor:
        model = self.checkpoint.model
        if any(parameter.device.type != "cpu" for parameter in model.parameters()):
            raise ValueError("BTC inference model must remain on CPU")
        frame_count = features.shape[0]
        timestep = self.feature_config.timestep
        padding = (-frame_count) % timestep
        padded = (
            np.pad(features, ((0, padding), (0, 0)), mode="constant")
            if padding
            else features
        )
        tensor = torch.from_numpy(np.ascontiguousarray(padded)).unsqueeze(0)
        outputs: list[torch.Tensor] = []
        with torch.inference_mode():
            for start in range(0, padded.shape[0], timestep):
                logits = model(tensor[:, start : start + timestep, :])
                if logits.shape != (1, timestep, 170) or not torch.isfinite(logits).all():
                    raise RuntimeError("BTC model returned invalid logits")
                outputs.append(logits.squeeze(0).cpu())
        return torch.cat(outputs, dim=0)[:frame_count]
