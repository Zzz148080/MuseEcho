from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from museecho_ml.artifacts import canonical_sha256, write_immutable_json
from museecho_ml.data.plan_d import (
    PLAN_C_TEST_MANIFEST_SHA256,
    load_plan_d_protocol,
)
from museecho_ml.evaluation.metrics import ScoredChordInterval, weighted_chord_scores
from museecho_ml.evaluation.plan_d import (
    load_plan_d_legacy_predictions,
    load_plan_d_raw_predictions,
)
from museecho_ml.postprocess.calibration import CalibrationParameters
from museecho_ml.postprocess.decode import decode_logits
from museecho_ml.vocabulary import ChordVocabulary

_DEVELOPMENT_SPLITS = frozenset({"train", "calibration", "validation"})
_SEEDS = (20260821, 20260822, 20260823)
_ML_ROOT = Path(__file__).resolve().parents[3]


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
    seed: int | None = None


def audit_frame_alignment(
    frame_times: NDArray[np.floating],
    reference: Sequence[ScoredChordInterval],
) -> dict[str, float]:
    times = np.asarray(frame_times, dtype=np.float64)
    if (
        times.ndim != 1
        or len(times) == 0
        or not np.all(np.isfinite(times))
        or np.any(times < 0)
        or np.any(np.diff(times) <= 0)
    ):
        raise ValueError("Plan D audit frame times are invalid")
    if not reference:
        raise ValueError("Plan D audit reference cannot be empty")
    grid = times
    if len(times) > 1:
        terminal = times[-1] + float(np.median(np.diff(times)))
        grid = np.append(times, terminal)
    boundaries = np.asarray(
        sorted(
            {item.start_seconds for item in reference}
            | {item.end_seconds for item in reference}
        ),
        dtype=np.float64,
    )
    errors = np.min(np.abs(grid[:, None] - boundaries[None, :]), axis=0)
    return {
        "maximum_boundary_frame_error_seconds": float(errors.max(initial=0.0)),
        "mean_boundary_frame_error_seconds": float(errors.mean()),
    }


def build_plan_d_failure_audit(
    tracks: Sequence[PlanDAuditTrack],
    *,
    supported_qualities: Sequence[str],
) -> dict[str, Any]:
    qualities = _validated_supported_qualities(supported_qualities)
    validated = _validated_audit_tracks(tracks)
    body = {
        "schema_version": 1,
        "audit_version": "plan-d-failure-audit-v1",
        "alignment": _aggregate_alignment(validated),
        "root_confusion_seconds": _confusion_seconds(validated, "root"),
        "quality_confusion_seconds": _confusion_seconds(
            validated, "quality", labels=qualities
        ),
        "bass_confusion_seconds": _confusion_seconds(validated, "bass"),
        "event_counts": _event_count_report(validated),
        "quality_support": _quality_support_report(validated, qualities),
        "confidence_curve": _confidence_curve(validated),
        "cover_group_count": len({track.cover_group_id for track in validated}),
        "datasets": _stratified_reports(validated, key="dataset"),
        "seeds": _stratified_reports(validated, key="seed"),
    }
    return {**body, "audit_sha256": canonical_sha256(body)}


def run_plan_d_audit(
    tracks: Sequence[PlanDAuditTrack],
    *,
    supported_qualities: Sequence[str],
    output_path: Path,
) -> dict[str, Any]:
    report = build_plan_d_failure_audit(
        tracks, supported_qualities=supported_qualities
    )
    body = dict(report)
    body.pop("audit_sha256")
    body["status"] = "completed"
    result = {**body, "audit_sha256": canonical_sha256(body)}
    write_immutable_json(output_path, result)
    return result


