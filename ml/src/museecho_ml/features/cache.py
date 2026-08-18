from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict
from pathlib import Path

import numpy as np

from museecho_ml.features.cqt import CqtConfig, FeatureSequence

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class FeatureCacheCorruption(ValueError):
    pass


class FeatureCache:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def compute_key(
        audio_sha256: str,
        config: CqtConfig,
        *,
        extractor_version: str = "cqt-v1",
    ) -> str:
        if not isinstance(audio_sha256, str) or _SHA256.fullmatch(audio_sha256) is None:
            raise ValueError("feature cache audio_sha256 must be lowercase hexadecimal")
        if not isinstance(extractor_version, str) or not extractor_version.strip():
            raise ValueError("feature cache extractor_version must be non-empty")
        payload = json.dumps(
            {
                "audio_sha256": audio_sha256,
                "config": asdict(config),
                "extractor_version": extractor_version,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def path_for(self, key: str) -> Path:
        if not isinstance(key, str) or _SHA256.fullmatch(key) is None:
            raise ValueError("feature cache key must be lowercase SHA-256")
        return self.root / key[:2] / f"{key}.npz"

    def load(self, key: str) -> FeatureSequence | None:
        path = self.path_for(key)
        if not path.exists():
            return None
        try:
            with np.load(path, allow_pickle=False) as payload:
                if set(payload.files) != {
                    "key",
                    "main_cqt",
                    "bass_cqt",
                    "frame_times",
                    "valid_mask",
                }:
                    raise FeatureCacheCorruption("feature cache entry is corrupt")
                stored_key = str(payload["key"].item())
                features = FeatureSequence(
                    main_cqt=np.array(payload["main_cqt"], copy=True),
                    bass_cqt=np.array(payload["bass_cqt"], copy=True),
                    frame_times=np.array(payload["frame_times"], copy=True),
                    valid_mask=np.array(payload["valid_mask"], copy=True),
                )
        except FeatureCacheCorruption:
            raise
        except (EOFError, OSError, TypeError, ValueError) as error:
            raise FeatureCacheCorruption("feature cache entry is corrupt") from error
        if stored_key != key or not _valid_features(features):
            raise FeatureCacheCorruption("feature cache entry is corrupt")
        return features

    def store(self, key: str, features: FeatureSequence) -> Path:
        if not _valid_features(features):
            raise ValueError("feature cache sequence is invalid")
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w+b",
                dir=path.parent,
                prefix=f".{key}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                np.savez_compressed(
                    temporary,
                    key=np.asarray(key),
                    main_cqt=features.main_cqt,
                    bass_cqt=features.bass_cqt,
                    frame_times=features.frame_times,
                    valid_mask=features.valid_mask,
                )
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
        return path


def _valid_features(features: FeatureSequence) -> bool:
    main = features.main_cqt
    bass = features.bass_cqt
    times = features.frame_times
    mask = features.valid_mask
    return (
        isinstance(main, np.ndarray)
        and isinstance(bass, np.ndarray)
        and isinstance(times, np.ndarray)
        and isinstance(mask, np.ndarray)
        and main.dtype == np.float32
        and bass.dtype == np.float32
        and times.dtype == np.float64
        and mask.dtype == np.bool_
        and main.ndim == 2
        and bass.ndim == 2
        and times.ndim == 1
        and mask.ndim == 1
        and main.shape[1] == bass.shape[1] == len(times) == len(mask)
        and bass.shape[0] <= main.shape[0]
        and main.size > 0
        and bass.size > 0
        and np.isfinite(main).all()
        and np.isfinite(bass).all()
        and np.isfinite(times).all()
    )
