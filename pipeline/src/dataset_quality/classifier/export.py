"""Versioned snapshot of the MLflow runs, so a clean clone can audit them (rubric 3.1/3.2).

The tracking store (``pipeline/mlflow-data/``) is git-ignored: on a fresh clone the MLflow
server starts empty. ``export_runs`` reads every run of the given experiments through the
MLflow API and writes what an auditor needs into ``reports/classifier/``:

* ``mlflow_runs.json`` — per run: ID, name, status, times, every effective parameter, the
  lineage/reproducibility tags (commit, DVC md5, manifest hash, classes, seeds, weight
  hashes), final metrics, the per-epoch history of train/val loss and accuracy, the
  artifact list, and whether it counts as one of the rubric-valid runs (with the reason
  when it does not);
* ``curves/<run name>-<run id prefix>.png`` — each run's logged train/val curves.

It is a copy for auditing, not a second source of truth: every number comes from MLflow,
and ``run_id`` points back to the run it was read from.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import mlflow
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from dataset_quality.classifier.experiments import valid_runs

EXPORT_REPORT = "mlflow_runs.json"
CURVES_DIR = "curves"
CURVES_ARTIFACT = "curves.png"
EPOCH_METRICS = ("train_loss", "train_accuracy", "val_loss", "val_accuracy")


def _iso(timestamp_ms: int | None) -> str | None:
    if timestamp_ms is None:
        return None
    return datetime.fromtimestamp(timestamp_ms / 1000, UTC).isoformat()


def _history(client: MlflowClient, run_id: str) -> list[dict[str, float]]:
    by_epoch: dict[int, dict[str, float]] = {}
    for key in EPOCH_METRICS:
        for point in client.get_metric_history(run_id, key):
            by_epoch.setdefault(point.step, {"epoch": point.step})[key] = point.value
    return [by_epoch[epoch] for epoch in sorted(by_epoch)]


def _download_curves(run_id: str, run_name: str, target_dir: Path) -> str | None:
    staging = target_dir / run_id
    try:
        local = Path(
            mlflow.artifacts.download_artifacts(
                run_id=run_id, artifact_path=CURVES_ARTIFACT, dst_path=str(staging)
            )
        )
    except (MlflowException, OSError):
        shutil.rmtree(staging, ignore_errors=True)
        return None
    destination = target_dir / f"{run_name}-{run_id[:8]}.png"
    local.replace(destination)
    local.parent.rmdir()
    return f"{CURVES_DIR}/{destination.name}"


def export_runs(
    *,
    experiments: list[str],
    manifest_sha256: str,
    classes: list[str],
    report_dir: Path,
) -> dict:
    client = MlflowClient()
    curves_dir = report_dir / CURVES_DIR
    curves_dir.mkdir(parents=True, exist_ok=True)

    exported = []
    for name in experiments:
        experiment = client.get_experiment_by_name(name)
        if experiment is None:
            raise ValueError(f"MLflow experiment {name!r} does not exist")
        validity = {
            row["run_id"]: row for row in valid_runs(client, name, manifest_sha256, classes)
        }
        runs = client.search_runs(
            [experiment.experiment_id],
            order_by=["attributes.start_time ASC"],
            max_results=1000,
        )
        rows = []
        for run in runs:
            run_id = run.info.run_id
            checked = validity.get(run_id)
            rows.append(
                {
                    "run_id": run_id,
                    "run_name": run.info.run_name,
                    "status": run.info.status,
                    "start_time": _iso(run.info.start_time),
                    "end_time": _iso(run.info.end_time),
                    "valid": bool(checked and checked["valid"]),
                    "invalid_reasons": (
                        checked["invalid_reasons"] if checked else ["different manifest"]
                    ),
                    "params": dict(sorted(run.data.params.items())),
                    "tags": {
                        key: value
                        for key, value in sorted(run.data.tags.items())
                        if not key.startswith("mlflow.")
                    },
                    "metrics": dict(sorted(run.data.metrics.items())),
                    "history": _history(client, run_id),
                    "artifacts": sorted(a.path for a in client.list_artifacts(run_id)),
                    "curves": _download_curves(run_id, run.info.run_name, curves_dir),
                }
            )
        exported.append(
            {
                "name": name,
                "experiment_id": experiment.experiment_id,
                "runs": len(rows),
                "valid_runs": sum(row["valid"] for row in rows),
                "run_list": rows,
            }
        )

    snapshot = {
        "exported_at": datetime.now(UTC).isoformat(),
        "manifest_sha256": manifest_sha256,
        "classes": classes,
        "experiments": exported,
    }
    (report_dir / EXPORT_REPORT).write_text(
        json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8"
    )
    return snapshot
