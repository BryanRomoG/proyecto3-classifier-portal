"""T3-3.1: the 10-run experiment grid and what counts as a valid run (rubric 3.1).

The grid is a versioned YAML file (``experiments/classifier_grid.yaml``): a ``base`` config
plus one ``overrides`` block per run. ``load_grid`` refuses a grid that would not satisfy the
rubric *before* anything trains: fewer than 10 runs, repeated names, two runs with the
exact same effective config, or any of the seven searched hyperparameters taking fewer than
two distinct values.

``valid_runs`` applies the same rubric to what MLflow actually holds: finished, same
manifest and class list, weights really changed, more than one epoch, and no exact
duplicate of another valid run — neither in its searched parameters nor in its final
weights (a parameter that never took effect produces the same model, not a new result).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml
from mlflow.tracking import MlflowClient

from dataset_quality.classifier.config import SEARCHED_HYPERPARAMETERS, TrainingConfig

MIN_RUNS = 10


class GridError(ValueError):
    """The experiment grid does not meet the rubric; nothing was trained."""


@dataclass(frozen=True)
class GridRun:
    name: str
    config: TrainingConfig


@dataclass(frozen=True)
class Grid:
    experiment_name: str
    runs: list[GridRun]
    sha256: str
    path: Path


def _merge(base: dict, overrides: dict) -> dict:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def coverage(configs: list[TrainingConfig]) -> dict[str, list[object]]:
    """Distinct values each searched hyperparameter takes across the configs."""

    values: dict[str, list[object]] = {name: [] for name in SEARCHED_HYPERPARAMETERS}
    for config in configs:
        for name, value in config.searched_values().items():
            if value not in values[name]:
                values[name].append(value)
    return values


def check_grid(runs: list[GridRun]) -> list[str]:
    problems: list[str] = []
    if len(runs) < MIN_RUNS:
        problems.append(f"grid has {len(runs)} runs, the rubric requires at least {MIN_RUNS}")
    names = [run.name for run in runs]
    if len(set(names)) != len(names):
        problems.append("run names must be unique")
    effective = [json.dumps(run.config.model_dump(mode="json"), sort_keys=True) for run in runs]
    if len(set(effective)) != len(effective):
        problems.append("two runs have exactly the same effective configuration")
    for name, distinct in coverage([run.config for run in runs]).items():
        if len(distinct) < 2:
            problems.append(f"hyperparameter {name!r} takes only {distinct}; needs >= 2 values")
    return problems


def load_grid(path: Path) -> Grid:
    raw = path.read_bytes()
    document = yaml.safe_load(raw) or {}
    base = document.get("base") or {}
    runs = []
    for entry in document.get("runs") or []:
        name = entry["name"]
        try:
            config = TrainingConfig.model_validate(_merge(base, entry.get("overrides") or {}))
        except ValueError as error:
            raise GridError(f"run {name!r}: {error}") from error
        runs.append(GridRun(name=name, config=config))
    problems = check_grid(runs)
    if problems:
        raise GridError("; ".join(problems))
    return Grid(
        experiment_name=document.get("experiment_name", "t3-classifier"),
        runs=runs,
        sha256=hashlib.sha256(raw).hexdigest(),
        path=path,
    )


def _searched_signature(params: dict[str, str]) -> tuple[str, ...]:
    return tuple(params.get(name, "") for name in SEARCHED_HYPERPARAMETERS)


def valid_runs(
    client: MlflowClient, experiment_name: str, manifest_sha256: str, classes: list[str]
) -> list[dict]:
    """Rubric-valid runs of the experiment on this manifest, oldest first."""

    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        return []
    runs = client.search_runs(
        [experiment.experiment_id],
        filter_string=f"tags.manifest_sha256 = '{manifest_sha256}'",
        order_by=["attributes.start_time ASC"],
        max_results=1000,
    )
    accepted: list[dict] = []
    seen: set[tuple[str, ...]] = set()
    seen_weights: dict[str, str] = {}
    for run in runs:
        tags, metrics, params = run.data.tags, run.data.metrics, run.data.params
        reasons = []
        if run.info.status != "FINISHED":
            reasons.append(f"status {run.info.status}")
        if tags.get("classes") != json.dumps(classes):
            reasons.append("different class list")
        if tags.get("weights_changed") != "true":
            reasons.append("weights did not change")
        if metrics.get("stopped_epoch", 0) < 2:
            reasons.append("fewer than 2 epochs")
        signature = _searched_signature(params)
        final_weights = tags.get("final_state_sha256", "")
        if not reasons and signature in seen:
            reasons.append("duplicate of an earlier valid run")
        if not reasons and final_weights in seen_weights:
            # Different parameters that never took effect (e.g. a max_epochs above the
            # early-stopping point) yield bit-identical weights: same result, not a new run.
            reasons.append(f"identical final weights to run {seen_weights[final_weights]}")
        row = {
            "run_id": run.info.run_id,
            "run_name": run.info.run_name,
            "grid_run": tags.get("grid_run", ""),
            "status": run.info.status,
            "params": {name: params.get(name) for name in SEARCHED_HYPERPARAMETERS},
            "best_val_accuracy": metrics.get("best_val_accuracy"),
            "best_val_loss": metrics.get("best_val_loss"),
            "best_epoch": metrics.get("best_epoch"),
            "stopped_epoch": metrics.get("stopped_epoch"),
            "start_time": run.info.start_time,
            "end_time": run.info.end_time,
            "valid": not reasons,
            "invalid_reasons": reasons,
        }
        if not reasons:
            seen.add(signature)
            seen_weights[final_weights] = run.info.run_name
        accepted.append(row)
    return accepted
