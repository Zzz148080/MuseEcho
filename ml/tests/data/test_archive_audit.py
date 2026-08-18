from __future__ import annotations

import io
import tarfile
import wave
import zipfile
from pathlib import Path

import pytest

from museecho_ml.data.archive_audit import audit_audio_archive


def _wav_bytes(duration_seconds: float, sample_rate: int = 8000) -> bytes:
    target = io.BytesIO()
    with wave.open(target, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\x00\x00" * round(duration_seconds * sample_rate))
    return target.getvalue()


def test_audit_zip_sums_headers_without_extracting(tmp_path: Path) -> None:
    archive_path = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("audio/b.wav", _wav_bytes(2.5))
        archive.writestr("audio/a.wav", _wav_bytes(1.0))
        archive.writestr("metadata.json", "{}")

    report = audit_audio_archive(archive_path)

    assert report["archive_type"] == "zip"
    assert report["audio_file_count"] == 2
    assert report["total_audio_seconds"] == 3.5
    assert report["minimum_audio_seconds"] == 1.0
    assert report["maximum_audio_seconds"] == 2.5
    assert report["invalid_audio_count"] == 0


def test_audit_tar_reports_invalid_wav(tmp_path: Path) -> None:
    archive_path = tmp_path / "fixture.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, payload in (
            ("audio/good.wav", _wav_bytes(3.0)),
            ("audio/broken.wav", b"not a wav"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))

    report = audit_audio_archive(archive_path)

    assert report["archive_type"] == "tar"
    assert report["audio_file_count"] == 1
    assert report["total_audio_seconds"] == 3.0
    assert report["invalid_audio_files"] == ["audio/broken.wav"]


def test_audit_rejects_archive_without_readable_wav(tmp_path: Path) -> None:
    archive_path = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("metadata.json", "{}")

    with pytest.raises(ValueError, match="readable WAV"):
        audit_audio_archive(archive_path)
