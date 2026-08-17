from __future__ import annotations

from dataclasses import dataclass

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

    @classmethod
    def default(cls) -> ChordVocabulary:
        return cls(ROOT_LABELS, QUALITY_LABELS, BASS_LABELS)

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
