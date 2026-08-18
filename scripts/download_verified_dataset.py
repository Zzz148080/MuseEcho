"""Resume a dataset download and verify its published checksum.

The final path is only replaced after the complete temporary download matches the
expected digest. Interrupted downloads remain as ``<output>.part`` and can be
resumed by running the same command again.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _digest(path: Path, algorithm: str) -> str:
    checksum = hashlib.new(algorithm)
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            checksum.update(chunk)
    return checksum.hexdigest()


def _download_once(url: str, partial: Path) -> None:
    offset = partial.stat().st_size if partial.exists() else 0
    request = urllib.request.Request(url)
    if offset:
        request.add_header("Range", f"bytes={offset}-")

    with urllib.request.urlopen(request, timeout=120) as response:
        append = offset > 0 and response.status == 206
        mode = "ab" if append else "wb"
        downloaded = offset if append else 0
        total_header = response.headers.get("Content-Length")
        total = downloaded + int(total_header) if total_header else None
        last_report = downloaded
        with partial.open(mode) as target:
            while chunk := response.read(8 * 1024 * 1024):
                target.write(chunk)
                downloaded += len(chunk)
                if downloaded - last_report >= 256 * 1024 * 1024:
                    if total:
                        percent = downloaded * 100 / total
                        print(
                            f"downloaded={downloaded} total={total} "
                            f"percent={percent:.2f}",
                            flush=True,
                        )
                    else:
                        print(f"downloaded={downloaded}", flush=True)
                    last_report = downloaded


def download(
    *,
    url: str,
    output: Path,
    algorithm: str,
    expected: str,
    attempts: int,
) -> None:
    expected = expected.lower()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f"{output.name}.part")

    if output.exists():
        actual = _digest(output, algorithm)
        if actual == expected:
            print(f"verified existing file: {output}")
            return
        raise RuntimeError(
            f"existing final file checksum mismatch: expected {expected}, got {actual}"
        )

    for attempt in range(1, attempts + 1):
        try:
            _download_once(url, partial)
            break
        except (OSError, urllib.error.URLError) as error:
            if attempt == attempts:
                raise
            delay = min(2 ** (attempt - 1), 16)
            print(
                f"download attempt {attempt} failed: {error}; retrying in {delay}s",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay)

    actual = _digest(partial, algorithm)
    if actual != expected:
        raise RuntimeError(
            f"download checksum mismatch: expected {expected}, got {actual}; "
            f"partial retained at {partial}"
        )
    os.replace(partial, output)
    print(f"verified download: {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--algorithm", choices=("md5", "sha256"), default="md5")
    parser.add_argument("--expected", required=True)
    parser.add_argument("--attempts", type=int, default=5)
    args = parser.parse_args()
    if args.attempts < 1:
        parser.error("--attempts must be positive")
    download(
        url=args.url,
        output=args.output,
        algorithm=args.algorithm,
        expected=args.expected,
        attempts=args.attempts,
    )


if __name__ == "__main__":
    main()
