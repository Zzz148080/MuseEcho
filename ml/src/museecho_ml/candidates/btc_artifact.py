from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from museecho_ml.artifacts import write_immutable_json

_APPROVED_CHECKPOINT_HOST = "raw.githubusercontent.com"
_SOURCE_FIELDS = frozenset(
    {
        "schema_version",
        "candidate_version",
        "repository",
        "repository_ref",
        "source_url",
        "size_bytes",
        "git_blob_sha1",
        "license_spdx",
    }
)
_CANDIDATE_VERSION = "btc-ismir19-large-voca-v1"


@dataclass(frozen=True)
class BtcArtifactSource:
    repository: str
    repository_ref: str
    source_url: str
    size_bytes: int
    git_blob_sha1: str
    license_spdx: str

    def __post_init__(self) -> None:
        parsed = urlparse(self.source_url)
        if parsed.scheme != "https" or parsed.hostname != _APPROVED_CHECKPOINT_HOST:
            raise ValueError("BTC source must use the approved GitHub raw host")
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes <= 0
        ):
            raise ValueError("BTC source size must be a positive integer")
        if len(self.git_blob_sha1) != 40 or any(
            character not in "0123456789abcdef" for character in self.git_blob_sha1
        ):
            raise ValueError("BTC source Git blob SHA-1 is invalid")


@dataclass(frozen=True)
class BtcArtifactLock:
    repository: str
    repository_ref: str
    source_url: str
    size_bytes: int
    git_blob_sha1: str
    sha256: str
    license_spdx: str


def git_blob_sha1(payload: bytes) -> str:
    header = b"blob " + str(len(payload)).encode("ascii") + b"\0"
    return hashlib.sha1(header + payload).hexdigest()


def load_btc_source(path: Path) -> BtcArtifactSource:
    try:
        value: Any = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("BTC source descriptor is unreadable") from error
    if not isinstance(value, dict) or set(value) != _SOURCE_FIELDS:
        raise ValueError("BTC source descriptor fields do not match the approved schema")
    if value["schema_version"] != 1:
        raise ValueError("BTC source descriptor schema version is unsupported")
    if value["candidate_version"] != _CANDIDATE_VERSION:
        raise ValueError("BTC source descriptor candidate version is unsupported")
    try:
        return BtcArtifactSource(
            repository=value["repository"],
            repository_ref=value["repository_ref"],
            source_url=value["source_url"],
            size_bytes=value["size_bytes"],
            git_blob_sha1=value["git_blob_sha1"],
            license_spdx=value["license_spdx"],
        )
    except (TypeError, ValueError) as error:
        raise ValueError("BTC source descriptor values are invalid") from error


def verify_btc_artifact(path: Path, source: BtcArtifactSource) -> BtcArtifactLock:
    payload = path.resolve(strict=True).read_bytes()
    if len(payload) != source.size_bytes:
        raise ValueError("BTC checkpoint size does not match approved source")
    if git_blob_sha1(payload) != source.git_blob_sha1:
        raise ValueError("BTC checkpoint Git blob identity does not match")
    return BtcArtifactLock(
        repository=source.repository,
        repository_ref=source.repository_ref,
        source_url=source.source_url,
        size_bytes=len(payload),
        git_blob_sha1=source.git_blob_sha1,
        sha256=hashlib.sha256(payload).hexdigest(),
        license_spdx=source.license_spdx,
    )


def acquire_btc_artifact(
    source: BtcArtifactSource,
    destination: Path,
    lock_output: Path,
) -> BtcArtifactLock:
    target = destination.resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".btc-checkpoint.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        request = Request(source.source_url, headers={"User-Agent": "MuseEcho-BTC-audit/1"})
        with urlopen(request, timeout=60) as response:  # noqa: S310
            final_url = response.geturl()
            if urlparse(final_url).hostname != _APPROVED_CHECKPOINT_HOST:
                raise ValueError("BTC checkpoint redirected outside the approved host")
            with os.fdopen(descriptor, "wb") as output:
                descriptor = -1
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
        lock = verify_btc_artifact(temporary, source)
        os.replace(temporary, target)
        write_immutable_json(lock_output, asdict(lock))
        return lock
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acquire the approved BTC checkpoint")
    subparsers = parser.add_subparsers(dest="command", required=True)
    acquire_parser = subparsers.add_parser("acquire")
    acquire_parser.add_argument("--source", type=Path, required=True)
    acquire_parser.add_argument("--destination", type=Path, required=True)
    acquire_parser.add_argument("--lock-output", type=Path, required=True)
    arguments = parser.parse_args(argv)

    if arguments.command == "acquire":
        source = load_btc_source(arguments.source)
        lock = acquire_btc_artifact(
            source,
            arguments.destination,
            arguments.lock_output,
        )
        print(json.dumps(asdict(lock), ensure_ascii=False, sort_keys=True))
        return 0
    raise AssertionError("unreachable BTC artifact command")


if __name__ == "__main__":
    raise SystemExit(main())