def build_plan_d_stage_0_audit(
    *,
    protocol: Mapping[str, Any],
    vocabulary: ChordVocabulary,
    split: str,
    legacy_by_track: Mapping[str, Sequence[ScoredChordInterval]],
    legacy_identity: Mapping[str, Any],
    raw_by_seed: Mapping[int, Sequence[Any]],
    deep_identities: Mapping[int, Mapping[str, Any]],
    calibration_by_seed: Mapping[int, CalibrationParameters],
    calibration_identities: Mapping[int, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    if split not in {"calibration", "validation"}:
        raise ValueError("Plan D audit forbids test split")
    expected_seeds = tuple(protocol.get("seeds", ()))
    if expected_seeds != _SEEDS or set(raw_by_seed) != set(_SEEDS):
        raise ValueError("Plan D audit seed identity drift")
    if set(deep_identities) != set(_SEEDS) or set(calibration_by_seed) != set(
        _SEEDS
    ):
        raise ValueError("Plan D audit seed evidence is incomplete")
    split_binding = protocol.get("development_splits", {}).get(split)
    plan_c = protocol.get("plan_c")
    legacy_binding = protocol.get("legacy_algorithm")
    if not all(
        isinstance(value, Mapping)
        for value in (split_binding, plan_c, legacy_binding)
    ):
        raise ValueError("Plan D audit protocol identity is invalid")
    manifest_sha256 = split_binding.get("manifest_sha256")
    vocabulary_sha256 = plan_c.get("vocabulary_sha256")
    legacy_version = legacy_binding.get("version")
    if (
        legacy_identity.get("split") != split
        or legacy_identity.get("manifest_sha256") != manifest_sha256
        or legacy_identity.get("algorithm_version") != legacy_version
    ):
        raise ValueError("Plan D legacy audit identity drift")
    if not legacy_by_track:
        raise ValueError("Plan D legacy audit predictions cannot be empty")

    ordered_raw: dict[int, tuple[Any, ...]] = {}
    track_ids = set(legacy_by_track)
    for seed in _SEEDS:
        identity = deep_identities[seed]
        if (
            identity.get("seed") != seed
            or identity.get("split") != split
            or identity.get("manifest_sha256") != manifest_sha256
            or identity.get("vocabulary_sha256") != vocabulary_sha256
        ):
            raise ValueError("Plan D deep audit identity drift")
        raw = tuple(sorted(raw_by_seed[seed], key=lambda item: item.track_id))
        if not raw or {item.track_id for item in raw} != track_ids:
            raise ValueError("Plan D audit track identity drift")
        if any(item.split != split for item in raw):
            raise ValueError("Plan D audit forbids test split")
        ordered_raw[seed] = raw

    first_by_track = {item.track_id: item for item in ordered_raw[_SEEDS[0]]}
    reference_consistent = True
    frame_grid_consistent = True
    deep_tracks: list[PlanDAuditTrack] = []
    for seed in _SEEDS:
        calibration = calibration_by_seed[seed]
        for raw in ordered_raw[seed]:
            baseline = first_by_track[raw.track_id]
            if (
                raw.dataset_id != baseline.dataset_id
                or raw.cover_group_id != baseline.cover_group_id
                or raw.duration_seconds != baseline.duration_seconds
            ):
                raise ValueError("Plan D audit track metadata drift")
            reference_consistent &= raw.reference == baseline.reference
            frame_grid_consistent &= np.array_equal(
                raw.frame_times, baseline.frame_times
            ) and np.array_equal(raw.valid_mask, baseline.valid_mask)
            prediction = decode_logits(
                raw.root_logits,
                raw.quality_logits,
                raw.bass_logits,
                raw.boundary_logits,
                raw.frame_times,
                raw.valid_mask,
                duration_seconds=raw.duration_seconds,
                vocabulary=vocabulary,
                calibration=calibration,
            )
            deep_tracks.append(
                PlanDAuditTrack(
                    track_id=raw.track_id,
                    dataset_id=raw.dataset_id,
                    cover_group_id=raw.cover_group_id,
                    split=split,
                    duration_seconds=raw.duration_seconds,
                    frame_times=np.asarray(raw.frame_times, dtype=np.float64),
                    reference=tuple(raw.reference),
                    prediction=tuple(prediction),
                    seed=seed,
                )
            )

    legacy_tracks = tuple(
        PlanDAuditTrack(
            track_id=track_id,
            dataset_id=raw.dataset_id,
            cover_group_id=raw.cover_group_id,
            split=split,
            duration_seconds=raw.duration_seconds,
            frame_times=np.asarray(raw.frame_times, dtype=np.float64),
            reference=tuple(raw.reference),
            prediction=tuple(legacy_by_track[track_id]),
        )
        for track_id, raw in sorted(first_by_track.items())
    )
    qualities = tuple(
        label for label in vocabulary.quality_labels if label not in {"N", "X"}
    )
    deep_report = build_plan_d_failure_audit(
        tuple(deep_tracks), supported_qualities=qualities
    )
    legacy_report = build_plan_d_failure_audit(
        legacy_tracks, supported_qualities=qualities
    )
    maximum_hop = max(
        float(np.max(np.diff(track.frame_times), initial=0.0))
        for track in deep_tracks
    )
    checks = {
        "development-split": True,
        "manifest-identity": True,
        "vocabulary-identity": True,
        "legacy-algorithm-identity": True,
        "track-identity": True,
        "reference-consistency": bool(reference_consistent),
        "frame-grid-consistency": bool(frame_grid_consistent),
        "frame-alignment": (
            deep_report["alignment"]["maximum_boundary_frame_error_seconds"]
            <= maximum_hop + 1e-12
        ),
    }
    seed_identities = {}
    for seed in _SEEDS:
        seed_identity = {
            "checkpoint_sha256": deep_identities[seed]["checkpoint_sha256"]
        }
        if calibration_identities is not None:
            seed_identity.update(calibration_identities[seed])
        seed_identities[str(seed)] = seed_identity
    body = {
        "schema_version": 1,
        "audit_version": "plan-d-failure-audit-v1",
        "status": "completed" if all(checks.values()) else "defect-found",
        "split": split,
        "checks": checks,
        "identity": {
            "manifest_sha256": manifest_sha256,
            "vocabulary_sha256": vocabulary_sha256,
            "legacy_algorithm_version": legacy_version,
            "seeds": seed_identities,
        },
        "variants": {"deep-only": deep_report, "legacy": legacy_report},
    }
    return {**body, "audit_sha256": canonical_sha256(body)}


def run_plan_d_stage_0_audit_from_files(
    *,
    protocol_path: Path,
    vocabulary_path: Path,
    legacy_predictions_path: Path,
    deep_prediction_paths: Mapping[int, Path],
    split: str,
    output_path: Path,
) -> dict[str, Any]:
    if split not in {"calibration", "validation"}:
        raise ValueError("Plan D audit forbids test split")
    protocol = load_plan_d_protocol(protocol_path)
    split_binding = protocol["development_splits"].get(split)
    if (
        not isinstance(split_binding, Mapping)
        or split_binding.get("manifest_sha256") == PLAN_C_TEST_MANIFEST_SHA256
    ):
        raise ValueError("Plan D audit forbids the Plan C test manifest")
    vocabulary = _load_audit_vocabulary(vocabulary_path, protocol)
    if set(deep_prediction_paths) != set(_SEEDS):
        raise ValueError("Plan D audit requires exactly three seed predictions")

    legacy_by_track, legacy_identity = load_plan_d_legacy_predictions(
        legacy_predictions_path
    )
    raw_by_seed = {}
    deep_identities = {}
    calibration_by_seed = {}
    calibration_identities = {}
    for seed in _SEEDS:
        raw, identity = load_plan_d_raw_predictions(deep_prediction_paths[seed])
        raw_by_seed[seed] = raw
        deep_identities[seed] = identity
        calibration, calibration_identity = _load_plan_c_calibration(
            seed=seed,
            checkpoint_sha256=identity["checkpoint_sha256"],
            protocol=protocol,
        )
        calibration_by_seed[seed] = calibration
        calibration_identities[seed] = calibration_identity
    result = build_plan_d_stage_0_audit(
        protocol=protocol,
        vocabulary=vocabulary,
        split=split,
        legacy_by_track=legacy_by_track,
        legacy_identity=legacy_identity,
        raw_by_seed=raw_by_seed,
        deep_identities=deep_identities,
        calibration_by_seed=calibration_by_seed,
        calibration_identities=calibration_identities,
    )
    write_immutable_json(output_path, result)
    return result


def _load_audit_vocabulary(
    path: Path, protocol: Mapping[str, Any]
) -> ChordVocabulary:
    try:
        payload = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Plan D audit vocabulary is unreadable") from error
    vocabulary = ChordVocabulary.from_dict(payload)
    if payload.get("vocabulary_sha256") != protocol["plan_c"]["vocabulary_sha256"]:
        raise ValueError("Plan D audit vocabulary identity drift")
    return vocabulary


def _load_plan_c_calibration(
    *, seed: int, checkpoint_sha256: str, protocol: Mapping[str, Any]
) -> tuple[CalibrationParameters, dict[str, str]]:
    candidates = sorted(
        (_ML_ROOT / "runs" / "plan-c").glob(f"*/C1/{seed}/finetune")
    )
    for directory in candidates:
        try:
            calibration_payload = json.loads(
                (directory / "calibration.json").read_text(encoding="utf-8")
            )
            threshold_payload = json.loads(
                (directory / "threshold.json").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(calibration_payload, dict) or not isinstance(
            threshold_payload, dict
        ):
            continue
        calibration_body = dict(calibration_payload)
        calibration_sha256 = calibration_body.pop("calibration_sha256", None)
        threshold_body = dict(threshold_payload)
        threshold_sha256 = threshold_body.pop("threshold_sha256", None)
        if (
            not isinstance(calibration_sha256, str)
            or canonical_sha256(calibration_body) != calibration_sha256
            or not isinstance(threshold_sha256, str)
            or canonical_sha256(threshold_body) != threshold_sha256
            or calibration_payload.get("checkpoint_sha256") != checkpoint_sha256
            or calibration_payload.get("calibration_manifest_sha256")
            != protocol["development_splits"]["calibration"]["manifest_sha256"]
            or calibration_payload.get("vocabulary_sha256")
            != protocol["plan_c"]["vocabulary_sha256"]
            or threshold_payload.get("calibration_sha256") != calibration_sha256
        ):
            continue
        try:
            parameters = CalibrationParameters(
                root_temperature=calibration_payload["root_temperature"],
                quality_temperature=calibration_payload["quality_temperature"],
                bass_temperature=calibration_payload["bass_temperature"],
                publication_threshold=threshold_payload["publication_threshold"],
                boundary_threshold=calibration_payload["boundary_threshold"],
                minimum_event_seconds=calibration_payload["minimum_event_seconds"],
            )
        except (KeyError, TypeError, ValueError):
            continue
        return parameters, {
            "calibration_sha256": calibration_sha256,
            "threshold_sha256": threshold_sha256,
        }
    raise ValueError(f"Plan D seed {seed} calibration evidence is unavailable")


def _parse_deep_prediction_paths(values: Sequence[str]) -> dict[int, Path]:
    result: dict[int, Path] = {}
    for value in values:
        try:
            seed_text, path_text = value.split("=", 1)
            seed = int(seed_text)
        except (ValueError, TypeError) as error:
            raise ValueError("Plan D deep prediction argument is invalid") from error
        if seed in result or seed not in _SEEDS or not path_text:
            raise ValueError("Plan D deep prediction argument is invalid")
        result[seed] = Path(path_text)
    if set(result) != set(_SEEDS):
        raise ValueError("Plan D audit requires exactly three seed predictions")
    return result


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Plan D Stage 0 audit")
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--vocabulary", type=Path, required=True)
    parser.add_argument("--legacy-predictions", type=Path, required=True)
    parser.add_argument("--deep-predictions", action="append", default=[])
    parser.add_argument("--split", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.split not in {"calibration", "validation"}:
        raise ValueError("Plan D audit forbids test split")
    result = run_plan_d_stage_0_audit_from_files(
        protocol_path=args.protocol,
        vocabulary_path=args.vocabulary,
        legacy_predictions_path=args.legacy_predictions,
        deep_prediction_paths=_parse_deep_prediction_paths(args.deep_predictions),
        split=args.split,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "audit_sha256": result["audit_sha256"],
                "status": result["status"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def _validated_supported_qualities(values: Sequence[str]) -> tuple[str, ...]:
    if (
        not isinstance(values, Sequence)
        or isinstance(values, (str, bytes))
        or not values
        or any(not isinstance(value, str) or not value for value in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError("Plan D supported qualities are invalid")
    return tuple(sorted(values))


def _validated_audit_tracks(
    tracks: Sequence[PlanDAuditTrack],
) -> tuple[PlanDAuditTrack, ...]:
    if not isinstance(tracks, Sequence) or not tracks:
        raise ValueError("Plan D audit tracks cannot be empty")
    vocabulary = ChordVocabulary.default()
    validated: list[PlanDAuditTrack] = []
    identities: set[tuple[int | None, str]] = set()
    for track in tracks:
        if not isinstance(track, PlanDAuditTrack):
            raise ValueError("Plan D audit track type is invalid")
        if track.split not in _DEVELOPMENT_SPLITS:
            raise ValueError("Plan D audit forbids test split")
        if not track.track_id or not track.dataset_id:
            raise ValueError("Plan D audit track identity is invalid")
        if not track.cover_group_id:
            raise ValueError("Plan D audit cover group is missing")
        if track.seed is not None and type(track.seed) is not int:
            raise ValueError("Plan D audit seed is invalid")
        if not math.isfinite(track.duration_seconds) or track.duration_seconds <= 0:
            raise ValueError("Plan D audit duration is invalid")
        identity = (track.seed, track.track_id)
        if identity in identities:
            raise ValueError("Plan D audit track identity is duplicated")
        identities.add(identity)
        _validate_timeline(track.reference, track.duration_seconds, "reference", vocabulary)
        _validate_timeline(track.prediction, track.duration_seconds, "prediction", vocabulary)
        weighted_chord_scores(track.reference, track.prediction)
        audit_frame_alignment(track.frame_times, track.reference)
        validated.append(track)
    return tuple(
        sorted(
            validated,
            key=lambda item: (
                item.dataset_id,
                -1 if item.seed is None else item.seed,
                item.cover_group_id,
                item.track_id,
            ),
        )
    )


def _validate_timeline(
    items: Sequence[ScoredChordInterval],
    duration_seconds: float,
    name: str,
    vocabulary: ChordVocabulary,
) -> None:
    if not items:
        raise ValueError(f"Plan D audit {name} timeline cannot be empty")
    previous_end = 0.0
    for item in items:
        if item.start_seconds < previous_end:
            raise ValueError(f"Plan D audit {name} intervals overlap")
        try:
            vocabulary.encode(item.chord)
        except ValueError as error:
            raise ValueError("Plan D audit contains an illegal chord state") from error
        previous_end = item.end_seconds
    if not math.isclose(items[0].start_seconds, 0.0, abs_tol=1e-9) or not math.isclose(
        items[-1].end_seconds, duration_seconds, abs_tol=1e-9
    ):
        raise ValueError(f"Plan D audit {name} timeline extent is invalid")


def _aggregate_alignment(tracks: Sequence[PlanDAuditTrack]) -> dict[str, float]:
    reports = [audit_frame_alignment(track.frame_times, track.reference) for track in tracks]
    return {
        "maximum_boundary_frame_error_seconds": max(
            report["maximum_boundary_frame_error_seconds"] for report in reports
        ),
        "mean_boundary_frame_error_seconds": sum(
            report["mean_boundary_frame_error_seconds"] for report in reports
        )
        / len(reports),
    }


def _aligned_segments(
    reference: Sequence[ScoredChordInterval],
    prediction: Sequence[ScoredChordInterval],
) -> Iterable[tuple[ScoredChordInterval, ScoredChordInterval, float]]:
    reference_index = 0
    prediction_index = 0
    while reference_index < len(reference) and prediction_index < len(prediction):
        reference_item = reference[reference_index]
        prediction_item = prediction[prediction_index]
        start = max(reference_item.start_seconds, prediction_item.start_seconds)
        end = min(reference_item.end_seconds, prediction_item.end_seconds)
        if start < end:
            yield reference_item, prediction_item, end - start
        if reference_item.end_seconds <= prediction_item.end_seconds:
            reference_index += 1
        if prediction_item.end_seconds <= reference_item.end_seconds:
            prediction_index += 1


def _confusion_seconds(
    tracks: Sequence[PlanDAuditTrack],
    head: str,
    *,
    labels: Sequence[str] = (),
) -> dict[str, dict[str, float]]:
    rows: dict[str, dict[str, float]] = {label: {} for label in labels}
    for track in tracks:
        for reference, prediction, duration in _aligned_segments(
            track.reference, track.prediction
        ):
            if head == "quality" and reference.chord.root != prediction.chord.root:
                continue
            if head == "bass" and (
                reference.chord.root != prediction.chord.root
                or reference.chord.quality != prediction.chord.quality
            ):
                continue
            expected = getattr(reference.chord, head)
            actual = getattr(prediction.chord, head)
            row = rows.setdefault(expected, {})
            row[actual] = row.get(actual, 0.0) + duration
    return {
        expected: {actual: row[actual] for actual in sorted(row)}
        for expected, row in sorted(rows.items())
    }


def _event_count_report(tracks: Sequence[PlanDAuditTrack]) -> dict[str, float | int]:
    reference = sum(len(track.reference) for track in tracks)
    prediction = sum(len(track.prediction) for track in tracks)
    return {
        "prediction": prediction,
        "reference": reference,
        "ratio": prediction / reference,
    }


def _quality_support_report(
    tracks: Sequence[PlanDAuditTrack], qualities: Sequence[str]
) -> dict[str, dict[str, float | int]]:
    report: dict[str, dict[str, float | int]] = {}
    for quality in qualities:
        matching = [
            (track, item)
            for track in tracks
            for item in track.reference
            if item.chord.quality == quality
        ]
        report[quality] = {
            "cover_groups": len({track.cover_group_id for track, _ in matching}),
            "duration_seconds": sum(
                item.end_seconds - item.start_seconds for _, item in matching
            ),
            "intervals": len(matching),
        }
    return report


def _confidence_curve(tracks: Sequence[PlanDAuditTrack]) -> dict[str, Any]:
    bins = [
        {"lower": index / 10, "upper": (index + 1) / 10, "duration_seconds": 0.0,
         "correct_seconds": 0.0}
        for index in range(10)
    ]
    duration_seconds = 0.0
    correct_seconds = 0.0
    for track in tracks:
        for reference, prediction, duration in _aligned_segments(
            track.reference, track.prediction
        ):
            index = min(int(prediction.confidence * 10), 9)
            bins[index]["duration_seconds"] += duration
            correct = (
                reference.chord.root == prediction.chord.root
                and reference.chord.quality == prediction.chord.quality
            )
            if correct:
                bins[index]["correct_seconds"] += duration
                correct_seconds += duration
            duration_seconds += duration
    return {
        "bins": bins,
        "correct_seconds": correct_seconds,
        "duration_seconds": duration_seconds,
    }


def _stratified_reports(
    tracks: Sequence[PlanDAuditTrack], *, key: str
) -> dict[str, dict[str, Any]]:
    values: dict[str, list[PlanDAuditTrack]] = {}
    for track in tracks:
        if key == "dataset":
            value = track.dataset_id
        else:
            if track.seed is None:
                continue
            value = str(track.seed)
        values.setdefault(value, []).append(track)
    return {
        value: {
            "event_counts": _event_count_report(items),
            "quality_confusion_seconds": _confusion_seconds(items, "quality"),
            "track_count": len(items),
        }
        for value, items in sorted(values.items())
    }


if __name__ == "__main__":
    main()
