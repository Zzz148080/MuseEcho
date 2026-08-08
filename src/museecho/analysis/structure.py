from __future__ import annotations

import string
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks

from museecho.analysis.harmonic_features import (
    HOP_LENGTH,
    HarmonicFeatures,
    extract_harmonic_features,
    validate_harmonic_input,
)

_MINIMUM_SEGMENT_SECONDS = 1.0
_RECURRENCE_THRESHOLD = 0.82


@dataclass(frozen=True)
class StructureSegment:
    label: str | None
    start_seconds: float
    end_seconds: float
    confidence: float | None
    algorithm: str = "chroma-recurrence-novelty-v1"

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "confidence": self.confidence,
            "algorithm": self.algorithm,
        }


def segment_structure(
    samples: Sequence[float] | memoryview,
    sample_rate: int,
) -> tuple[StructureSegment, ...]:
    array, normalized_rate, duration_seconds = validate_harmonic_input(samples, sample_rate)
    features = extract_harmonic_features(array, normalized_rate, duration_seconds)
    if features.chroma.shape[1] == 0 or not _has_structural_evidence(features):
        return (_unknown_segment(duration_seconds),)
    novelty = _recurrence_novelty(features.chroma, normalized_rate)
    boundary_frames = _select_boundary_frames(novelty, normalized_rate)
    boundary_times = _boundary_times(boundary_frames, features)
    profiles = _segment_profiles(features, boundary_times)
    labels, similarities = _cluster_recurrent_profiles(profiles)
    return tuple(
        StructureSegment(
            labels[index],
            boundary_times[index],
            boundary_times[index + 1],
            float(np.clip(0.7 + 0.3 * similarities[index], 0.0, 1.0)),
        )
        for index in range(len(profiles))
    )


def _has_structural_evidence(features: HarmonicFeatures) -> bool:
    if features.duration_seconds < _MINIMUM_SEGMENT_SECONDS:
        return False
    chroma = np.maximum(features.chroma, 0.0)
    totals = np.sum(chroma, axis=0)
    sorted_chroma = np.sort(chroma, axis=0)
    concentration = np.divide(
        np.sum(sorted_chroma[-3:, :], axis=0),
        totals,
        out=np.zeros_like(totals),
        where=totals > 1e-12,
    )
    active = (features.rms > 1e-4) & (concentration >= 0.55)
    return float(np.mean(active)) >= 0.6


def _recurrence_novelty(chroma: np.ndarray, sample_rate: int) -> np.ndarray:
    norms = np.linalg.norm(chroma, axis=0)
    normalized = np.divide(chroma, norms, out=np.zeros_like(chroma), where=norms > 1e-12)
    window_frames = max(2, round(0.5 * sample_rate / HOP_LENGTH))
    novelty = np.zeros(chroma.shape[1], dtype=np.float64)
    for boundary in range(window_frames, chroma.shape[1] - window_frames):
        left = normalized[:, boundary - window_frames : boundary]
        right = normalized[:, boundary : boundary + window_frames]
        left_similarity = float(np.mean(left.T @ left))
        right_similarity = float(np.mean(right.T @ right))
        cross_similarity = float(np.mean(left.T @ right))
        novelty[boundary] = max(
            0.0,
            0.5 * (left_similarity + right_similarity) - cross_similarity,
        )
    return novelty


def _select_boundary_frames(novelty: np.ndarray, sample_rate: int) -> list[int]:
    minimum_frames = max(1, round(_MINIMUM_SEGMENT_SECONDS * sample_rate / HOP_LENGTH))
    peaks, properties = find_peaks(
        novelty,
        height=0.2,
        prominence=0.15,
        distance=minimum_frames,
    )
    ordered = sorted(
        zip(peaks.tolist(), properties["peak_heights"].tolist()),
        key=lambda item: item[1],
        reverse=True,
    )
    accepted: list[int] = []
    frame_count = novelty.size
    for frame, _height in ordered:
        if frame < minimum_frames or frame_count - frame < minimum_frames:
            continue
        if all(abs(frame - previous) >= minimum_frames for previous in accepted):
            accepted.append(frame)
    return sorted(accepted)


def _boundary_times(boundary_frames: list[int], features: HarmonicFeatures) -> list[float]:
    centers = features.frame_centers_seconds
    times = [0.0]
    times.extend(
        float(np.clip(centers[frame], 0.0, features.duration_seconds)) for frame in boundary_frames
    )
    times.append(float(features.duration_seconds))
    return times


def _segment_profiles(
    features: HarmonicFeatures,
    boundary_times: list[float],
) -> list[np.ndarray]:
    centers = features.frame_centers_seconds
    profiles: list[np.ndarray] = []
    for start, end in zip(boundary_times, boundary_times[1:]):
        mask = (centers >= start) & (centers < end)
        if not bool(np.any(mask)):
            profiles.append(np.zeros(12, dtype=np.float64))
            continue
        profile = np.mean(features.chroma[:, mask], axis=1)
        norm = float(np.linalg.norm(profile))
        profiles.append(profile / norm if norm > 1e-12 else profile)
    return profiles


def _cluster_recurrent_profiles(
    profiles: list[np.ndarray],
) -> tuple[list[str], list[float]]:
    representatives: list[np.ndarray] = []
    labels: list[str] = []
    similarities: list[float] = []
    for profile in profiles:
        if representatives:
            scores = [float(np.dot(profile, representative)) for representative in representatives]
            best_index = int(np.argmax(scores))
            best_score = scores[best_index]
        else:
            best_index = 0
            best_score = 1.0
        if representatives and best_score >= _RECURRENCE_THRESHOLD:
            labels.append(_section_label(best_index))
            similarities.append(best_score)
        else:
            representatives.append(profile)
            labels.append(_section_label(len(representatives) - 1))
            similarities.append(1.0)
    return labels, similarities


def _section_label(index: int) -> str:
    alphabet = string.ascii_uppercase
    result = ""
    value = index
    while True:
        value, remainder = divmod(value, len(alphabet))
        result = alphabet[remainder] + result
        if value == 0:
            return result
        value -= 1


def _unknown_segment(duration_seconds: float) -> StructureSegment:
    return StructureSegment(None, 0.0, float(duration_seconds), None)
