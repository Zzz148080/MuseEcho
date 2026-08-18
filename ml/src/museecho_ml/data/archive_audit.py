from __future__ import annotations

import argparse
import io
import json
import math
import tarfile
import wave
import zipfile
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from typing import Any, BinaryIO


def audit_audio_archive(path: Path) -> dict[str, Any]:
    """Read WAV headers in a ZIP or TAR archive without extracting audio."""

    archive = path.resolve(strict=True)
    if not archive.is_file():
        raise ValueError("audio archive must be a file")
    if zipfile.is_zipfile(archive):
        durations, invalid = _audit_zip(archive)
        archive_type = "zip"
    elif tarfile.is_tarfile(archive):
        durations, invalid = _audit_tar(archive)
        archive_type = "tar"
    else:
        raise ValueError("audio archive must be a readable ZIP or TAR file")
    if not durations:
        raise ValueError("audio archive does not contain readable WAV files")
    total_seconds = math.fsum(duration for _, duration in durations)
    values = [duration for _, duration in durations]
    return {
        "schema_version": 1,
        "archive_name": archive.name,
        "archive_size_bytes": archive.stat().st_size,
        "archive_type": archive_type,
        "audio_file_count": len(durations),
        "invalid_audio_count": len(invalid),
        "invalid_audio_files": sorted(invalid),
        "total_audio_seconds": round(total_seconds, 6),
        "total_audio_hours": round(total_seconds / 3600, 6),
        "minimum_audio_seconds": round(min(values), 6),
        "maximum_audio_seconds": round(max(values), 6),
    }


def _audit_zip(path: Path) -> tuple[list[tuple[str, float]], list[str]]:
    durations: list[tuple[str, float]] = []
    invalid: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = sorted(
            item.filename
            for item in archive.infolist()
            if not item.is_dir() and _is_audio_member(item.filename)
        )
        for name in names:
            try:
                with archive.open(name) as source:
                    durations.append((name, _wav_duration(source)))
            except (EOFError, OSError, ValueError, wave.Error):
                invalid.append(name)
    return durations, invalid


def _audit_tar(path: Path) -> tuple[list[tuple[str, float]], list[str]]:
    durations: list[tuple[str, float]] = []
    invalid: list[str] = []
    # Stream compressed TAR files once. Calling ``getmembers()`` first leaves the
    # gzip reader at EOF; extracting each earlier member then repeatedly seeks
    # and re-decompresses the archive, which is prohibitively slow for corpora.
    with tarfile.open(path, mode="r|*") as archive:
        for member in archive:
            if not member.isfile() or not _is_audio_member(member.name):
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                invalid.append(member.name)
                continue
            try:
                with closing(extracted):
                    # ``tarfile`` stream-mode members are forward-only, while
                    # ``wave`` seeks while walking RIFF chunks. Buffer only the
                    # current member so the compressed TAR itself remains a
                    # single-pass read.
                    durations.append(
                        (member.name, _wav_duration(io.BytesIO(extracted.read())))
                    )
            except (EOFError, OSError, ValueError, wave.Error):
                invalid.append(member.name)
    return durations, invalid


def _is_audio_member(name: str) -> bool:
    """Identify real WAV payloads, excluding macOS AppleDouble sidecars."""

    path = Path(name.replace("\\", "/"))
    return (
        path.suffix.lower() == ".wav"
        and not path.name.startswith("._")
        and "__MACOSX" not in path.parts
    )


def _wav_duration(source: BinaryIO) -> float:
    with wave.open(source, "rb") as audio:
        frame_rate = audio.getframerate()
        frame_count = audio.getnframes()
        if frame_rate <= 0 or frame_count <= 0:
            raise ValueError("WAV duration metadata is invalid")
        duration = frame_count / frame_rate
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("WAV duration is invalid")
        return duration


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Audit WAV duration in a ZIP or TAR archive without extracting it"
    )
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = audit_audio_archive(args.archive)
    if args.output is not None:
        _write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
