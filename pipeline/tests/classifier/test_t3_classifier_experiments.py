"""T3-3.1: the committed 10-run grid satisfies the rubric; bad grids are refused."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dataset_quality.classifier.config import SEARCHED_HYPERPARAMETERS
from dataset_quality.classifier.experiments import GridError, coverage, load_grid
from dataset_quality.classifier.selection import SelectionError, SelectionPolicy

PIPELINE_ROOT = Path(__file__).resolve().parents[2]
GRID = PIPELINE_ROOT / "experiments" / "classifier_grid.yaml"
POLICY = PIPELINE_ROOT / "experiments" / "selection_policy.yaml"


def test_committed_grid_has_ten_runs_and_varies_all_seven_hyperparameters() -> None:
    grid = load_grid(GRID)

    assert len(grid.runs) >= 10
    values = coverage([run.config for run in grid.runs])
    assert set(values) == set(SEARCHED_HYPERPARAMETERS)
    for name, distinct in values.items():
        assert len(distinct) >= 2, name


def test_committed_grid_shares_everything_but_the_searched_hyperparameters() -> None:
    grid = load_grid(GRID)
    fixed = [run.config.model_dump(exclude=set(SEARCHED_HYPERPARAMETERS)) for run in grid.runs]

    assert all(entry == fixed[0] for entry in fixed)


def _write_grid(tmp_path: Path, runs: list[dict]) -> Path:
    path = tmp_path / "grid.yaml"
    base = yaml.safe_load(GRID.read_text(encoding="utf-8"))["base"]
    path.write_text(yaml.safe_dump({"base": base, "runs": runs}), encoding="utf-8")
    return path


def test_grid_with_a_constant_hyperparameter_is_refused(tmp_path) -> None:
    runs = [{"name": f"r{i}", "overrides": {"learning_rate": 0.001 * (i + 1)}} for i in range(10)]

    with pytest.raises(GridError, match="optimizer"):
        load_grid(_write_grid(tmp_path, runs))


def test_grid_with_duplicate_runs_or_too_few_runs_is_refused(tmp_path) -> None:
    runs = yaml.safe_load(GRID.read_text(encoding="utf-8"))["runs"]

    with pytest.raises(GridError, match="same effective configuration"):
        load_grid(_write_grid(tmp_path, [*runs, {"name": "copy", "overrides": {}}]))
    with pytest.raises(GridError, match="at least 10"):
        load_grid(_write_grid(tmp_path, runs[:9]))


def test_committed_policy_uses_a_validation_metric() -> None:
    policy = SelectionPolicy.load(POLICY)

    assert policy.metric == "best_val_accuracy" and policy.mode == "max"
    assert policy.min_valid_runs >= 10


def test_a_policy_on_a_test_metric_is_refused(tmp_path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text("metric: test_accuracy\nmode: max\n", encoding="utf-8")

    with pytest.raises(SelectionError, match="validation"):
        SelectionPolicy.load(path)
