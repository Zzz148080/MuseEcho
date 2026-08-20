from __future__ import annotations

import pytest
import torch

from museecho_ml.training.seed import (
    collect_device_metadata,
    configure_reproducibility,
    resolve_device,
)


def test_cpu_reproducibility_and_metadata_are_explicit() -> None:
    device = resolve_device("cpu")
    configure_reproducibility(20260820, device)

    metadata = collect_device_metadata(device, precision_mode="float32")

    assert device == torch.device("cpu")
    assert torch.are_deterministic_algorithms_enabled()
    assert metadata["device_type"] == "cpu"
    assert metadata["precision_mode"] == "float32"
    assert metadata["cuda_available"] is torch.cuda.is_available()
    assert metadata["cuda_runtime_version"] == torch.version.cuda
    assert metadata["cuda_driver_version"] is None
    assert isinstance(metadata["python_version"], str)
    assert isinstance(metadata["torch_version"], str)


def test_auto_device_matches_runtime_and_explicit_cuda_fails_closed() -> None:
    automatic = resolve_device("auto")
    expected = "cuda" if torch.cuda.is_available() else "cpu"
    assert automatic.type == expected

    if not torch.cuda.is_available():
        with pytest.raises(RuntimeError, match="CUDA"):
            resolve_device("cuda")


def test_cpu_rejects_mixed_precision_metadata() -> None:
    with pytest.raises(ValueError, match="CPU"):
        collect_device_metadata(torch.device("cpu"), precision_mode="amp-float16")
