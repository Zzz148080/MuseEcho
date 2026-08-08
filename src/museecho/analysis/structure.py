from __future__ import annotations

import math
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
_ABA_RECURRENCE_THRESHOLD = 0.95


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
    selected_times, boundary_strengths = _select_multiscale_boundaries(features)
    if not selected_times:
        return (_unknown_segment(duration_seconds),)
    boundary_times = [0.0, *selected_times, float(duration_seconds)]
    profiles = _segment_profiles(features, boundary_times)
    evidence = _segment_evidence(features, boundary_times)
    labels, similarities = _cluster_recurrent_profiles(profiles)
    segments: list[StructureSegment] = []
    for index, clustered_label in enumerate(labels):
        label: str | None = clustered_label
        adjacent_strengths = boundary_strengths[
            max(0, index - 1) : min(len(boundary_strengths), index + 1)
        ]
        boundary_evidence = float(np.mean(adjacent_strengths))
        if evidence[index]:
            confidence = float(
                np.clip(
                    0.65 + 0.25 * boundary_evidence + 0.1 * similarities[index],
                    0.0,
                    1.0,
                )
            )
        else:
            label = None
            confidence = None
        segments.append(
            StructureSegment(
                label,
                boundary_times[index],
                boundary_times[index + 1],
                confidence,
            )
        )
    return tuple(segments)


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


def _select_multiscale_boundaries(
    features: HarmonicFeatures,
) -> tuple[list[float], list[float]]:
    aggregate_frames = max(1, round(0.25 * features.sample_rate / HOP_LENGTH))
    aggregated = _aggregate_chroma(features.chroma, aggregate_frames)
    bin_seconds = aggregate_frames * HOP_LENGTH / features.sample_rate
    if _has_repeating_loop(aggregated, bin_seconds):
        return [], []
    general_times, general_strengths = _general_novelty_boundaries(
        aggregated,
        bin_seconds,
        features.duration_seconds,
    )
    recurrent_aba = _prefix_suffix_recurrence_boundaries(
        aggregated,
        bin_seconds,
        features.duration_seconds,
    )
    if recurrent_aba is not None:
        recurrent_times, recurrent_strengths = recurrent_aba
        first, second = recurrent_times
        start_bin = max(0, round(first / bin_seconds))
        end_bin = min(aggregated.shape[1], round(second / bin_seconds))
        middle_chroma = aggregated[:, start_bin:end_bin]
        local_times, local_strengths = _general_novelty_boundaries(
            middle_chroma,
            bin_seconds,
            second - first,
        )
        local_candidates = [
            (timestamp, strength)
            for timestamp, strength in zip(local_times, local_strengths)
            if timestamp >= _MINIMUM_SEGMENT_SECONDS - 0.35
            and second - first - timestamp >= _MINIMUM_SEGMENT_SECONDS - 0.35
        ]
        local_times, local_strengths = _enforce_minimum_segments(
            local_candidates,
            second - first,
        )
        if (
            len(local_times) > 1
            and not _local_segments_recur(middle_chroma, local_times, bin_seconds)
            and not _local_segments_are_stable(middle_chroma, local_times, bin_seconds)
        ):
            local_times = []
            local_strengths = []
        internal = [
            (first + timestamp, strength)
            for timestamp, strength in zip(local_times, local_strengths)
            if timestamp >= _MINIMUM_SEGMENT_SECONDS
            and second - first - timestamp >= _MINIMUM_SEGMENT_SECONDS
        ]
        combined = [
            (first, recurrent_strengths[0]),
            *internal,
            (second, recurrent_strengths[1]),
        ]
        return _enforce_minimum_segments(combined, features.duration_seconds)
    return _enforce_minimum_segments(
        list(zip(general_times, general_strengths)),
        features.duration_seconds,
    )


def _local_segments_recur(
    chroma: np.ndarray,
    boundary_times: list[float],
    bin_seconds: float,
) -> bool:
    boundary_bins = [0]
    boundary_bins.extend(round(timestamp / bin_seconds) for timestamp in boundary_times)
    boundary_bins.append(chroma.shape[1])
    profiles: list[np.ndarray] = []
    for start, end in zip(boundary_bins, boundary_bins[1:]):
        profile = np.mean(chroma[:, start:end], axis=1)
        norm = float(np.linalg.norm(profile))
        profiles.append(profile / norm if norm > 1e-12 else profile)
    for left in range(len(profiles)):
        for right in range(left + 2, len(profiles)):
            if float(np.dot(profiles[left], profiles[right])) >= 0.9:
                return True
    return False


