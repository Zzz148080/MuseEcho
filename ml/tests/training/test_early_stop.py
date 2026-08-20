from __future__ import annotations

import pytest

from museecho_ml.training.early_stop import EarlyStopConfig, EarlyStopper


def test_early_stopper_selects_only_improved_validation_metric() -> None:
    stopper = EarlyStopper(EarlyStopConfig(patience=2, minimum_delta=0.01))

    assert stopper.update(0.50, epoch=0) is True
    assert stopper.update(0.505, epoch=1) is False
    assert stopper.should_stop is False
    assert stopper.update(0.49, epoch=2) is False

    assert stopper.should_stop is True
    assert stopper.best_metric == 0.50
    assert stopper.best_epoch == 0


def test_early_stopper_state_round_trips_exactly() -> None:
    original = EarlyStopper(EarlyStopConfig(patience=3, mode="min"))
    original.update(2.0, epoch=0)
    original.update(2.1, epoch=1)

    restored = EarlyStopper(EarlyStopConfig(patience=3, mode="min"))
    restored.load_state_dict(original.state_dict())

    assert restored.state_dict() == original.state_dict()
    assert restored.update(1.5, epoch=2) is True
    assert restored.best_metric == 1.5


def test_early_stopper_rejects_nonfinite_validation_metric() -> None:
    stopper = EarlyStopper(EarlyStopConfig())

    with pytest.raises(ValueError, match="finite"):
        stopper.update(float("nan"), epoch=0)
