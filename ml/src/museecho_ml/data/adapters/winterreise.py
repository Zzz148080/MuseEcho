from __future__ import annotations

import re
import wave
from pathlib import Path

from museecho_ml.data.adapters.base import CsvChordAdapter
from museecho_ml.data.manifest import LocalTrackSource

_TRACK_PATTERN = re.compile(r"^(?P<work>Schubert_D911-\d{2})_(?P<performance>HU33|SC06)$")


class WinterreiseAdapter(CsvChordAdapter):
    """Read normalized Winterreise chord CSV files with named columns."""


def discover_winterreise_sources(dataset_root: Path) -> tuple[LocalTrackSource, ...]:
    """Pair the distributable Winterreise WAV files with their audio chord annotations."""

    root = dataset_root.resolve(strict=True)
    audio_root = root / "01_RawData" / "audio_wav"
    annotation_root = root / "02_Annotations" / "ann_audio_chord"
    if not audio_root.is_dir() or not annotation_root.is_dir():
        raise ValueError("Winterreise dataset is missing its audio or annotation directory")

    sources: list[LocalTrackSource] = []
    for audio_path in sorted(audio_root.glob("*.wav"), key=lambda path: path.name):
        match = _TRACK_PATTERN.fullmatch(audio_path.stem)
        if match is None:
            raise ValueError(f"unexpected Winterreise audio filename: {audio_path.name}")
        annotation_path = annotation_root / f"{audio_path.stem}.csv"
        if not annotation_path.is_file():
            raise ValueError(f"Winterreise annotation is missing for {audio_path.name}")
        sources.append(
            LocalTrackSource(
                dataset_id="schubert-winterreise",
                track_id=audio_path.stem,
                work_id=match.group("work"),
                cover_group_id=match.group("work"),
                artist_id=match.group("performance"),
                audio_path=audio_path,
                annotation_path=annotation_path,
                duration_seconds=_wav_duration_seconds(audio_path),
            )
        )
    if not sources:
        raise ValueError("Winterreise dataset does not contain packaged WAV recordings")
    return tuple(sources)


def _wav_duration_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as audio:
            frame_rate = audio.getframerate()
            frame_count = audio.getnframes()
    except (EOFError, wave.Error):
        raise ValueError(f"Winterreise audio is not a readable WAV file: {path.name}") from None
    if frame_rate <= 0 or frame_count <= 0:
        raise ValueError(f"Winterreise audio has an invalid duration: {path.name}")
    return frame_count / frame_rate