def _local_segments_are_stable(
    chroma: np.ndarray,
    boundary_times: list[float],
    bin_seconds: float,
) -> bool:
    boundary_bins = [0]
    boundary_bins.extend(round(timestamp / bin_seconds) for timestamp in boundary_times)
    boundary_bins.append(chroma.shape[1])
    for start, end in zip(boundary_bins, boundary_bins[1:]):
        frames = chroma[:, start:end]
        if frames.shape[1] == 0:
            return False
        profile = np.mean(frames, axis=1)
        norm = float(np.linalg.norm(profile))
        if norm <= 1e-12:
            return False
        stability = float(np.mean((profile / norm) @ frames))
        if stability < 0.94:
            return False
    return True


def _general_novelty_boundaries(
    chroma: np.ndarray,
    bin_seconds: float,
    duration_seconds: float,
) -> tuple[list[float], list[float]]:
    maximum_scale = min(16.0, duration_seconds / 3.0)
    scales: list[float] = []
    scale = 0.5
    while scale <= maximum_scale + 1e-9:
        scales.append(scale)
        scale *= 2
    candidates: list[tuple[float, float]] = []
    for scale_seconds in reversed(scales):
        window_bins = max(2, round(scale_seconds / bin_seconds))
        novelty = _window_profile_novelty(chroma, window_bins)
        maximum = float(np.max(novelty, initial=0.0))
        if maximum < 0.08:
            continue
        minimum_bins = max(
            math.floor(_MINIMUM_SEGMENT_SECONDS / bin_seconds),
            round(0.75 * scale_seconds / bin_seconds),
        )
        peaks, _properties = find_peaks(
            novelty,
            height=max(0.08, 0.45 * maximum),
            prominence=max(0.04, 0.2 * maximum),
            distance=minimum_bins,
        )
        accepted = [int(peak) for peak in peaks if 0 < peak < chroma.shape[1]]
        if not accepted:
            continue
        scale_strengths = [float(np.clip(novelty[peak] / maximum, 0.0, 1.0)) for peak in accepted]
        scale_times = [float(peak * bin_seconds) for peak in accepted]
        candidates.extend(zip(scale_times, scale_strengths))
    if not candidates:
        return [], []
    groups: list[list[tuple[float, float]]] = []
    for candidate in sorted(candidates):
        if groups and candidate[0] - groups[-1][-1][0] <= max(0.35, 2 * bin_seconds):
            groups[-1].append(candidate)
        else:
            groups.append([candidate])
    merged_times: list[float] = []
    merged_strengths: list[float] = []
    for group in groups:
        weights = np.asarray([strength for _timestamp, strength in group], dtype=np.float64)
        times = np.asarray([timestamp for timestamp, _strength in group], dtype=np.float64)
        merged_times.append(float(np.average(times, weights=weights)))
        merged_strengths.append(float(np.max(weights)))
    return merged_times, merged_strengths


def _prefix_suffix_recurrence_boundaries(
    chroma: np.ndarray,
    bin_seconds: float,
    duration_seconds: float,
) -> tuple[list[float], list[float]] | None:
    minimum_bins = max(2, math.ceil(_MINIMUM_SEGMENT_SECONDS / bin_seconds))
    maximum_bins = (chroma.shape[1] - minimum_bins) // 2
    for section_bins in range(maximum_bins, minimum_bins - 1, -1):
        prefix = chroma[:, :section_bins]
        suffix = chroma[:, -section_bins:]
        frame_recurrence = np.sum(prefix * suffix, axis=0)
        recurrence = float(np.mean(frame_recurrence))
        middle = chroma[:, section_bins:-section_bins]
        if middle.shape[1] < minimum_bins:
            continue
        recurrent_profile = np.mean(np.concatenate((prefix, suffix), axis=1), axis=1)
        middle_profile = np.mean(middle, axis=1)
        recurrent_norm = float(np.linalg.norm(recurrent_profile))
        middle_norm = float(np.linalg.norm(middle_profile))
        if recurrent_norm <= 1e-12 or middle_norm <= 1e-12:
            continue
        similarity_to_middle = float(
            np.dot(recurrent_profile, middle_profile) / (recurrent_norm * middle_norm)
        )
        contrast = 1.0 - similarity_to_middle
        if recurrence < _ABA_RECURRENCE_THRESHOLD or contrast < 0.03:
            continue
        section_seconds = section_bins * bin_seconds
        first = section_seconds
        second = duration_seconds - section_seconds
        if second <= first:
            continue
        strength = float(np.clip(0.5 * recurrence + 0.5 * contrast / 0.25, 0.0, 1.0))
        return [first, second], [strength, strength]
    return None


def _has_repeating_loop(chroma: np.ndarray, bin_seconds: float) -> bool:
    minimum_lag = max(2, math.floor(2.0 / bin_seconds))
    maximum_lag = chroma.shape[1] // 3
    if maximum_lag < minimum_lag:
        return False
    for lag in range(minimum_lag, maximum_lag + 1):
        cycle_profile = np.mean(chroma[:, :lag], axis=1)
        if 1.0 - float(np.linalg.norm(cycle_profile)) < 0.05:
            continue
        frame_similarities = np.sum(chroma[:, :-lag] * chroma[:, lag:], axis=0)
        if float(np.mean(frame_similarities)) < 0.90:
            continue
        if float(np.mean(frame_similarities >= 0.85)) >= 0.80:
            return True
    return False


