import csv
import re
import wave
from collections.abc import Iterable
from pathlib import Path

from museecho_ml.data.adapters.base import CsvChordAdapter, LabChordAdapter
from museecho_ml.data.manifest import ChordInterval, LocalTrackSource

_RWC_POPULAR_ID = re.compile(r"^RWC_P\d{3}$")


class RwcAdapter(CsvChordAdapter):
    """Read official RWC 2.0 chord CSV files and legacy local LAB exports."""

    def _read_intervals(self, annotation: Path) -> Iterable[ChordInterval]:
        if annotation.suffix.lower() == ".lab":
            yield from LabChordAdapter._read_intervals(self, annotation)
            return
        yield from super()._read_intervals(annotation)


def discover_rwc_sources(
    audio_root: Path, annotations_root: Path
) -> tuple[LocalTrackSource, ...]:
    """Pair RWC-P audio with the official curated annotations and metadata."""

    resolved_audio_root = audio_root.resolve(strict=True)
    resolved_annotations_root = annotations_root.resolve(strict=True)
    metadata_path = resolved_annotations_root / "metadata.csv"
    chord_root = (
        resolved_annotations_root
        / "01_annotations_preprocessed"
        / "chords"
        / "RWC-P"
    )
    if not metadata_path.is_file() or not chord_root.is_dir():
        raise ValueError("RWC annotations are missing metadata or the RWC-P chord directory")

    audio_by_id: dict[str, Path] = {}
    for audio_path in resolved_audio_root.rglob("*.wav"):
        if not _RWC_POPULAR_ID.fullmatch(audio_path.stem):
            continue
        if audio_path.stem in audio_by_id:
            raise ValueError(f"duplicate RWC audio file for {audio_path.stem}")
        audio_by_id[audio_path.stem] = audio_path

    sources: list[LocalTrackSource] = []
    with metadata_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, delimiter=";")
        required = {"RWCID", "CollID", "Artist"}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError("RWC metadata is missing required columns")
        for row in reader:
            if row["CollID"] != "P":
                continue
            track_id = row["RWCID"]
            if not _RWC_POPULAR_ID.fullmatch(track_id):
                raise ValueError(f"RWC-P metadata has an invalid identifier: {track_id}")
            audio_path = audio_by_id.get(track_id)
            if audio_path is None:
                raise ValueError(f"RWC audio is missing for {track_id}")
            annotation_path = chord_root / f"{track_id}.csv"
            if not annotation_path.is_file():
                raise ValueError(f"RWC chord annotation is missing for {track_id}")
            artist = row["Artist"].strip() or None
            sources.append(
                LocalTrackSource(
                    dataset_id="rwc-popular",
                    track_id=track_id,
                    work_id=track_id,
                    cover_group_id=track_id,
                    artist_id=artist,
                    audio_path=audio_path,
                    annotation_path=annotation_path,
                    duration_seconds=_wav_duration_seconds(audio_path),
                )
            )
    if not sources:
        raise ValueError("RWC metadata does not contain popular-music tracks")
    if len(sources) != len(audio_by_id):
        unused = sorted(set(audio_by_id) - {source.track_id for source in sources})
        raise ValueError(f"RWC audio contains files not represented by metadata: {unused[0]}")
    return tuple(sorted(sources, key=lambda source: source.track_id))


def _wav_duration_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as audio:
            frame_rate = audio.getframerate()
            frame_count = audio.getnframes()
    except (EOFError, wave.Error):
        raise ValueError(f"RWC audio is not a readable WAV file: {path.name}") from None
    if frame_rate <= 0 or frame_count <= 0:
        raise ValueError(f"RWC audio has an invalid duration: {path.name}")
    return frame_count / frame_rate
