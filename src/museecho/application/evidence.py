from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from museecho.domain.models import AnalysisResult, Evidence, TimeSeries
from museecho.theory.chords import parse_chord
from museecho.theory.notes import parse_note

_THEORY_FIELDS = frozenset(
    {
        "algorithm",
        "enharmonic_candidates",
        "functions",
        "intervals",
        "is_diatonic",
        "limitations",
        "mode",
        "pitch_classes",
        "quality",
        "roman_numeral",
        "symbol",
        "tonic",
    }
)
_LLM_KIND_ALLOWLIST = frozenset(
    {
        "rhythm",
        "energy",
        "tonality",
        "section",
        "chord",
        "deterministic_theory",
    }
)
_EVIDENCE_ID_VERSION = "evidence-id-v1"
_THEORY_FUNCTIONS = frozenset(
    {
        "tonic",
        "tonic-prolongation",
        "tonic-substitute",
        "predominant",
        "dominant",
        "dominant-substitute",
    }
)
_THEORY_INTERVALS = frozenset({"root", "major third", "minor third", "perfect fifth"})
_THEORY_ROMAN_NUMERALS = frozenset(
    {"I", "ii", "iii", "IV", "V", "vi", "vii°", "i", "ii°", "III", "iv", "v", "VI", "VII"}
)
_THEORY_LIMITATIONS = frozenset(
    {
        "unsupported-chord",
        "key-context-unavailable",
        "non-diatonic",
        "raised-leading-tone",
        "enharmonic-key-spelling",
    }
)


@dataclass(frozen=True)
class EvidencePolicy:
    version: str = "evidence-policy-v1"
    rhythm_minimum_confidence: float = 0.7
    energy_minimum_confidence: float = 0.7
    tonality_minimum_confidence: float = 0.7
    section_minimum_confidence: float = 0.7
    chord_minimum_confidence: float = 0.7
    max_selected_items: int = 32
    max_payload_characters: int = 8_192

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("version cannot be empty")
        thresholds = (
            self.rhythm_minimum_confidence,
            self.energy_minimum_confidence,
            self.tonality_minimum_confidence,
            self.section_minimum_confidence,
            self.chord_minimum_confidence,
        )
        if any(
            type(value) not in {int, float} or not math.isfinite(value) or not 0.0 <= value <= 1.0
            for value in thresholds
        ):
            raise ValueError("evidence confidence thresholds must be between 0 and 1")
        if type(self.max_selected_items) is not int or self.max_selected_items <= 0:
            raise ValueError("max_selected_items must be a positive integer")
        if type(self.max_payload_characters) is not int or self.max_payload_characters <= 0:
            raise ValueError("max_payload_characters must be a positive integer")


