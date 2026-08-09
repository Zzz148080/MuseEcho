from __future__ import annotations

import argparse
import base64
import ctypes
import json
import os
import platform
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np

from museecho.application.access import AccessService
from museecho.application.coordinator import AnalysisCoordinator
from museecho.application.queue import SingleWorkerQueue
from museecho.application.uploads import UploadSubmissionService
from museecho.domain.status import AnalysisStage
from museecho.infrastructure.audio_store import ChunkedEncryptedAudioStore
from museecho.infrastructure.db import create_session_factory
from museecho.infrastructure.repositories import SqliteAnalysisRepository, init_db

MAX_WALL_SECONDS = 90.0
MAX_PEAK_RSS_BYTES = 4 * 1024**3
SAMPLE_RATE = 22_050
_CHORD_SECONDS = 1.25
_CHORD_FREQUENCIES = (
    (261.6256, 329.6276, 391.9954),
    (195.9977, 246.9417, 293.6648),
    (220.0, 261.6256, 329.6276),
    (174.6141, 220.0, 261.6256),
)


class _MemorySecretStore:
    source = "benchmark-memory"

    def __init__(self) -> None:
        self._value = base64.urlsafe_b64encode(b"b" * 32).decode("ascii")

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value

    def clear(self) -> bool:
        self._value = ""
        return True


def run_benchmark(*, duration_seconds: float, runtime_parent: Path) -> dict[str, Any]:
    if not 1.0 <= duration_seconds <= 600.0:
        raise ValueError("duration_seconds must be between 1 and 600")
    original_affinity = _get_cpu_affinity()
    affinity = _limit_cpu_affinity(2)
    try:
        return _run_benchmark_limited(
            duration_seconds=duration_seconds,
            runtime_parent=runtime_parent,
            affinity=affinity,
        )
    finally:
        _set_cpu_affinity(original_affinity)


def _run_benchmark_limited(
    *, duration_seconds: float, runtime_parent: Path, affinity: list[int]
) -> dict[str, Any]:
    runtime_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="museecho-benchmark-", dir=runtime_parent) as raw:
        runtime_root = Path(raw)
        source_path = runtime_root / "representative.wav"
        _write_representative_wav(source_path, duration_seconds)

        database_url = f"sqlite:///{(runtime_root / 'museecho.db').as_posix()}"
        init_db(database_url)
        session_factory = create_session_factory(database_url)
        repository = SqliteAnalysisRepository(session_factory)
        store = ChunkedEncryptedAudioStore(
            runtime_root / "ciphertext",
            key_store=_MemorySecretStore(),
            repository=repository,
            chunk_size=1024 * 1024,
        )
        stage_seconds: dict[str, float] = {}
        coordinator = AnalysisCoordinator(
            repository=repository,
            audio_store=store,
            temp_root=runtime_root / "analysis",
            stage_observer=lambda _analysis_id, stage, elapsed: stage_seconds.__setitem__(
                stage.value, round(elapsed, 6)
            ),
        )
        queue = SingleWorkerQueue(repository, coordinator)
        upload_service = UploadSubmissionService(
            repository=repository,
            audio_store=store,
            access_service=AccessService(repository),
            queue=queue,
            temp_root=runtime_root / "uploads",
        )

        wall_started = time.perf_counter()
        cpu_started = time.process_time()
        with source_path.open("rb") as source:
            submitted = upload_service.submit(
                source,
                filename="representative.wav",
                media_type="audio/wav",
            )
        upload_seconds = time.perf_counter() - wall_started
        idle = queue.wait_for_idle(timeout=MAX_WALL_SECONDS + 30.0)
        queue.stop()
        wall_seconds = time.perf_counter() - wall_started
        cpu_seconds = time.process_time() - cpu_started
        job = repository.get(submitted.job.id)
        result = repository.get_result(submitted.job.id)
        peak_rss_bytes = _peak_rss_bytes()
        persisted = (
            idle and job is not None and job.status is AnalysisStage.COMPLETE and result is not None
        )

        report: dict[str, Any] = {
            "schema_version": "museecho-performance-v1",
            "passed": bool(
                persisted
                and len(affinity) in {1, 2}
                and wall_seconds <= MAX_WALL_SECONDS
                and peak_rss_bytes <= MAX_PEAK_RSS_BYTES
            ),
            "thresholds": {
                "max_wall_seconds": MAX_WALL_SECONDS,
                "max_peak_rss_bytes": MAX_PEAK_RSS_BYTES,
                "max_cpu_affinity_count": 2,
            },
            "workload": {
                "duration_seconds": duration_seconds,
                "sample_rate": SAMPLE_RATE,
                "channels": 1,
                "format": "pcm_s16le_wav",
                "pattern": "streamed_c_g_am_f_progression",
            },
            "environment": {
                "platform": platform.platform(),
                "python": sys.version.split()[0],
                "logical_cpu_count": os.cpu_count(),
                "cpu_affinity": affinity,
                "cpu_affinity_count": len(affinity),
                "memory_limit_mode": "observed_process_peak",
            },
            "measurements": {
                "wall_seconds": round(wall_seconds, 6),
                "cpu_seconds": round(cpu_seconds, 6),
                "upload_validation_and_encryption_seconds": round(upload_seconds, 6),
                "queued_analysis_seconds": round(max(0.0, wall_seconds - upload_seconds), 6),
                "peak_rss_bytes": peak_rss_bytes,
                "stage_seconds": stage_seconds,
            },
            "result": {
                "persisted": persisted,
                "duration_seconds": None if result is None else result.duration_seconds,
                "sections": 0 if result is None else len(repository.get_sections(submitted.job.id)),
                "chords": 0 if result is None else len(repository.get_chords(submitted.job.id)),
                "evidence": len(repository.get_evidence(submitted.job.id)),
            },
        }
        session_factory.kw["bind"].dispose()
        return report


