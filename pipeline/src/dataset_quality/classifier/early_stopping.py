"""T3-2.2: early stopping and best-checkpoint restoration (rubric 2.4).

``EarlyStopping`` is pure bookkeeping over a monitored validation metric; ``fit`` drives the
epoch loop around two callables (train one epoch, validate) so the stopping and restore
logic can be tested with a scripted metric sequence, independently of real training.

Rule: an epoch *improves* when the metric beats the best so far by more than
``min_delta`` (lower for ``val_loss``, higher for ``val_accuracy``). Training stops after
``patience`` consecutive epochs without improvement, and the model is always left holding
the weights of the best epoch — never the last one.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field

from torch import nn

from dataset_quality.classifier.config import MonitoredMetric

EpochMetrics = dict[str, float]


class EarlyStopping:
    def __init__(self, monitor: MonitoredMetric, patience: int, min_delta: float) -> None:
        self.monitor = monitor
        self.patience = patience
        self.min_delta = min_delta
        self.mode = "min" if monitor == "val_loss" else "max"
        self.best_value: float | None = None
        self.best_epoch: int | None = None
        self.epochs_without_improvement = 0

    def improves(self, value: float) -> bool:
        if self.best_value is None:
            return True
        if self.mode == "min":
            return value < self.best_value - self.min_delta
        return value > self.best_value + self.min_delta

    def update(self, value: float, epoch: int) -> bool:
        """Record one epoch; return whether it is the new best."""

        if self.improves(value):
            self.best_value = value
            self.best_epoch = epoch
            self.epochs_without_improvement = 0
            return True
        self.epochs_without_improvement += 1
        return False

    @property
    def should_stop(self) -> bool:
        return self.epochs_without_improvement >= self.patience


@dataclass
class FitResult:
    history: list[EpochMetrics] = field(default_factory=list)
    best_epoch: int = 0
    best_value: float = 0.0
    stopped_epoch: int = 0
    stopped_early: bool = False
    monitor: str = "val_loss"


def fit(
    model: nn.Module,
    *,
    max_epochs: int,
    stopper: EarlyStopping,
    train_epoch: Callable[[int], EpochMetrics],
    validate: Callable[[int], EpochMetrics],
    on_epoch_end: Callable[[int, EpochMetrics, bool], None] | None = None,
) -> FitResult:
    """Run up to ``max_epochs`` epochs, stop early, and restore the best epoch's weights."""

    result = FitResult(monitor=stopper.monitor)
    best_state = copy.deepcopy(model.state_dict())
    for epoch in range(1, max_epochs + 1):
        metrics = {"epoch": float(epoch), **train_epoch(epoch), **validate(epoch)}
        if stopper.monitor not in metrics:
            raise KeyError(f"validate() must return {stopper.monitor!r}")
        improved = stopper.update(metrics[stopper.monitor], epoch)
        if improved:
            best_state = copy.deepcopy(model.state_dict())
        result.history.append(metrics)
        result.stopped_epoch = epoch
        if on_epoch_end is not None:
            on_epoch_end(epoch, metrics, improved)
        if stopper.should_stop:
            result.stopped_early = epoch < max_epochs
            break

    model.load_state_dict(best_state)
    assert stopper.best_epoch is not None and stopper.best_value is not None
    result.best_epoch = stopper.best_epoch
    result.best_value = stopper.best_value
    return result