def build_evidence(
    result: AnalysisResult,
    *,
    policy: EvidencePolicy | None = None,
) -> tuple[Evidence, ...]:
    result.validate()
    selected = policy or EvidencePolicy()
    items: list[Evidence] = []
    track = result.track
    if track.bpm is not None and track.bpm_confidence is not None:
        items.append(
            _track_evidence(
                track.analysis_id,
                discriminator="bpm",
                kind="rhythm",
                duration_seconds=track.duration_seconds,
                value={"bpm": track.bpm},
                confidence=track.bpm_confidence,
                minimum_confidence=selected.rhythm_minimum_confidence,
                algorithm="track-rhythm",
                source_known=_has_allowed_public_shape("rhythm", {"bpm": track.bpm}),
            )
        )
    if track.time_signature is not None and track.time_signature_confidence is not None:
        items.append(
            _track_evidence(
                track.analysis_id,
                discriminator="time-signature",
                kind="rhythm",
                duration_seconds=track.duration_seconds,
                value={"time_signature": track.time_signature},
                confidence=track.time_signature_confidence,
                minimum_confidence=selected.rhythm_minimum_confidence,
                algorithm="track-time-signature",
                source_known=_has_allowed_public_shape(
                    "rhythm",
                    {"time_signature": track.time_signature},
                ),
            )
        )
    if track.key_tonic is not None and track.mode is not None and track.key_confidence is not None:
        items.append(
            _track_evidence(
                track.analysis_id,
                discriminator="tonality",
                kind="tonality",
                duration_seconds=track.duration_seconds,
                value={"tonic": track.key_tonic, "mode": track.mode},
                confidence=track.key_confidence,
                minimum_confidence=selected.tonality_minimum_confidence,
                algorithm="track-tonality",
                source_known=_has_allowed_public_shape(
                    "tonality",
                    {"tonic": track.key_tonic, "mode": track.mode},
                ),
            )
        )
    for section in result.sections:
        section_value = {"label": section.label}
        eligible = (
            section.confidence >= selected.section_minimum_confidence
            and _has_allowed_public_shape("section", section_value)
        )
        items.append(
            Evidence(
                id=uuid.uuid5(section.id, f"{_EVIDENCE_ID_VERSION}:section"),
                analysis_id=section.analysis_id,
                kind="section",
                start_seconds=section.start_seconds,
                end_seconds=section.end_seconds,
                value_json=section_value if eligible else None,
                confidence=section.confidence,
                algorithm=section.algorithm,
                eligible_for_llm=eligible,
            )
        )
    for chord in result.chords:
        chord_value = {"symbol": chord.symbol}
        eligible = (
            chord.confidence >= selected.chord_minimum_confidence
            and _has_allowed_public_shape("chord", chord_value)
        )
        items.append(
            Evidence(
                id=uuid.uuid5(chord.id, f"{_EVIDENCE_ID_VERSION}:chord"),
                analysis_id=chord.analysis_id,
                kind="chord",
                start_seconds=chord.start_seconds,
                end_seconds=chord.end_seconds,
                value_json=chord_value if eligible else None,
                confidence=chord.confidence,
                algorithm=chord.algorithm,
                eligible_for_llm=eligible,
            )
        )
        if chord.theory_json is not None:
            theory_value = {
                key: value for key, value in chord.theory_json.items() if key in _THEORY_FIELDS
            }
            theory_algorithm = theory_value.get("algorithm")
            theory_eligible = eligible and _valid_theory_value(theory_value)
            items.append(
                Evidence(
                    id=uuid.uuid5(
                        chord.id,
                        f"{_EVIDENCE_ID_VERSION}:deterministic_theory",
                    ),
                    analysis_id=chord.analysis_id,
                    kind="deterministic_theory",
                    start_seconds=chord.start_seconds,
                    end_seconds=chord.end_seconds,
                    value_json=theory_value if theory_eligible else None,
                    confidence=chord.confidence,
                    algorithm=(
                        theory_algorithm
                        if isinstance(theory_algorithm, str)
                        else "deterministic-theory"
                    ),
                    eligible_for_llm=theory_eligible,
                )
            )
    energy_ids: set[uuid.UUID] = set()
    for series in result.time_series:
        if series.kind != "energy" or not series.points_json:
            continue
        evidence_id = _energy_evidence_id(track.analysis_id, series)
        if evidence_id in energy_ids:
            continue
        energy_ids.add(evidence_id)
        points = series.points_json
        source_known = all(0.0 <= point <= 1.0 for point in points)
        confidence = 1.0 if source_known else 0.0
        eligible = confidence >= selected.energy_minimum_confidence
        end_seconds = min(
            track.duration_seconds,
            len(points) * series.resolution_seconds,
        )
        items.append(
            Evidence(
                id=evidence_id,
                analysis_id=track.analysis_id,
                kind="energy",
                start_seconds=0.0,
                end_seconds=end_seconds,
                value_json=(
                    {
                        "minimum": min(points),
                        "maximum": max(points),
                        "mean": sum(points) / len(points),
                        "resolution_seconds": series.resolution_seconds,
                        "point_count": len(points),
                    }
                    if eligible
                    else None
                ),
                confidence=confidence,
                algorithm=series.algorithm,
                eligible_for_llm=eligible,
            )
        )
    return tuple(items)


