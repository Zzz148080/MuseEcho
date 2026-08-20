from __future__ import annotations

import os
import platform
import random
import subprocess
import sys
from typing import Any

import numpy as np
import torch

_PRECISION_MODES = {"float32", "amp-float16", "amp-bfloat16"}


def resolve_device(requested: str) -> torch.device:
    if requested not in {"auto", "cpu", "cuda"}:
        raise ValueError("training device must be auto, cpu, or cuda")
    if requested == "auto":
        requested = "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    return torch.device(requested)


def configure_reproducibility(seed: int, device: torch.device) -> None:
    if type(seed) is not int or seed < 0:
        raise ValueError("reproducibility seed must be a non-negative integer")
    if device.type not in {"cpu", "cuda"}:
        raise ValueError("reproducibility device must be CPU or CUDA")
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA reproducibility requires an available CUDA device")
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if device.type == "cuda":
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True


def collect_device_metadata(
    device: torch.device, *, precision_mode: str
) -> dict[str, Any]:
    if precision_mode not in _PRECISION_MODES:
        raise ValueError("training precision mode is unsupported")
    if device.type == "cpu" and precision_mode != "float32":
        raise ValueError("CPU training requires float32 precision")
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA metadata requires an available CUDA device")
    if device.type not in {"cpu", "cuda"}:
        raise ValueError("training metadata device must be CPU or CUDA")
    index = torch.cuda.current_device() if device.type == "cuda" else None
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "torch_version": str(torch.__version__),
        "device_type": device.type,
        "device_index": index,
        "device_name": (
            torch.cuda.get_device_name(index) if index is not None else platform.processor()
        ),
        "precision_mode": precision_mode,
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        "cuda_available": torch.cuda.is_available(),
        "cuda_runtime_version": torch.version.cuda,
        "cuda_driver_version": _cuda_driver_version() if index is not None else None,
        "cudnn_version": torch.backends.cudnn.version(),
    }


def _cuda_driver_version() -> str | None:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=driver_version",
                "--format=csv,noheader",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    versions = sorted({line.strip() for line in completed.stdout.splitlines() if line.strip()})
    return ",".join(versions) if versions else None
