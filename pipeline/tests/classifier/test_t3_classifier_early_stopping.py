"""T3-2.2: early stopping on a scripted metric sequence restores the best epoch (rubric 2.4).

The "model" is a single parameter that ``train_epoch`` overwrites with the epoch number, so
after ``fit`` its value says exactly which epoch's weights were restored.
"""

from __future__ import annotations

import pytest
import torch
from torch import nn

from dataset_quality.classifier.early_stopping import EarlyStopping, fit


class EpochStamp(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.weight = nn.Parameter(torch.zeros(1))


def _run(sequence, *, monitor="val_loss", patience=3, min_delta=0.0, max_epochs=None):
    model = EpochStamp()

    def train_epoch(epoch: int) -> dict[str, float]:
        with torch.no_grad():
            model.weight.fill_(float(epoch))
        return {"train_loss": 0.0, "train_accuracy": 0.0}

    def validate(epoch: int) -> dict[str, float]:
        other = "val_accuracy" if monitor == "val_loss" else "val_loss"
        return {monitor: sequence[epoch - 1], other: 0.0}

    result = fit(
        model,
        max_epochs=max_epochs or len(sequence),
        stopper=EarlyStopping(monitor, patience, min_delta),
        train_epoch=train_epoch,
        validate=validate,
    )
    return model, result


def test_stops_after_patience_and_restores_best_not_last() -> None:
    model, result = _run([1.0, 0.8, 0.7, 0.75, 0.74, 0.9, 0.95, 0.5], patience=3)

    assert result.best_epoch == 3
    assert result.stopped_epoch == 6
    assert result.stopped_early is True
    assert model.weight.item() == 3.0, "weights must come from the best epoch, not epoch 6"
    assert len(result.history) == 6


def test_improvements_smaller_than_min_delta_do_not_count() -> None:
    model, result = _run([1.0, 0.995, 0.99, 0.985, 0.98], patience=2, min_delta=0.01)

    assert result.best_epoch == 1
    assert result.stopped_epoch == 3
    assert model.weight.item() == 1.0


def test_accuracy_is_maximised() -> None:
    model, result = _run([0.5, 0.7, 0.9, 0.85, 0.88], monitor="val_accuracy", patience=2)

    assert result.best_epoch == 3
    assert model.weight.item() == 3.0


def test_runs_to_max_epochs_when_always_improving() -> None:
    model, result = _run([0.9, 0.8, 0.7, 0.6], patience=2)

    assert result.stopped_early is False
    assert result.best_epoch == result.stopped_epoch == 4
    assert model.weight.item() == 4.0


def test_validate_must_return_the_monitored_metric() -> None:
    model = EpochStamp()
    with pytest.raises(KeyError):
        fit(
            model,
            max_epochs=2,
            stopper=EarlyStopping("val_loss", 2, 0.0),
            train_epoch=lambda e: {},
            validate=lambda e: {"val_accuracy": 1.0},
        )
