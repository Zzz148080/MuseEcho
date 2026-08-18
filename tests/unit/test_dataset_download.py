from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.download_verified_dataset import _download_once, download


class _FakeResponse:
    def __init__(self, *, status: int, content_length: int, chunks: list[bytes]):
        self.status = status
        self.headers = {"Content-Length": str(content_length)}
        self._chunks = iter(chunks)

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, _size: int) -> bytes:
        return next(self._chunks, b"")


def test_download_once_rejects_a_short_http_response(tmp_path: Path) -> None:
    partial = tmp_path / "archive.zip.part"
    response = _FakeResponse(status=200, content_length=6, chunks=[b"abc"])

    with patch(
        "scripts.download_verified_dataset.urllib.request.urlopen",
        return_value=response,
    ):
        with pytest.raises(OSError, match="incomplete HTTP response"):
            _download_once("https://example.test/archive.zip", partial)

    assert partial.read_bytes() == b"abc"


def test_download_retries_and_resumes_after_a_short_response(
    tmp_path: Path,
) -> None:
    output = tmp_path / "archive.zip"
    responses = [
        _FakeResponse(status=200, content_length=6, chunks=[b"abc"]),
        _FakeResponse(status=206, content_length=3, chunks=[b"def"]),
    ]

    with (
        patch(
            "scripts.download_verified_dataset.urllib.request.urlopen",
            side_effect=responses,
        ),
        patch("scripts.download_verified_dataset.time.sleep"),
    ):
        download(
            url="https://example.test/archive.zip",
            output=output,
            algorithm="md5",
            expected=hashlib.md5(b"abcdef").hexdigest(),
            attempts=2,
        )

    assert output.read_bytes() == b"abcdef"
    assert not output.with_name("archive.zip.part").exists()
