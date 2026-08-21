from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from museecho_ml.evaluation.metrics import ScoredChordInterval
from museecho_ml.evaluation.report import EvaluationConfig, evaluate_corpus
from museecho_ml.labels import CanonicalChord, parse_annotation


class LegacyEvent(Protocol):
    symbol: str | None
    start_seconds: float
    end_seconds: float
    confidence: float | None
    algorithm: str


AudioLoader = Callable[[Path], tuple[np.ndarray, int]]
LegacyRecognizer = Callable[[np.ndarray, int], Sequence[LegacyEvent]]
_EVALUATION_SPLITS = ("validation", "test")
_TIMELINE_TOLERANCE_SECONDS = 1e-9


def load_evaluation_config(path: Path) -> EvaluationConfig:
    payload = _read_json(path)
    if payload.get("schema_version") != 1 or payload.get("evaluation_version") != "1.0.0":
        raise ValueError("legacy evaluation requires evaluation-v1 config")
    try:
        return EvaluationConfig(
            boundary_tolerance_seconds=payload["boundary_tolerance_seconds"],
            ece_bin_count=payload["ece_bin_count"],
            publication_threshold=payload["publication_threshold"],
            exact_match_includes_bass=payload["exact_match_includes_bass"],
        )
    except KeyError as error:
        raise ValueError(f"legacy evaluation config missing field: {error.args[0]}") from None


def evaluate_legacy_manifest(
    manifest: dict[str, Any],
    *,
    dataset_roots: Mapping[str, Path],
    config: EvaluationConfig,
    recognize: LegacyRecognizer,
    audio_loader: AudioLoader,
) -> dict[str, Any]:
    """Run the unchanged legacy recognizer over one frozen evaluation manifest."""

    if manifest.get("corpus_role") != "real-gold":
        raise ValueError("legacy evaluation requires a real-gold manifest")
    split_name = manifest.get("split")
    if split_name not in {"validation", "test"}:
        raise PermissionError(f"{split_name or 'unknown'} split is not an evaluation split")
    tracks = manifest.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        raise ValueError("legacy evaluation manifest must contain tracks")

    evaluation_tracks: dict[
        str, tuple[tuple[ScoredChordInterval, ...], tuple[ScoredChordInterval, ...]]
    ] = {}
    predictions: list[dict[str, Any]] = []
    algorithms: set[str] = set()
    resolved_roots = {
        dataset_id: path.resolve(strict=True) for dataset_id, path in dataset_roots.items()
    }
    for track in sorted(tracks, key=lambda item: item.get("track_id", "")):
        if not isinstance(track, dict):
            raise ValueError("legacy evaluation tracks must be objects")
        track_id = track.get("track_id")
        dataset_id = track.get("dataset_id")
        audio_path = track.get("audio_path")
        duration_seconds = track.get("duration_seconds")
        if (
            not isinstance(track_id, str)
            or not track_id.strip()
            or not isinstance(dataset_id, str)
            or not isinstance(audio_path, str)
            or isinstance(duration_seconds, bool)
            or not isinstance(duration_seconds, (int, float))
            or not math.isfinite(duration_seconds)
            or duration_seconds <= 0
        ):
            raise ValueError("legacy evaluation track metadata is invalid")
        root = resolved_roots.get(dataset_id)
        if root is None:
            raise ValueError(f"legacy evaluation is missing dataset root for {dataset_id}")
        resolved_audio = (root / audio_path).resolve(strict=True)
        try:
            resolved_audio.relative_to(root)
        except ValueError:
            raise ValueError(
                "legacy evaluation audio path must remain inside dataset root"
            ) from None
        samples, sample_rate = audio_loader(resolved_audio)
        samples = np.asarray(samples, dtype=np.float32)
        if (
            samples.ndim != 1
            or samples.size == 0
            or type(sample_rate) is not int
            or sample_rate <= 0
        ):
            raise ValueError("legacy audio loader returned invalid samples")
        observed_duration = samples.size / sample_rate
        if not math.isclose(
            observed_duration,
            float(duration_seconds),
            abs_tol=max(0.05, 1 / sample_rate),
        ):
            raise ValueError("legacy audio duration does not match frozen manifest")
        raw_events = tuple(recognize(samples, sample_rate))
        reference = _reference_intervals(track, float(duration_seconds))
        prediction, serialized_events, track_algorithms = _prediction_intervals(
            raw_events, float(duration_seconds)
        )
        algorithms.update(track_algorithms)
        evaluation_tracks[track_id] = (reference, prediction)
        predictions.append({"track_id": track_id, "events": serialized_events})
    if len(algorithms) != 1:
        raise ValueError("legacy evaluation requires one stable algorithm version")
    prediction_hash = _sha256(predictions)
    report = {
        "schema_version": 1,
        "baseline_version": "legacy-baseline-v1",
        "algorithm_version": next(iter(algorithms)),
        "manifest_split": split_name,
        "manifest_sha256": _sha256(manifest),
        "split_sha256": manifest.get("split_sha256"),
        "evaluation": evaluate_corpus(evaluation_tracks, config),
        "predictions_sha256": prediction_hash,
    }
    return {"report": report, "predictions": predictions}


