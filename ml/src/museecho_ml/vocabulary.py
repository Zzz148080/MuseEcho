from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from museecho_ml.artifacts import canonical_sha256
from museecho_ml.labels import BASS_INTERVALS, PITCH_NAMES, SUPPORTED_QUALITIES, CanonicalChord

ROOT_LABELS = (*PITCH_NAMES, "N", "X")
QUALITY_LABELS = (*SUPPORTED_QUALITIES, "N", "X")
BASS_LABELS = (*BASS_INTERVALS, "N", "X")


@dataclass(frozen=True)
class EncodedChord:
    root: int
    quality: int
    bass: int


@dataclass(frozen=True)
class ChordVocabulary:
    root_labels: tuple[str, ...]
    quality_labels: tuple[str, ...]
    bass_labels: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_labels(self.root_labels, ROOT_LABELS, "root")
        _validate_labels(self.quality_labels, QUALITY_LABELS, "quality")
        _validate_labels(self.bass_labels, BASS_LABELS, "bass")

    @classmethod
    def default(cls) -> ChordVocabulary:
        return cls(ROOT_LABELS, QUALITY_LABELS, BASS_LABELS)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ChordVocabulary:
        if not isinstance(value, Mapping):
            raise ValueError("vocabulary must be an object")
        embedded_hash = value.get("vocabulary_sha256")
        if embedded_hash is not None:
            body = dict(value)
            del body["vocabulary_sha256"]
            if (
                not isinstance(embedded_hash, str)
                or canonical_sha256(body) != embedded_hash
            ):
                raise ValueError("vocabulary SHA-256 does not match")
        labels: dict[str, tuple[str, ...]] = {}
        for head in ("root", "quality", "bass"):
            raw = value.get(f"{head}_labels")
            if not isinstance(raw, list):
                raise ValueError(f"vocabulary {head}_labels must be a list")
            labels[head] = tuple(raw)
        return cls(
            root_labels=labels["root"],
            quality_labels=labels["quality"],
            bass_labels=labels["bass"],
        )

    def encode(self, chord: CanonicalChord) -> EncodedChord:
        _validate_state(chord)
        try:
            return EncodedChord(
                self.root_labels.index(chord.root),
                self.quality_labels.index(chord.quality),
                self.bass_labels.index(chord.bass),
            )
        except ValueError:
            raise ValueError("chord state is outside this vocabulary") from None

    def decode(self, encoded: EncodedChord) -> CanonicalChord:
        root = _label_at(self.root_labels, encoded.root, "root")
        quality = _label_at(self.quality_labels, encoded.quality, "quality")
        bass = _label_at(self.bass_labels, encoded.bass, "bass")
        chord = CanonicalChord(root, quality, bass)
        _validate_state(chord)
        return chord


def _label_at(labels: tuple[str, ...], index: int, head: str) -> str:
    if type(index) is not int or not 0 <= index < len(labels):
        raise ValueError(f"encoded {head} index is outside the vocabulary")
    return labels[index]


def _validate_state(chord: CanonicalChord) -> None:
    values = (chord.root, chord.quality, chord.bass)
    special_values = {value for value in values if value in {"N", "X"}}
    if special_values and not (len(special_values) == 1 and len(set(values)) == 1):
        raise ValueError("chord state cannot mix N or X with acoustic labels")
    if not special_values and (
        chord.root not in PITCH_NAMES
        or chord.quality not in SUPPORTED_QUALITIES
        or chord.bass not in BASS_INTERVALS
    ):
        raise ValueError("chord state is outside the supported labels")


def _validate_labels(
    labels: tuple[str, ...], allowed: tuple[str, ...], head: str
) -> None:
    if not isinstance(labels, tuple) or any(
        not isinstance(label, str) or not label for label in labels
    ):
        raise ValueError(f"vocabulary {head} labels must be non-empty strings")
    if len(set(labels)) != len(labels):
        raise ValueError(f"vocabulary {head} labels contain a duplicate")
    if len(labels) < 2 or labels[-2:] != ("N", "X"):
        raise ValueError(f"vocabulary {head} labels must end with N and X")
    if any(label not in allowed for label in labels):
        raise ValueError(f"vocabulary {head} labels contain an unsupported label")
