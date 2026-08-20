from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EarlyStopConfig:
    mode: str = "max"
    patience: int = 5
    minimum_delta: float = 0.0

    def __post_init__(self) -> None:
        if self.mode not in {"max", "min"}:
            raise ValueError("early-stop mode must be max or min")
        if type(self.patience) is not int or self.patience <= 0:
            raise ValueError("early-stop patience must be a positive integer")
        if (
            isinstance(self.minimum_delta, bool)
            or not isinstance(self.minimum_delta, (int, float))
            or not math.isfinite(self.minimum_delta)
            or self.minimum_delta < 0
        ):
            raise ValueError("early-stop minimum_delta must be finite and non-negative")


class EarlyStopper:
    def __init__(self, config: EarlyStopConfig) -> None:
        self.config = config
        self._best_metric: float | None = None
        self._best_epoch: int | None = None
        self._bad_epochs = 0
        self._should_stop = False

    @property
    def should_stop(self) -> bool:
        return self._should_stop

    @property
    def best_metric(self) -> float | None:
        return self._best_metric

    @property
    def best_epoch(self) -> int | None:
        return self._best_epoch

    def update(self, metric: float, *, epoch: int) -> bool:
        if (
            isinstance(metric, bool)
            or not isinstance(metric, (int, float))
            or not math.isfinite(metric)
        ):
            raise ValueError("early-stop validation metric must be finite")
        if type(epoch) is not int or epoch < 0:
            raise ValueError("early-stop epoch must be a non-negative integer")
        improved = self._best_metric is None or self._is_improvement(float(metric))
        if improved:
            self._best_metric = float(metric)
            self._best_epoch = epoch
            self._bad_epochs = 0
            self._should_stop = False
        else:
            self._bad_epochs += 1
            self._should_stop = self._bad_epochs >= self.config.patience
        return improved

    def state_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "best_metric": self._best_metric,
            "best_epoch": self._best_epoch,
            "bad_epochs": self._bad_epochs,
            "should_stop": self._should_stop,
        }

    def load_state_dict(self, value: dict[str, Any]) -> None:
        required = {
            "schema_version",
            "best_metric",
            "best_epoch",
            "bad_epochs",
            "should_stop",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("early-stop state fields are invalid")
        best_metric = value["best_metric"]
        best_epoch = value["best_epoch"]
        bad_epochs = value["bad_epochs"]
        should_stop = value["should_stop"]
        if value["schema_version"] != 1:
            raise ValueError("early-stop state version is unsupported")
        if best_metric is not None and (
            isinstance(best_metric, bool)
            or not isinstance(best_metric, (int, float))
            or not math.isfinite(best_metric)
        ):
            raise ValueError("early-stop best metric must be finite or null")
        if (best_epoch is None) != (best_metric is None) or (
            best_epoch is not None and (type(best_epoch) is not int or best_epoch < 0)
        ):
            raise ValueError("early-stop best epoch is invalid")
        if type(bad_epochs) is not int or bad_epochs < 0:
            raise ValueError("early-stop bad epoch count is invalid")
        if type(should_stop) is not bool or should_stop != (
            bad_epochs >= self.config.patience
        ):
            raise ValueError("early-stop stopped state is inconsistent")
        self._best_metric = None if best_metric is None else float(best_metric)
        self._best_epoch = best_epoch
        self._bad_epochs = bad_epochs
        self._should_stop = should_stop

    def _is_improvement(self, metric: float) -> bool:
        assert self._best_metric is not None
        if self.config.mode == "max":
            return metric > self._best_metric + self.config.minimum_delta
        return metric < self._best_metric - self.config.minimum_delta