def select_for_segment(
    evidence: Sequence[Evidence],
    start_seconds: float,
    end_seconds: float,
    *,
    policy: EvidencePolicy | None = None,
) -> tuple[Evidence, ...]:
    if (
        not math.isfinite(start_seconds)
        or not math.isfinite(end_seconds)
        or start_seconds < 0.0
        or end_seconds <= start_seconds
    ):
        raise ValueError("segment must be a finite non-negative interval")
    analysis_ids = {item.analysis_id for item in evidence}
    if len(analysis_ids) > 1:
        raise ValueError("evidence from different analyses cannot be mixed")
    selected_policy = policy or EvidencePolicy()
    candidates = sorted(
        (
            item
            for item in evidence
            if isinstance(item.kind, str)
            and item.kind in _LLM_KIND_ALLOWLIST
            and _valid_algorithm(item.algorithm)
            and item.eligible_for_llm
            and item.value_json is not None
            and item.confidence >= _minimum_confidence(selected_policy, item.kind)
            and not _is_unknown(item.public_value)
            and _has_allowed_public_shape(item.kind, item.public_value)
            and item.start_seconds < end_seconds
            and start_seconds < item.end_seconds
        ),
        key=lambda item: (
            item.start_seconds,
            item.end_seconds,
            item.kind,
            str(item.id),
        ),
    )
    selected: list[Evidence] = []
    seen_ids: set[uuid.UUID] = set()
    character_count = 2
    for item in candidates:
        if item.id in seen_ids:
            continue
        separator_size = 1 if selected else 0
        payload_size = len(_serialize_for_llm(item)) + separator_size
        if character_count + payload_size > selected_policy.max_payload_characters:
            continue
        selected.append(item)
        seen_ids.add(item.id)
        character_count += payload_size
        if len(selected) >= selected_policy.max_selected_items:
            break
    return tuple(selected)