def run_legacy_protocol(
    manifests: Mapping[str, dict[str, Any]],
    *,
    dataset_roots: Mapping[str, Path],
    config: EvaluationConfig,
    source_commit: str,
    environment: Mapping[str, str],
    recognize: LegacyRecognizer,
    audio_loader: AudioLoader,
    predictions_output: Path,
    report_output: Path,
    markdown_output: Path,
) -> dict[str, Any]:
    """Run validation then frozen test and write immutable replayable baseline artifacts."""

    if set(manifests) != set(_EVALUATION_SPLITS):
        raise ValueError("legacy protocol requires validation and test manifests")
    if not isinstance(source_commit, str) or not source_commit.strip():
        raise ValueError("legacy protocol source_commit must be non-empty")
    split_reports: dict[str, dict[str, Any]] = {}
    prediction_rows: list[dict[str, Any]] = []
    algorithms: set[str] = set()
    for split_name in _EVALUATION_SPLITS:
        manifest = manifests[split_name]
        if manifest.get("split") != split_name:
            raise ValueError(f"legacy protocol manifest does not match {split_name}")
        result = evaluate_legacy_manifest(
            manifest,
            dataset_roots=dataset_roots,
            config=config,
            recognize=recognize,
            audio_loader=audio_loader,
        )
        split_reports[split_name] = result["report"]
        algorithms.add(result["report"]["algorithm_version"])
        prediction_rows.extend(
            {"split": split_name, **prediction} for prediction in result["predictions"]
        )
    if len(algorithms) != 1:
        raise ValueError("legacy protocol requires one stable algorithm version")
    predictions_payload = b"".join(
        _compact_json_bytes(row) + b"\n" for row in prediction_rows
    )
    serialized_config = {
        "boundary_tolerance_seconds": config.boundary_tolerance_seconds,
        "ece_bin_count": config.ece_bin_count,
        "publication_threshold": config.publication_threshold,
        "exact_match_includes_bass": config.exact_match_includes_bass,
    }
    report = {
        "schema_version": 1,
        "baseline_version": "legacy-baseline-v1",
        "source_commit": source_commit,
        "algorithm_version": next(iter(algorithms)),
        "environment": dict(sorted(environment.items())),
        "evaluation_config": serialized_config,
        "evaluation_config_sha256": _sha256(serialized_config),
        "predictions_sha256": hashlib.sha256(predictions_payload).hexdigest(),
        "splits": split_reports,
    }
    artifacts = {
        predictions_output: predictions_payload,
        report_output: _pretty_json_bytes(report),
        markdown_output: _markdown_report(report).encode("utf-8"),
    }
    _write_immutable_artifacts(artifacts)
    return report


def replay_legacy_protocol(
    manifests: Mapping[str, dict[str, Any]],
    *,
    predictions_path: Path,
    config: EvaluationConfig,
) -> dict[str, Any]:
    """Recompute every metric from frozen manifests and path-free prediction JSONL."""

    if set(manifests) != set(_EVALUATION_SPLITS):
        raise ValueError("legacy replay requires validation and test manifests")
    try:
        predictions_payload = predictions_path.read_bytes()
        rows = [json.loads(line) for line in predictions_payload.splitlines() if line]
    except (OSError, json.JSONDecodeError):
        raise ValueError("legacy prediction JSONL is unreadable") from None
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("legacy prediction JSONL rows must be objects")
        split_name = row.get("split")
        track_id = row.get("track_id")
        if not isinstance(split_name, str) or not isinstance(track_id, str):
            raise ValueError("legacy prediction JSONL row identifiers are invalid")
        key = (split_name, track_id)
        if key in indexed:
            raise ValueError("legacy prediction JSONL contains duplicated tracks")
        indexed[key] = row
    split_evaluations: dict[str, dict[str, object]] = {}
    consumed: set[tuple[str, str]] = set()
    for split_name in _EVALUATION_SPLITS:
        manifest = manifests[split_name]
        tracks = manifest.get("tracks")
        if manifest.get("split") != split_name or not isinstance(tracks, list):
            raise ValueError(f"legacy replay manifest does not match {split_name}")
        evaluation_tracks = {}
        for track in sorted(tracks, key=lambda item: item.get("track_id", "")):
            track_id = track.get("track_id")
            duration_seconds = track.get("duration_seconds")
            key = (split_name, track_id)
            row = indexed.get(key)
            if (
                not isinstance(track_id, str)
                or isinstance(duration_seconds, bool)
                or not isinstance(duration_seconds, (int, float))
                or row is None
            ):
                raise ValueError("legacy replay is missing a frozen track prediction")
            reference = _reference_intervals(track, float(duration_seconds))
            prediction = _serialized_prediction_intervals(
                row.get("events"), float(duration_seconds)
            )
            evaluation_tracks[track_id] = (reference, prediction)
            consumed.add(key)
        split_evaluations[split_name] = evaluate_corpus(evaluation_tracks, config)
    if consumed != set(indexed):
        raise ValueError("legacy prediction JSONL contains tracks outside frozen manifests")
    return {
        "schema_version": 1,
        "predictions_sha256": hashlib.sha256(predictions_payload).hexdigest(),
        "splits": split_evaluations,
    }


