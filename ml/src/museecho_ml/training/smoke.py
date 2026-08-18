from __future__ import annotations

import argparse
import json
import math
import wave
from pathlib import Path
from typing import Any

import numpy as np
import torch

from museecho_ml.data.manifest import ChordInterval
from museecho_ml.features.cqt import CqtConfig, extract_features
from museecho_ml.labels import CanonicalChord
from museecho_ml.model.batch import TrainingExample, collate_examples
from museecho_ml.model.crnn import ChordCrnn, CrnnConfig
from museecho_ml.model.loss import LossConfig, multitask_loss
from museecho_ml.training.trainer import (
    TrainerConfig,
    TrainingState,
    build_optimizer,
    configure_cpu_reproducibility,
    load_checkpoint,
    save_checkpoint,
    train_step,
)
from museecho_ml.vocabulary import ChordVocabulary


def run_two_track_overfit(
    manifest_path: Path,
    dataset_root: Path,
    checkpoint_path: Path,
    *,
    steps: int = 80,
    segment_seconds: float = 4.0,
    seed: int = 20260818,
) -> dict[str, Any]:
    """Overfit two real manifest tracks and verify a resumable CPU checkpoint."""

    if type(steps) is not int or steps <= 0:
        raise ValueError("overfit steps must be a positive integer")
    if not math.isfinite(segment_seconds) or segment_seconds <= 0:
        raise ValueError("overfit segment_seconds must be finite and positive")
    configure_cpu_reproducibility(seed)
    track_ids, examples = _load_examples(
        manifest_path, dataset_root, limit=2, segment_seconds=segment_seconds
    )
    batch = collate_examples(examples, ChordVocabulary.default())
    model = ChordCrnn(
        CrnnConfig(
            main_conv_channels=(4,),
            bass_conv_channels=(4,),
            gru_hidden_size=12,
            gru_layers=1,
            dropout=0.0,
        )
    )
    trainer_config = TrainerConfig(learning_rate=0.01, weight_decay=0.0)
    loss_config = LossConfig()
    optimizer = build_optimizer(model, trainer_config)
    initial_loss = _evaluate(model, batch, loss_config)
    last_metrics: dict[str, float] | None = None
    for _ in range(steps):
        last_metrics = train_step(
            model,
            batch,
            optimizer,
            loss_config=loss_config,
            trainer_config=trainer_config,
            device=torch.device("cpu"),
        )
    final_loss = _evaluate(model, batch, loss_config)
    save_checkpoint(
        checkpoint_path,
        model,
        optimizer,
        TrainingState(epoch=0, step_in_epoch=steps, global_step=steps),
        trainer_config=trainer_config,
        loss_config=loss_config,
    )
    restored_model = ChordCrnn(model.config)
    restored_optimizer = build_optimizer(restored_model, trainer_config)
    restored_state = load_checkpoint(
        checkpoint_path,
        restored_model,
        restored_optimizer,
        trainer_config=trainer_config,
        loss_config=loss_config,
    )
    restored_loss = _evaluate(restored_model, batch, loss_config)
    if not math.isclose(final_loss, restored_loss, rel_tol=0, abs_tol=1e-7):
        raise RuntimeError("CPU smoke checkpoint did not restore identical loss")
    assert last_metrics is not None
    return {
        "schema_version": 1,
        "track_ids": list(track_ids),
        "steps": steps,
        "initial_loss": initial_loss,
        "final_loss": final_loss,
        "loss_ratio": final_loss / initial_loss,
        "restored_loss": restored_loss,
        "restored_global_step": restored_state.global_step,
        "last_gradient_norm": last_metrics["gradient_norm"],
        "checkpoint_path": str(checkpoint_path.resolve(strict=True)),
    }


def _evaluate(model: ChordCrnn, batch: Any, loss_config: LossConfig) -> float:
    model.eval()
    with torch.no_grad():
        logits = model(batch.main, batch.bass, batch.sequence_mask)
        value = float(multitask_loss(logits, batch.targets, loss_config).total)
    if not math.isfinite(value):
        raise RuntimeError("CPU smoke loss is not finite")
    return value


def _load_examples(
    manifest_path: Path,
    dataset_root: Path,
    *,
    limit: int,
    segment_seconds: float,
) -> tuple[tuple[str, ...], tuple[TrainingExample, ...]]:
    root = dataset_root.resolve(strict=True)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    tracks = payload.get("tracks") if isinstance(payload, dict) else None
    if not isinstance(tracks, list) or len(tracks) < limit:
        raise ValueError("overfit manifest does not contain two tracks")
    identifiers: list[str] = []
    examples: list[TrainingExample] = []
    for track in tracks[:limit]:
        if not isinstance(track, dict) or not isinstance(track.get("track_id"), str):
            raise ValueError("overfit manifest track is invalid")
        audio_path = (root / str(track.get("audio_path"))).resolve(strict=True)
        if not audio_path.is_relative_to(root) or not audio_path.is_file():
            raise ValueError("overfit audio path escapes the dataset root")
        audio, sample_rate = _read_wav_prefix(audio_path, segment_seconds)
        features = extract_features(audio, sample_rate=sample_rate, config=CqtConfig())
        duration = min(segment_seconds, len(audio) / sample_rate)
        intervals = _manifest_intervals(track.get("intervals"), duration)
        identifiers.append(track["track_id"])
        examples.append(TrainingExample(features, intervals))
    return tuple(identifiers), tuple(examples)


def _read_wav_prefix(path: Path, seconds: float) -> tuple[np.ndarray, int]:
    try:
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            if channels <= 0 or sample_width != 2 or sample_rate <= 0:
                raise ValueError("CPU smoke requires 16-bit PCM WAV audio")
            frame_count = min(source.getnframes(), math.ceil(seconds * sample_rate))
            samples = np.frombuffer(source.readframes(frame_count), dtype="<i2")
    except (EOFError, wave.Error) as error:
        raise ValueError(f"CPU smoke WAV is unreadable: {path.name}") from error
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)
    return np.ascontiguousarray(samples), sample_rate


def _manifest_intervals(value: object, duration: float) -> tuple[ChordInterval, ...]:
    if not isinstance(value, list):
        raise ValueError("overfit manifest intervals are invalid")
    intervals: list[ChordInterval] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("overfit manifest interval is invalid")
        start = float(item["start_seconds"])
        end = min(float(item["end_seconds"]), duration)
        if start >= duration:
            break
        if end <= start:
            continue
        intervals.append(
            ChordInterval(
                start,
                end,
                CanonicalChord(
                    str(item["root"]),
                    str(item["quality"]),
                    str(item["bass"]),
                    item.get("mapping_reason"),
                ),
            )
        )
    if not intervals:
        raise ValueError("overfit segment does not contain chord labels")
    return tuple(intervals)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run two-track overfit and CPU smoke")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=80)
    parser.add_argument("--segment-seconds", type=float, default=4.0)
    args = parser.parse_args()
    report = run_two_track_overfit(
        args.manifest,
        args.dataset_root,
        args.checkpoint,
        steps=args.steps,
        segment_seconds=args.segment_seconds,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
