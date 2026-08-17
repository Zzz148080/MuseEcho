from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ML_ROOT = REPOSITORY_ROOT / "ml"


def test_ml_project_has_an_independent_locked_package() -> None:
    pyproject = ML_ROOT / "pyproject.toml"
    lockfile = ML_ROOT / "uv.lock"

    assert pyproject.is_file()
    assert lockfile.is_file()

    metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert metadata["project"]["name"] == "museecho-ml"
    assert metadata["project"]["requires-python"] == ">=3.12,<3.13"
    assert metadata["tool"]["uv"]["required-version"] == "==0.11.29"


def test_chord_model_manifest_schema_has_required_identity_fields() -> None:
    schema_path = REPOSITORY_ROOT / "models" / "chords" / "manifest.schema.json"

    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "schema_version",
        "model_version",
        "algorithm",
        "model_sha256",
        "feature_config_sha256",
        "vocabulary_sha256",
        "calibration_sha256",
        "input",
        "outputs",
        "runtime",
        "license",
    }


def test_training_artifacts_are_ignored() -> None:
    ignore = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert {
        "ml/data/",
        "ml/cache/",
        "ml/runs/",
        "ml/checkpoints/",
        "*.pt",
        "*.pth",
        "*.ckpt",
        "*.onnx",
    }.issubset(ignore)


def test_product_runtime_does_not_import_training_framework() -> None:
    forbidden = ("import torch", "from torch", "import museecho_ml", "from museecho_ml")
    violations: list[str] = []
    for source in (REPOSITORY_ROOT / "src" / "museecho").rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        if any(marker in text for marker in forbidden):
            violations.append(str(source.relative_to(REPOSITORY_ROOT)))

    assert violations == []


def test_no_large_training_artifacts_are_tracked() -> None:
    completed = subprocess.run(
        ["git", "ls-files", "ml", "models/chords"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    forbidden_suffixes = {".pt", ".pth", ".ckpt", ".onnx", ".wav", ".mp3", ".flac"}
    tracked = [Path(line) for line in completed.stdout.splitlines() if line]

    assert [str(path) for path in tracked if path.suffix.lower() in forbidden_suffixes] == []