def _serialized_prediction_intervals(
    raw_events: Any, duration_seconds: float
) -> tuple[ScoredChordInterval, ...]:
    if not isinstance(raw_events, list) or not raw_events:
        raise ValueError("legacy replay prediction must contain events")
    intervals: list[ScoredChordInterval] = []
    for raw in raw_events:
        if not isinstance(raw, dict):
            raise ValueError("legacy replay events must be objects")
        chord = CanonicalChord(
            root=raw.get("root"),
            quality=raw.get("quality"),
            bass=raw.get("bass"),
        )
        chord.display_symbol
        intervals.append(
            ScoredChordInterval(
                float(raw.get("start_seconds")),
                float(raw.get("end_seconds")),
                chord,
                float(raw.get("confidence")),
            )
        )
    if not math.isclose(intervals[0].start_seconds, 0.0, abs_tol=1e-9) or not math.isclose(
        intervals[-1].end_seconds, duration_seconds, abs_tol=1e-9
    ):
        raise ValueError("legacy replay prediction must cover the full track")
    return tuple(intervals)


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Legacy baseline v1",
        "",
        f"- Source commit: `{report['source_commit']}`",
        f"- Algorithm: `{report['algorithm_version']}`",
        f"- Predictions SHA-256: `{report['predictions_sha256']}`",
        "",
        "| Split | Tracks | Hours | Root WCSR | Exact WCSR | Macro-F1 | Boundary F1 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for split_name in _EVALUATION_SPLITS:
        evaluation = report["splits"][split_name]["evaluation"]
        aggregate = evaluation["aggregate"]
        lines.append(
            f"| {split_name} | {evaluation['track_count']} | "
            f"{evaluation['duration_seconds'] / 3600:.6f} | "
            f"{aggregate['weighted_scores']['root']:.6f} | "
            f"{aggregate['weighted_scores']['exact_quality']:.6f} | "
            f"{aggregate['quality']['macro_f1']:.6f} | "
            f"{aggregate['boundary']['f1']:.6f} |"
        )
    lines.extend(
        [
            "",
            "The current data gate remains G1 NOT READY. This report is a frozen comparison "
            "baseline, not evidence that the available corpus is sufficient for a competition "
            "candidate.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_immutable_artifacts(artifacts: Mapping[Path, bytes]) -> None:
    for path, payload in artifacts.items():
        if path.exists() and path.read_bytes() != payload:
            raise FileExistsError(
                f"baseline artifact already exists with different content: {path}"
            )
    for path, payload in artifacts.items():
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_name, path)
        finally:
            temporary_path = Path(temporary_name)
            if temporary_path.exists():
                temporary_path.unlink()


def _reference_intervals(
    track: dict[str, Any], duration_seconds: float
) -> tuple[ScoredChordInterval, ...]:
    raw_intervals = track.get("intervals")
    if not isinstance(raw_intervals, list):
        raise ValueError("legacy reference track must contain intervals")
    result: list[ScoredChordInterval] = []
    cursor = 0.0
    for raw in raw_intervals:
        if not isinstance(raw, dict):
            raise ValueError("legacy reference intervals must be objects")
        start = raw.get("start_seconds")
        end = raw.get("end_seconds")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
            or start < cursor - _TIMELINE_TOLERANCE_SECONDS
            or end <= start
            or end > duration_seconds + _TIMELINE_TOLERANCE_SECONDS
        ):
            raise ValueError("legacy reference interval timeline is invalid")
        normalized_start = (
            cursor
            if math.isclose(start, cursor, abs_tol=_TIMELINE_TOLERANCE_SECONDS)
            else float(start)
        )
        normalized_end = (
            duration_seconds
            if math.isclose(end, duration_seconds, abs_tol=_TIMELINE_TOLERANCE_SECONDS)
            else float(end)
        )
        if normalized_start > cursor:
            result.append(
                ScoredChordInterval(cursor, normalized_start, parse_annotation("N"))
            )
        chord = CanonicalChord(
            root=raw.get("root"),
            quality=raw.get("quality"),
            bass=raw.get("bass"),
            mapping_reason=raw.get("mapping_reason"),
        )
        chord.display_symbol
        result.append(ScoredChordInterval(normalized_start, normalized_end, chord))
        cursor = normalized_end
    if duration_seconds - cursor > _TIMELINE_TOLERANCE_SECONDS:
        result.append(ScoredChordInterval(cursor, duration_seconds, parse_annotation("N")))
    if not result:
        result.append(ScoredChordInterval(0.0, duration_seconds, parse_annotation("N")))
    return tuple(result)