def _serialize_for_llm(evidence: Evidence) -> str:
    return json.dumps(
        {
            "id": str(evidence.id),
            "kind": evidence.kind,
            "start_seconds": evidence.start_seconds,
            "end_seconds": evidence.end_seconds,
            "public_value": evidence.public_value,
            "confidence": evidence.confidence,
            "algorithm": evidence.algorithm,
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _energy_evidence_id(analysis_id: uuid.UUID, series: TimeSeries) -> uuid.UUID:
    identity = json.dumps(
        {
            "algorithm": series.algorithm,
            "resolution_seconds": series.resolution_seconds,
            "points": series.points_json,
        },
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()
    return uuid.uuid5(analysis_id, f"{_EVIDENCE_ID_VERSION}:energy:{digest}")


def _track_evidence(
    analysis_id: uuid.UUID,
    *,
    discriminator: str,
    kind: str,
    duration_seconds: float,
    value: dict[str, object],
    confidence: float,
    minimum_confidence: float,
    algorithm: str,
    source_known: bool = True,
) -> Evidence:
    eligible = confidence >= minimum_confidence and source_known
    return Evidence(
        id=uuid.uuid5(
            analysis_id,
            f"{_EVIDENCE_ID_VERSION}:{discriminator}",
        ),
        analysis_id=analysis_id,
        kind=kind,
        start_seconds=0.0,
        end_seconds=duration_seconds,
        value_json=value if eligible else None,
        confidence=confidence,
        algorithm=algorithm,
        eligible_for_llm=eligible,
    )


def _known_text(value: str) -> bool:
    normalized = value.strip().casefold()
    return bool(normalized) and normalized != "unknown"


def _valid_algorithm(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and value.isascii()
        and all(character.isalnum() or character in "-_." for character in value)
    )


def _is_unknown(value: object) -> bool:
    if value is None:
        return True
    return isinstance(value, str) and value.strip().casefold() in {"", "unknown"}


def _has_allowed_public_shape(kind: str, value: object) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    if not all(isinstance(field, str) for field in value):
        return False
    facts = cast(dict[str, object], value)
    fields = set(facts)
    if kind == "rhythm":
        if not fields <= {"bpm", "time_signature"}:
            return False
        if "bpm" in facts:
            bpm = _as_finite_float(facts["bpm"])
            if bpm is None or bpm <= 0.0:
                return False
        return "time_signature" not in facts or _valid_time_signature(facts["time_signature"])
    if kind == "energy":
        if fields != {
            "minimum",
            "maximum",
            "mean",
            "resolution_seconds",
            "point_count",
        }:
            return False
        minimum = _as_finite_float(facts["minimum"])
        maximum = _as_finite_float(facts["maximum"])
        mean = _as_finite_float(facts["mean"])
        resolution = _as_finite_float(facts["resolution_seconds"])
        point_count = facts["point_count"]
        return (
            minimum is not None
            and maximum is not None
            and mean is not None
            and resolution is not None
            and 0.0 <= minimum <= mean <= maximum <= 1.0
            and resolution > 0.0
            and type(point_count) is int
            and point_count > 0
        )
    if kind == "tonality":
        tonic = facts.get("tonic")
        mode = facts.get("mode")
        return (
            fields == {"tonic", "mode"}
            and isinstance(tonic, str)
            and parse_note(tonic) is not None
            and mode in {"major", "minor"}
        )
    if kind == "section":
        label = facts.get("label")
        return (
            fields == {"label"}
            and isinstance(label, str)
            and 1 <= len(label) <= 4
            and label.isascii()
            and label.isalpha()
            and label.isupper()
        )
    if kind == "chord":
        symbol = facts.get("symbol")
        return fields == {"symbol"} and isinstance(symbol, str) and parse_chord(symbol) is not None
    if kind == "deterministic_theory":
        return _valid_theory_value(facts)
    return False


def _as_finite_float(value: object) -> float | None:
    if type(value) not in {int, float}:
        return None
    number = float(cast(int | float, value))
    return number if math.isfinite(number) else None


def _valid_time_signature(value: object) -> bool:
    if not isinstance(value, str) or value.count("/") != 1:
        return False
    numerator, denominator = value.split("/")
    return (
        numerator.isascii()
        and denominator.isascii()
        and numerator.isdigit()
        and denominator.isdigit()
        and int(numerator) > 0
        and int(denominator) > 0
    )


def _valid_theory_value(value: dict[str, object]) -> bool:
    fields = set(value)
    if not fields <= _THEORY_FIELDS:
        return False
    for field, item in value.items():
        if field == "pitch_classes":
            valid = (
                isinstance(item, list)
                and bool(item)
                and all(isinstance(note, str) and parse_note(note) is not None for note in item)
            )
        elif field == "intervals":
            valid = (
                isinstance(item, list)
                and bool(item)
                and all(
                    isinstance(interval, str) and interval in _THEORY_INTERVALS for interval in item
                )
            )
        elif field == "quality":
            valid = item is None or (isinstance(item, str) and item in {"major", "minor"})
        elif field == "roman_numeral":
            valid = item is None or (isinstance(item, str) and item in _THEORY_ROMAN_NUMERALS)
        elif field == "functions":
            valid = isinstance(item, list) and all(
                isinstance(function, str) and function in _THEORY_FUNCTIONS for function in item
            )
        elif field == "is_diatonic":
            valid = item is None or type(item) is bool
        elif field == "enharmonic_candidates":
            valid = isinstance(item, list) and all(
                isinstance(symbol, str) and parse_chord(symbol) is not None for symbol in item
            )
        elif field == "limitations":
            valid = isinstance(item, list) and all(
                isinstance(limitation, str) and limitation in _THEORY_LIMITATIONS
                for limitation in item
            )
        elif field == "symbol":
            valid = item is None or (isinstance(item, str) and parse_chord(item) is not None)
        elif field == "tonic":
            valid = item is None or (isinstance(item, str) and parse_note(item) is not None)
        elif field == "mode":
            valid = item is None or (isinstance(item, str) and item in {"major", "minor"})
        else:
            valid = item == "deterministic-triad-theory-v1"
        if not valid:
            return False
    fact_fields = {
        "pitch_classes",
        "intervals",
        "quality",
        "roman_numeral",
        "functions",
        "is_diatonic",
    }
    return any(field in value and value[field] not in (None, (), [], {}) for field in fact_fields)


def _minimum_confidence(policy: EvidencePolicy, kind: str) -> float:
    if kind == "rhythm":
        return policy.rhythm_minimum_confidence
    if kind == "energy":
        return policy.energy_minimum_confidence
    if kind == "tonality":
        return policy.tonality_minimum_confidence
    if kind == "section":
        return policy.section_minimum_confidence
    return policy.chord_minimum_confidence