def _write_representative_wav(path: Path, duration_seconds: float) -> None:
    total_frames = int(round(duration_seconds * SAMPLE_RATE))
    chord_frames = int(round(_CHORD_SECONDS * SAMPLE_RATE))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        written = 0
        while written < total_frames:
            chord_index = (written // chord_frames) % len(_CHORD_FREQUENCIES)
            within_chord = written % chord_frames
            frame_count = min(total_frames - written, chord_frames - within_chord)
            frame = np.arange(within_chord, within_chord + frame_count, dtype=np.float64)
            seconds = frame / SAMPLE_RATE
            mixed = sum(
                np.sin(2.0 * np.pi * frequency * seconds)
                for frequency in _CHORD_FREQUENCIES[chord_index]
            ) / len(_CHORD_FREQUENCIES[chord_index])
            edge = np.minimum(frame, chord_frames - frame - 1)
            fade = np.clip(edge / (SAMPLE_RATE * 0.02), 0.0, 1.0)
            pcm = np.asarray(mixed * fade * 22_000, dtype="<i2")
            output.writeframesraw(pcm.tobytes())
            written += frame_count


def _limit_cpu_affinity(maximum: int) -> list[int]:
    if maximum <= 0:
        raise ValueError("maximum affinity must be positive")
    selected = _get_cpu_affinity()[:maximum]
    _set_cpu_affinity(selected)
    return selected


def _get_cpu_affinity() -> list[int]:
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.GetProcessAffinityMask.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_size_t),
        )
        kernel32.GetProcessAffinityMask.restype = ctypes.c_int
        process = kernel32.GetCurrentProcess()
        process_mask = ctypes.c_size_t()
        system_mask = ctypes.c_size_t()
        if not kernel32.GetProcessAffinityMask(
            process, ctypes.byref(process_mask), ctypes.byref(system_mask)
        ):
            raise OSError(ctypes.get_last_error(), "GetProcessAffinityMask failed")
        available = [
            index
            for index in range(ctypes.sizeof(ctypes.c_size_t) * 8)
            if process_mask.value >> index & 1
        ]
        return available
    getter = getattr(os, "sched_getaffinity", None)
    if getter is None:
        raise RuntimeError("CPU affinity is not supported on this platform")
    return sorted(getter(0))


def _set_cpu_affinity(selected: list[int]) -> None:
    if not selected:
        raise ValueError("CPU affinity cannot be empty")
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.SetProcessAffinityMask.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
        kernel32.SetProcessAffinityMask.restype = ctypes.c_int
        process = kernel32.GetCurrentProcess()
        target_mask = sum(1 << index for index in selected)
        if not kernel32.SetProcessAffinityMask(process, target_mask):
            raise OSError(ctypes.get_last_error(), "SetProcessAffinityMask failed")
        return
    setter = getattr(os, "sched_setaffinity", None)
    if setter is None:
        raise RuntimeError("CPU affinity is not supported on this platform")
    setter(0, selected)


def _peak_rss_bytes() -> int:
    if os.name == "nt":

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        process = kernel32.GetCurrentProcess()
        psapi.GetProcessMemoryInfo.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ProcessMemoryCounters),
            ctypes.c_ulong,
        )
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        if not psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
            raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
        return int(counters.PeakWorkingSetSize)
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the MuseEcho representative benchmark")
    parser.add_argument("--duration", type=float, default=300.0)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--runtime-parent", type=Path, default=Path("tmp/benchmark-runtime"))
    arguments = parser.parse_args()
    report = run_benchmark(
        duration_seconds=arguments.duration,
        runtime_parent=arguments.runtime_parent,
    )
    arguments.json.parent.mkdir(parents=True, exist_ok=True)
    arguments.json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
