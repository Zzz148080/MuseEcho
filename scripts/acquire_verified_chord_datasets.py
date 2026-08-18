"""Acquire the approved chord datasets serially with published MD5 checks.

The large archives stay under the ignored ``ml/data`` boundary.  Downloads are
deliberately serial because Zenodo throttles concurrent transfers; interrupted
files are resumed by :mod:`download_verified_dataset`.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from download_verified_dataset import download


@dataclass(frozen=True)
class DatasetFile:
    key: str
    url: str
    output_name: str
    md5: str
    size_bytes: int


FILES = (
    DatasetFile(
        key="idmt",
        url=(
            "https://zenodo.org/api/records/7544225/files/"
            "IDMT-SMT-CHORD-SEQUENCES-2.zip/content"
        ),
        output_name="IDMT-SMT-CHORD-SEQUENCES-2.zip",
        md5="998f79d81d3bbb8d396d495d9c6c0232",
        size_bytes=13_543_282_031,
    ),
    DatasetFile(
        key="jazznet-small",
        url=(
            "https://zenodo.org/api/records/7192653/files/"
            "progressions-small.tar.gz/content"
        ),
        output_name="jazznet-progressions-small.tar.gz",
        md5="01a550cb55f3f4abb634c0481506f9c6",
        size_bytes=1_898_014_414,
    ),
    DatasetFile(
        key="jazznet-chords",
        url="https://zenodo.org/api/records/7192653/files/chords.tar.gz/content",
        output_name="jazznet-chords.tar.gz",
        md5="8039eb8440e4a2a9e18cb72e5f09436d",
        size_bytes=388_949_707,
    ),
    DatasetFile(
        key="guitarset-audio",
        url=(
            "https://zenodo.org/api/records/3371780/files/"
            "audio_mono-mic.zip/content"
        ),
        output_name="guitarset-audio_mono-mic-1.1.0.zip",
        md5="275966d6610ac34999b58426beb119c3",
        size_bytes=656_927_981,
    ),
    DatasetFile(
        key="babyslakh",
        url=(
            "https://zenodo.org/api/records/4603870/files/"
            "babyslakh_16k.tar.gz/content"
        ),
        output_name="babyslakh_16k-v2.tar.gz",
        md5="311096dc2bde7d61c97e930edbfc7f78",
        size_bytes=882_818_115,
    ),
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Serially download and verify approved chord datasets"
    )
    parser.add_argument(
        "--download-root", type=Path, default=Path("ml/data/downloads")
    )
    parser.add_argument(
        "--only",
        action="append",
        choices=tuple(item.key for item in FILES),
        help="download only the named catalog item; may be repeated",
    )
    parser.add_argument("--attempts", type=int, default=20)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    selected = [item for item in FILES if not args.only or item.key in args.only]
    if args.list:
        for item in selected:
            print(
                f"{item.key}\t{item.size_bytes}\t{item.md5}\t{item.output_name}",
                flush=True,
            )
        return
    if args.attempts < 1:
        parser.error("--attempts must be positive")

    for item in selected:
        print(f"acquiring={item.key} expected_bytes={item.size_bytes}", flush=True)
        download(
            url=item.url,
            output=args.download_root / item.output_name,
            algorithm="md5",
            expected=item.md5,
            attempts=args.attempts,
        )


if __name__ == "__main__":
    main()
