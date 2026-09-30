"""T3-3.2: choose the candidate by a pre-declared validation metric, before any test.

The policy (``experiments/selection_policy.yaml``) is committed before the runs, so the
metric cannot be picked after looking at results. Selection only ever reads *validation*
metrics from MLflow, and it refuses to run once a test evaluation exists: the chronology
"select, then open the test" is enforced, not just promised.

The result, ``reports/classifier/selection.json``, pins one run ID and the SHA-256 of that
run's checkpoint as downloaded from MLflow; the final evaluation verifies both.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import mlflow
import yaml
from mlflow.tracking import MlflowClient

from dataset_quality.classifier.experiments import valid_runs
from dataset_quality.classifier.training import CHECKPOINT_NAME

EVALUATION_REPORT = "test_evaluation.json"
SELECTION_REPORT = "selection.json"


class SelectionError(RuntimeError):
    """The candidate cannot be selected (no valid runs, test already opened, ...)."""


@dataclass(frozen=True)
class SelectionPolicy:
    metric: str
    mode: str
    tie_breakers: list[tuple[str, str]]
    min_valid_runs: int
    sha256: str

    @classmethod
    def load(cls, path: Path) -> SelectionPolicy:
        raw = path.read_bytes()
        document = yaml.safe_load(raw)
        policy = cls(
            metric=document["metric"],
            mode=document["mode"],
            tie_breakers=[(t["metric"], t["mode"]) for t in document.get("tie_breakers", [])],
            min_valid_runs=int(document.get("min_valid_runs", 10)),
            sha256=hashlib.sha256(raw).hexdigest(),
        )
        for metric, mode in [(policy.metric, policy.mode), *policy.tie_breakers]:
            if not metric.startswith(("best_val_", "val_")):
                raise SelectionError(f"selection may only use validation metrics, got {metric}")
            if mode not in {"min", "max"}:
                raise SelectionError(f"mode must be min or max, got {mode}")
        return policy

    def sort_key(self, row: dict) -> tuple:
        key = []
        for metric, mode in [(self.metric, self.mode), *self.tie_breakers]:
            value = row[metric]
            key.append(-value if mode == "max" else value)
        key.append(row["start_time"])
        return tuple(key)


def rank_candidates(rows: list[dict], policy: SelectionPolicy) -> list[dict]:
    return sorted((row for row in rows if row["valid"]), key=policy.sort_key)


def select_candidate(
    *,
    policy_path: Path,
    experiment_name: str,
    manifest_sha256: str,
    classes: list[str],
    report_dir: Path,
    artifact_dir: Path,
) -> dict:
    if (report_dir / EVALUATION_REPORT).exists():
        raise SelectionError(
            "a test evaluation already exists: selecting (again) after opening the test "
            "would invalidate the protocol"
        )
    policy = SelectionPolicy.load(policy_path)
    client = MlflowClient()
    rows = valid_runs(client, experiment_name, manifest_sha256, classes)
    ranked = rank_candidates(rows, policy)
    if len(ranked) < policy.min_valid_runs:
        raise SelectionError(
            f"only {len(ranked)} valid runs; the policy requires {policy.min_valid_runs}"
        )
    chosen = ranked[0]
    run_id = chosen["run_id"]

    target = artifact_dir / run_id
    target.mkdir(parents=True, exist_ok=True)
    local = Path(
        mlflow.artifacts.download_artifacts(
            run_id=run_id, artifact_path=CHECKPOINT_NAME, dst_path=str(target)
        )
    )
    checkpoint_sha = hashlib.sha256(local.read_bytes()).hexdigest()
    logged_sha = client.get_run(run_id).data.tags.get("checkpoint_sha256")
    if checkpoint_sha != logged_sha:
        raise SelectionError(
            f"downloaded checkpoint sha256 {checkpoint_sha} != logged {logged_sha}"
        )

    selected_at = datetime.now(UTC).isoformat()
    selection = {
        "selected_at": selected_at,
        "experiment_name": experiment_name,
        "policy": {
            "file": policy_path.name,
            "sha256": policy.sha256,
            "metric": policy.metric,
            "mode": policy.mode,
            "tie_breakers": policy.tie_breakers,
        },
        "manifest_sha256": manifest_sha256,
        "classes": classes,
        "run_id": run_id,
        "run_name": chosen["run_name"],
        "checkpoint_artifact": f"runs:/{run_id}/{CHECKPOINT_NAME}",
        "checkpoint_sha256": checkpoint_sha,
        "selected_metric_value": chosen[policy.metric],
        "valid_runs": len(ranked),
        "ranking": [
            {
                k: row[k]
                for k in (
                    "run_id",
                    "run_name",
                    "best_val_accuracy",
                    "best_val_loss",
                    "best_epoch",
                    "params",
                )
            }
            for row in ranked
        ],
        "test_opened": False,
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / SELECTION_REPORT).write_text(
        json.dumps(selection, indent=2, sort_keys=True), encoding="utf-8"
    )
    client.set_tag(run_id, "selected_candidate", "true")
    client.set_tag(run_id, "selected_at", selected_at)
    client.set_tag(run_id, "selection_policy_sha256", policy.sha256)
    return selection
