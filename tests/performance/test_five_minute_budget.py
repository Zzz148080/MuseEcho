from pathlib import Path

from scripts.benchmark import _get_cpu_affinity, run_benchmark


def test_five_minute_pipeline_meets_runtime_and_memory_budget(tmp_path: Path) -> None:
    original_affinity = _get_cpu_affinity()
    report = run_benchmark(duration_seconds=300.0, runtime_parent=tmp_path)

    assert report["passed"], report
    assert report["workload"]["duration_seconds"] == 300.0
    assert report["environment"]["cpu_affinity_count"] <= 2
    assert report["measurements"]["wall_seconds"] <= 90.0
    assert report["measurements"]["peak_rss_bytes"] <= 4 * 1024**3
    assert report["result"]["persisted"] is True
    assert _get_cpu_affinity() == original_affinity
