from __future__ import annotations

import json
import math
import wave
from pathlib import Path

import pytest

from museecho_ml.data.fingerprint import (
    find_near_duplicates,
    fingerprint_wav,
    near_duplicate_score,
)
from museecho_ml.data.split import SplitAuditRequired, SplitPolicy, build_split

ML_ROOT = Path(__file__).resolve().parents[2]


def _track(
    track_id: str,
    cover_group_id: str,
    artist_id: str,
    audio_sha256: str | None = None,
    work_id: str | None = None,
) -> dict[str, str]:
    return {
        "track_id": track_id,
        "work_id": work_id or cover_group_id,
        "cover_group_id": cover_group_id,
        "artist_id": artist_id,
        "audio_sha256": audio_sha256 or f"sha-{track_id}",
    }


def _manifest(tracks: list[dict[str, str]]) -> dict[str, object]:
    return {"schema_version": 1, "dataset_id": "fixture", "tracks": tracks}


def _write_tone(
    path: Path,
    *,
    frequency_hz: float,
    duration_seconds: float,
    sample_rate: int = 8000,
    start_seconds: float = 0.0,
) -> None:
    frames = bytearray()
    for index in range(round(duration_seconds * sample_rate)):
        time_seconds = start_seconds + index / sample_rate
        sample = round(12000 * math.sin(2 * math.pi * frequency_hz * time_seconds))
        frames.extend(int(sample).to_bytes(2, "little", signed=True))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(bytes(frames))


def test_split_is_deterministic_and_keeps_cover_groups_together() -> None:
    tracks = [
        _track("cover-a-1", "cover-a", "artist-a"),
        _track("cover-a-2", "cover-a", "artist-b"),
    ] + [
        _track(f"track-{index}", f"cover-{index}", f"artist-{index}")
        for index in range(1, 8)
    ]
    policy = SplitPolicy(train=0.5, calibration=0.125, validation=0.125, test=0.25)

    first = build_split(_manifest(tracks), policy, seed=20260818)
    second = build_split(_manifest(list(reversed(tracks))), policy, seed=20260818)

    assert first == second
    assert first["assignments"]["cover-a-1"] == first["assignments"]["cover-a-2"]
    assert set(first["assignments"]) == {track["track_id"] for track in tracks}
    assert len(first["split_sha256"]) == 64
    assert len(first["policy_sha256"]) == 64


def test_split_requires_audit_for_exact_audio_collision_across_cover_groups() -> None:
    manifest = _manifest(
        [
            _track("track-a", "cover-a", "artist-a", "same-audio-hash"),
            _track("track-b", "cover-b", "artist-b", "same-audio-hash"),
        ]
    )

    with pytest.raises(SplitAuditRequired, match="audio hash"):
        build_split(manifest, SplitPolicy(), seed=7)


def test_artist_disjoint_policy_keeps_artist_in_one_split() -> None:
    tracks = [
        _track("artist-a-song-1", "cover-a", "artist-a"),
        _track("artist-a-song-2", "cover-b", "artist-a"),
    ] + [
        _track(f"track-{index}", f"cover-{index}", f"artist-{index}")
        for index in range(1, 8)
    ]

    result = build_split(
        _manifest(tracks), SplitPolicy(artist_disjoint=True), seed=20260818
    )

    assert result["assignments"]["artist-a-song-1"] == result["assignments"][
        "artist-a-song-2"
    ]


def test_split_keeps_same_work_together_even_if_cover_metadata_differs() -> None:
    tracks = [
        _track("work-a-version-1", "cover-a", "artist-a", work_id="work-a"),
        _track("work-a-version-2", "cover-b", "artist-b", work_id="work-a"),
    ] + [
        _track(f"track-{index}", f"cover-{index}", f"artist-{index}")
        for index in range(1, 8)
    ]

    result = build_split(_manifest(tracks), SplitPolicy(), seed=20260818)

    assert result["group_count"] == 8
    assert result["assignments"]["work-a-version-1"] == result["assignments"][
        "work-a-version-2"
    ]


def test_pcm_fingerprint_detects_aligned_clip_but_not_different_tone(
    tmp_path: Path,
) -> None:
    _write_tone(tmp_path / "full.wav", frequency_hz=233.0, duration_seconds=6.0)
    _write_tone(
        tmp_path / "clip.wav",
        frequency_hz=233.0,
        duration_seconds=3.0,
        start_seconds=2.0,
    )
    _write_tone(tmp_path / "other.wav", frequency_hz=367.0, duration_seconds=3.0)

    full = fingerprint_wav(tmp_path / "full.wav")
    clip = fingerprint_wav(tmp_path / "clip.wav")
    other = fingerprint_wav(tmp_path / "other.wav")

    assert near_duplicate_score(full, clip) >= 0.8
    assert near_duplicate_score(full, other) < 0.2
    assert [
        (candidate.left_track_id, candidate.right_track_id)
        for candidate in find_near_duplicates(
            {"full": full, "clip": clip, "other": other}, threshold=0.8
        )
    ] == [("clip", "full")]


def test_split_config_matches_versioned_policy() -> None:
    payload = json.loads(
        (ML_ROOT / "configs" / "split-v1.json").read_text(encoding="utf-8")
    )

    assert payload == {
        "schema_version": 1,
        "policy_version": "1.0.0",
        "ratios": {
            "train": 0.7,
            "calibration": 0.1,
            "validation": 0.1,
            "test": 0.1,
        },
        "artist_disjoint": False,
        "near_duplicate_threshold": 0.8,
        "seed": 20260818,
    }
