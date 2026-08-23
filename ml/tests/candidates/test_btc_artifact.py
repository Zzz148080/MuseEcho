from __future__ import annotations

import json
from hashlib import sha1, sha256
from pathlib import Path

import pytest

import museecho_ml.candidates.btc_artifact as btc_artifact_module
from museecho_ml.candidates.btc_artifact import (
    BtcArtifactSource,
    acquire_btc_artifact,
    load_btc_source,
    main,
    verify_btc_artifact,
)


def _git_blob_sha1(payload: bytes) -> str:
    header = b"blob " + str(len(payload)).encode("ascii") + b"\0"
    return sha1(header + payload).hexdigest()


def _source_for(payload: bytes) -> BtcArtifactSource:
    return BtcArtifactSource(
        repository="jayg996/BTC-ISMIR19",
        repository_ref="master",
        source_url=(
            "https://raw.githubusercontent.com/jayg996/BTC-ISMIR19/"
            "master/test/btc_model_large_voca.pt"
        ),
        size_bytes=len(payload),
        git_blob_sha1=_git_blob_sha1(payload),
        license_spdx="MIT",
    )


def test_verify_btc_artifact_binds_size_git_blob_and_sha256(tmp_path: Path) -> None:
    payload = b"official-checkpoint-fixture"
    checkpoint = tmp_path / "btc.pt"
    checkpoint.write_bytes(payload)

    lock = verify_btc_artifact(checkpoint, _source_for(payload))

    assert lock.sha256 == sha256(payload).hexdigest()
    assert lock.size_bytes == len(payload)
    assert lock.git_blob_sha1 == _git_blob_sha1(payload)


def test_verify_btc_artifact_rejects_size_mismatch(tmp_path: Path) -> None:
    checkpoint = tmp_path / "btc.pt"
    checkpoint.write_bytes(b"truncated")

    with pytest.raises(ValueError, match="size does not match"):
        verify_btc_artifact(checkpoint, _source_for(b"official"))


def test_verify_btc_artifact_rejects_git_blob_mismatch(tmp_path: Path) -> None:
    payload = b"official"
    checkpoint = tmp_path / "btc.pt"
    checkpoint.write_bytes(b"tampered")
    source = _source_for(payload)
    source = BtcArtifactSource(
        repository=source.repository,
        repository_ref=source.repository_ref,
        source_url=source.source_url,
        size_bytes=len(b"tampered"),
        git_blob_sha1=source.git_blob_sha1,
        license_spdx=source.license_spdx,
    )

    with pytest.raises(ValueError, match="Git blob identity"):
        verify_btc_artifact(checkpoint, source)


def test_btc_source_rejects_unapproved_host() -> None:
    with pytest.raises(ValueError, match="approved GitHub raw host"):
        BtcArtifactSource(
            repository="jayg996/BTC-ISMIR19",
            repository_ref="master",
            source_url="https://example.com/btc.pt",
            size_bytes=1,
            git_blob_sha1="0" * 40,
            license_spdx="MIT",
        )


def test_load_btc_source_rejects_unknown_or_missing_descriptor_fields(
    tmp_path: Path,
) -> None:
    descriptor = {
        "schema_version": 1,
        "candidate_version": "btc-ismir19-large-voca-v1",
        "repository": "jayg996/BTC-ISMIR19",
        "repository_ref": "master",
        "source_url": (
            "https://raw.githubusercontent.com/jayg996/BTC-ISMIR19/"
            "master/test/btc_model_large_voca.pt"
        ),
        "size_bytes": 12_229_576,
        "git_blob_sha1": "11c6edbaaaee33737aa7a41dcb9044191630326f",
        "license_spdx": "MIT",
    }
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(descriptor), encoding="utf-8")

    source = load_btc_source(source_path)

    assert source.repository == "jayg996/BTC-ISMIR19"
    assert source.size_bytes == 12_229_576

    descriptor["unexpected"] = True
    source_path.write_text(json.dumps(descriptor), encoding="utf-8")
    with pytest.raises(ValueError, match="descriptor fields"):
        load_btc_source(source_path)


class _FakeDownload:
    def __init__(self, payload: bytes, final_url: str) -> None:
        self._payload = payload
        self._offset = 0
        self._final_url = final_url

    def __enter__(self) -> _FakeDownload:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return self._final_url

    def read(self, size: int = -1) -> bytes:
        if self._offset >= len(self._payload):
            return b""
        if size < 0:
            size = len(self._payload)
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def test_acquire_btc_artifact_streams_verified_bytes_and_freezes_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"official-checkpoint-fixture"
    source = _source_for(payload)
    monkeypatch.setattr(
        btc_artifact_module,
        "urlopen",
        lambda *_args, **_kwargs: _FakeDownload(payload, source.source_url),
    )
    destination = tmp_path / "cache" / "btc.pt"
    lock_output = tmp_path / "config" / "lock.json"

    lock = acquire_btc_artifact(source, destination, lock_output)

    assert destination.read_bytes() == payload
    assert lock.sha256 == sha256(payload).hexdigest()
    frozen = json.loads(lock_output.read_text(encoding="utf-8"))
    assert frozen["sha256"] == lock.sha256
    assert frozen["git_blob_sha1"] == source.git_blob_sha1
    assert not tuple(destination.parent.glob("*.tmp"))


def test_acquire_btc_artifact_rejects_unapproved_redirect_and_cleans_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"official-checkpoint-fixture"
    source = _source_for(payload)
    monkeypatch.setattr(
        btc_artifact_module,
        "urlopen",
        lambda *_args, **_kwargs: _FakeDownload(
            payload, "https://downloads.example.com/btc.pt"
        ),
    )
    destination = tmp_path / "cache" / "btc.pt"

    with pytest.raises(ValueError, match="redirected outside"):
        acquire_btc_artifact(source, destination, tmp_path / "lock.json")

    assert not destination.exists()
    assert not tuple(destination.parent.glob("*.tmp"))


def test_acquire_cli_loads_source_and_writes_verified_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"official-checkpoint-fixture"
    source = _source_for(payload)
    source_path = tmp_path / "source.json"
    source_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "candidate_version": "btc-ismir19-large-voca-v1",
                "repository": source.repository,
                "repository_ref": source.repository_ref,
                "source_url": source.source_url,
                "size_bytes": source.size_bytes,
                "git_blob_sha1": source.git_blob_sha1,
                "license_spdx": source.license_spdx,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        btc_artifact_module,
        "urlopen",
        lambda *_args, **_kwargs: _FakeDownload(payload, source.source_url),
    )
    destination = tmp_path / "cache" / "btc.pt"
    lock_output = tmp_path / "lock.json"

    exit_code = main(
        [
            "acquire",
            "--source",
            str(source_path),
            "--destination",
            str(destination),
            "--lock-output",
            str(lock_output),
        ]
    )

    assert exit_code == 0
    assert destination.read_bytes() == payload
    assert json.loads(lock_output.read_text(encoding="utf-8"))["sha256"] == sha256(
        payload
    ).hexdigest()