def _enforce_minimum_segments(
    candidates: list[tuple[float, float]],
    duration_seconds: float,
) -> tuple[list[float], list[float]]:
    ordered = sorted(candidates)
    maximum_boundaries = max(0, math.floor(duration_seconds / _MINIMUM_SEGMENT_SECONDS) - 1)
    while len(ordered) > maximum_boundaries:
        weakest = min(range(len(ordered)), key=lambda index: ordered[index][1])
        ordered.pop(weakest)
    if not ordered:
        return [], []
    times = np.asarray([timestamp for timestamp, _strength in ordered], dtype=np.float64)
    count = times.size
    lower = np.arange(1, count + 1, dtype=np.float64) * _MINIMUM_SEGMENT_SECONDS
    upper = duration_seconds - (
        np.arange(count, 0, -1, dtype=np.float64) * _MINIMUM_SEGMENT_SECONDS
    )
    times = np.clip(times, lower, upper)
    for index in range(1, count):
        times[index] = max(times[index], times[index - 1] + _MINIMUM_SEGMENT_SECONDS)
    for index in range(count - 2, -1, -1):
        times[index] = min(times[index], times[index + 1] - _MINIMUM_SEGMENT_SECONDS)
    strengths = [strength for _timestamp, strength in ordered]
    return times.tolist(), strengths


def _aggregate_chroma(chroma: np.ndarray, aggregate_frames: int) -> np.ndarray:
    pieces: list[np.ndarray] = []
    for start in range(0, chroma.shape[1], aggregate_frames):
        profile = np.mean(chroma[:, start : start + aggregate_frames], axis=1)
        norm = float(np.linalg.norm(profile))
        pieces.append(profile / norm if norm > 1e-12 else profile)
    return np.stack(pieces, axis=1)


def _window_profile_novelty(chroma: np.ndarray, window_bins: int) -> np.ndarray:
    novelty = np.zeros(chroma.shape[1], dtype=np.float64)
    if chroma.shape[1] < 2 * window_bins + 1:
        return novelty
    prefix = np.concatenate(
        (np.zeros((12, 1), dtype=np.float64), np.cumsum(chroma, axis=1)),
        axis=1,
    )
    for boundary in range(window_bins, chroma.shape[1] - window_bins + 1):
        left = (prefix[:, boundary] - prefix[:, boundary - window_bins]) / window_bins
        right = (prefix[:, boundary + window_bins] - prefix[:, boundary]) / window_bins
        difference = left - right
        novelty[boundary] = 0.5 * float(np.dot(difference, difference))
    return novelty


def _segment_profiles(
    features: HarmonicFeatures,
    boundary_times: list[float],
) -> list[np.ndarray]:
    centers = features.frame_centers_seconds
    profiles: list[np.ndarray] = []
    profile_bins = 16
    for start, end in zip(boundary_times, boundary_times[1:]):
        mask = (centers >= start) & (centers < end)
        if not bool(np.any(mask)):
            profiles.append(np.zeros(12 * profile_bins, dtype=np.float64))
            continue
        frames = features.chroma[:, mask]
        indices = np.rint(np.linspace(0, frames.shape[1] - 1, num=profile_bins)).astype(int)
        sequence = frames[:, indices]
        frame_norms = np.linalg.norm(sequence, axis=0)
        normalized = np.divide(
            sequence,
            frame_norms,
            out=np.zeros_like(sequence),
            where=frame_norms > 1e-12,
        )
        profile = normalized.flatten(order="F")
        norm = float(np.linalg.norm(profile))
        profiles.append(profile / norm if norm > 1e-12 else profile)
    return profiles


def _segment_evidence(
    features: HarmonicFeatures,
    boundary_times: list[float],
) -> list[bool]:
    centers = features.frame_centers_seconds
    chroma = np.maximum(features.chroma, 0.0)
    totals = np.sum(chroma, axis=0)
    sorted_chroma = np.sort(chroma, axis=0)
    concentration = np.divide(
        np.sum(sorted_chroma[-3:, :], axis=0),
        totals,
        out=np.zeros_like(totals),
        where=totals > 1e-12,
    )
    evidence: list[bool] = []
    for start, end in zip(boundary_times, boundary_times[1:]):
        mask = (centers >= start) & (centers < end)
        if not bool(np.any(mask)):
            evidence.append(False)
            continue
        active = (features.rms[mask] > 1e-4) & (concentration[mask] >= 0.55)
        evidence.append(float(np.mean(active)) >= 0.6)
    return evidence


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
            similarities.append(0.0)
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
