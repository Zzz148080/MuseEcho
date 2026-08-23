from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import museecho_ml.artifacts as artifacts_module
from museecho_ml.artifacts import (
    canonical_json_bytes,
    canonical_sha256,
    file_sha256,
    write_immutable_bytes,
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


def test_immutable_json_temporary_name_does_not_embed_destination_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_mkstemp = artifacts_module.tempfile.mkstemp
    prefixes: list[str] = []

    def recording_mkstemp(*args, **kwargs):
        prefixes.append(kwargs["prefix"])
        return real_mkstemp(*args, **kwargs)

    monkeypatch.setattr(artifacts_module.tempfile, "mkstemp", recording_mkstemp)

    write_immutable_json(tmp_path / "audit-v1.json", {"status": "completed"})

    assert prefixes == [".immutable-json."]


def test_immutable_bytes_accepts_identical_content_and_rejects_drift(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "predictions.jsonl"

    write_immutable_bytes(artifact, b'{"track_id":"one"}\n')
    write_immutable_bytes(artifact, b'{"track_id":"one"}\n')

    assert artifact.read_bytes() == b'{"track_id":"one"}\n'
    with pytest.raises(FileExistsError, match="different content"):
        write_immutable_bytes(artifact, b'{"track_id":"two"}\n')
    assert not tuple(tmp_path.glob("*.tmp"))
