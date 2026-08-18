from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from museecho_ml.data.safe_extract import safe_extract_archive


def test_safe_extract_zip_is_atomic(tmp_path: Path) -> None:
    archive_path = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("dataset/audio.wav", b"audio")
        archive.writestr("dataset/labels.json", b"{}")

    destination = tmp_path / "source"
    report = safe_extract_archive(archive_path, destination)

    assert report["archive_type"] == "zip"
    assert report["member_count"] == 2
    assert (destination / "dataset" / "audio.wav").read_bytes() == b"audio"
    assert not destination.with_name("source.extracting").exists()


def test_safe_extract_tar_is_atomic(tmp_path: Path) -> None:
    archive_path = tmp_path / "fixture.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        payload = b"labels"
        item = tarfile.TarInfo("dataset/labels.csv")
        item.size = len(payload)
        archive.addfile(item, io.BytesIO(payload))

    destination = tmp_path / "source"
    report = safe_extract_archive(archive_path, destination)

    assert report["archive_type"] == "tar"
    assert (destination / "dataset" / "labels.csv").read_bytes() == b"labels"


@pytest.mark.parametrize("member_name", ["../escape.txt", "/absolute.txt", "C:/drive.txt"])
def test_safe_extract_rejects_unsafe_zip_paths(
    tmp_path: Path, member_name: str
) -> None:
    archive_path = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(member_name, b"escape")

    destination = tmp_path / "source"
    with pytest.raises(ValueError, match="unsafe archive member path"):
        safe_extract_archive(archive_path, destination)

    assert not destination.exists()
    assert not destination.with_name("source.extracting").exists()


def test_safe_extract_rejects_tar_links(tmp_path: Path) -> None:
    archive_path = tmp_path / "fixture.tar"
    with tarfile.open(archive_path, "w") as archive:
        item = tarfile.TarInfo("dataset/link")
        item.type = tarfile.SYMTYPE
        item.linkname = "../../escape"
        archive.addfile(item)

    destination = tmp_path / "source"
    with pytest.raises(ValueError, match="links and special files"):
        safe_extract_archive(archive_path, destination)

    assert not destination.exists()


def test_safe_extract_rejects_case_insensitive_collisions(tmp_path: Path) -> None:
    archive_path = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("dataset/Track.wav", b"one")
        archive.writestr("dataset/track.wav", b"two")

    with pytest.raises(ValueError, match="duplicated or ambiguous"):
        safe_extract_archive(archive_path, tmp_path / "source")