def _prediction_intervals(
    events: Sequence[LegacyEvent], duration_seconds: float
) -> tuple[tuple[ScoredChordInterval, ...], list[dict[str, Any]], set[str]]:
    if not events:
        raise ValueError("legacy recognizer returned no events")
    intervals: list[ScoredChordInterval] = []
    serialized: list[dict[str, Any]] = []
    algorithms: set[str] = set()
    for event in events:
        chord = parse_annotation("X" if event.symbol is None else event.symbol)
        confidence = 0.0 if event.confidence is None else float(event.confidence)
        interval = ScoredChordInterval(
            float(event.start_seconds),
            float(event.end_seconds),
            chord,
            confidence,
        )
        intervals.append(interval)
        algorithms.add(event.algorithm)
        serialized.append(
            {
                "start_seconds": interval.start_seconds,
                "end_seconds": interval.end_seconds,
                "root": chord.root,
                "quality": chord.quality,
                "bass": chord.bass,
                "confidence": confidence,
            }
        )
    if not math.isclose(intervals[0].start_seconds, 0.0, abs_tol=1e-9) or not math.isclose(
        intervals[-1].end_seconds, duration_seconds, abs_tol=1e-9
    ):
        raise ValueError("legacy prediction timeline must cover the full track")
    return tuple(intervals), serialized, algorithms


def _sha256(value: Any) -> str:
    return hashlib.sha256(_compact_json_bytes(value)).hexdigest()


def _compact_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _pretty_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON artifact {path}: {error}") from None
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must contain an object: {path}")
    return value


def _parse_path_mapping(values: list[str], *, label: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        key, separator, raw_path = value.partition("=")
        if not separator or not key.strip() or not raw_path.strip():
            raise ValueError(f"{label} must use NAME=PATH")
        if key in result:
            raise ValueError(f"{label} supplied more than once: {key}")
        result[key] = Path(raw_path)
    return result


def _default_audio_loader(path: Path) -> tuple[np.ndarray, int]:
    import librosa

    samples, sample_rate = librosa.load(path, sr=None, mono=True, dtype=np.float32)
    return np.asarray(samples, dtype=np.float32), int(sample_rate)


def _default_recognizer(samples: np.ndarray, sample_rate: int) -> Sequence[LegacyEvent]:
    from museecho.analysis.chords import estimate_chords

    return estimate_chords(samples, sample_rate)


def _runtime_environment() -> dict[str, str]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "numpy": np.__version__,
        "librosa": importlib.metadata.version("librosa"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze the real-music legacy chord baseline")
    parser.add_argument("--manifest", action="append", required=True)
    parser.add_argument("--dataset-root", action="append", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--predictions-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()
    manifest_paths = _parse_path_mapping(args.manifest, label="manifest")
    manifests = {name: _read_json(path) for name, path in manifest_paths.items()}
    dataset_roots = _parse_path_mapping(args.dataset_root, label="dataset root")
    report = run_legacy_protocol(
        manifests,
        dataset_roots=dataset_roots,
        config=load_evaluation_config(args.config),
        source_commit=args.source_commit,
        environment=_runtime_environment(),
        recognize=_default_recognizer,
        audio_loader=_default_audio_loader,
        predictions_output=args.predictions_output,
        report_output=args.report_output,
        markdown_output=args.markdown_output,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
