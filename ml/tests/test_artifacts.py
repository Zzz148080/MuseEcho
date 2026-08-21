from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from museecho_ml.artifacts import (
    canonical_json_bytes,
    canonical_sha256,
    file_sha256,
    write_immutable_json,
)


def test_canonical_json_is_order_independent_and_rejects_nan() -> None:
    assert canonical_json_bytes({"b": 2, "a": 1}) == b'{"a":1,"b":2}'
    assert canonical_sha256({"b": 2, "a": 1}) == hashlib.sha256(
        b'{"a":1,"b":2}'
    ).hexdigest()

    with pytest.raises(ValueError):
        canonical_json_bytes({"value": float("nan")})


def test_file_sha256_streams_file_bytes(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"plan-c\x00artifact")

    assert file_sha256(artifact) == hashlib.sha256(b"plan-c\x00artifact").hexdigest()


def test_immutable_json_accepts_identical_content_and_rejects_drift(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "frozen.json"

    write_immutable_json(artifact, {"b": 2, "a": 1})
    first = artifact.read_bytes()
    write_immutable_json(artifact, {"a": 1, "b": 2})

    assert first == b'{"a":1,"b":2}\n'
    assert artifact.read_bytes() == first
    with pytest.raises(FileExistsError, match="different content"):
        write_immutable_json(artifact, {"a": 2, "b": 2})
    assert not tuple(tmp_path.glob("*.tmp"))
