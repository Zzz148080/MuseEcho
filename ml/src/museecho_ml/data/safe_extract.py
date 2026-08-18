from __future__ import annotations

import argparse
import json
import ntpath
import os
import shutil
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


def safe_extract_archive(archive_path: Path, destination: Path) -> dict[str, Any]:
    """Validate and atomically extract a ZIP or TAR archive.

    Only regular files and directories are accepted. Absolute paths, parent
    traversal, Windows drive paths, links, devices, and case-insensitive path
    collisions are rejected before any archive member is written.
    """

    archive = archive_path.resolve(strict=True)
    if not archive.is_file():
        raise ValueError("archive must be a file")
    target = destination.resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"extraction destination already exists: {target}")
    temporary = target.with_name(f"{target.name}.extracting")
    if temporary.exists():
        raise FileExistsError(f"temporary extraction destination already exists: {temporary}")

    temporary.mkdir()
    try:
        if zipfile.is_zipfile(archive):
            member_count = _extract_zip(archive, temporary)
            archive_type = "zip"
        elif tarfile.is_tarfile(archive):
            member_count = _extract_tar(archive, temporary)
            archive_type = "tar"
        else:
            raise ValueError("archive must be a readable ZIP or TAR file")
        os.replace(temporary, target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {
        "schema_version": 1,
        "archive_name": archive.name,
        "archive_type": archive_type,
        "member_count": member_count,
        "destination": str(target),
    }


def _extract_zip(archive_path: Path, destination: Path) -> int:
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        _validate_unique_paths(item.filename for item in members)
        for item in members:
            mode = item.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError(f"ZIP links are not allowed: {item.filename}")
        archive.extractall(destination, members=members)
    return len(members)


def _extract_tar(archive_path: Path, destination: Path) -> int:
    with tarfile.open(archive_path, mode="r:*") as archive:
        members = archive.getmembers()
        _validate_unique_paths(member.name for member in members)
        for member in members:
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"TAR links and special files are not allowed: {member.name}")
        archive.extractall(destination, members=members, filter="data")
    return len(members)


def _validate_unique_paths(names: object) -> None:
    seen: set[str] = set()
    for raw_name in names:
        if not isinstance(raw_name, str) or not raw_name:
            raise ValueError("archive member path must be a non-empty string")
        normalized = raw_name.replace("\\", "/")
        drive, _ = ntpath.splitdrive(normalized)
        path = PurePosixPath(normalized)
        if drive or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError(f"unsafe archive member path: {raw_name}")
        collision_key = "/".join(path.parts).casefold()
        if collision_key in seen:
            raise ValueError(f"archive member path is duplicated or ambiguous: {raw_name}")
        seen.add(collision_key)


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely extract a ZIP or TAR archive")
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    report = safe_extract_archive(args.archive, args.destination)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
