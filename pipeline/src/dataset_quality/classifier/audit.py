"""Executable audits of the classifier evidence (rubric 2.3, 3.1-3.3, 4.2).

Each function re-derives a claim from primary data -- the MLflow tracking server and the
committed reports -- and returns every individual check next to an overall verdict. None
of them writes to MLflow or to ``reports/``; they are safe to run at any time.

* ``audit_runs``        -- the rubric-valid runs as MLflow actually holds them: status,
  manifest, classes, weights changed, >= 2 epochs, a config the trainer accepts, no exact
  duplicates, >= 10 valid runs, each of the seven hyperparameters with >= 2 values *among
  the valid runs*, and the logging each run must carry.
* ``audit_selection``   -- policy -> valid runs -> ranking -> selected run and checkpoint ->
  selection before the test was opened -> re-selection now refused.
* ``compare_runs``      -- two runs meant to be repeats: same manifest, config, seeds,
  device and code; same sample order and initial weights; metric differences.
* ``audit_test_predictions`` -- the final metrics recomputed from the per-sample CSV
  alone and compared with ``test_evaluation.json`` and the selected run's MLflow metrics.
"""

from __future__ import annotations

import csv
import json
import tempfile
from collections import Counter
from pathlib import Path

import mlflow
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from dataset_quality.classifier.config import (
    SEARCHED_HYPERPARAMETERS,
    TrainingConfig,
    validation_issues,
)
from dataset_quality.classifier.data import load_manifest, split_records
from dataset_quality.classifier.experiments import valid_runs
from dataset_quality.classifier.metrics import meets_threshold, metrics_from_predictions_csv
from dataset_quality.classifier.selection import (
    EVALUATION_REPORT,
    SELECTION_REPORT,
    SelectionError,
    SelectionPolicy,
    rank_candidates,
    select_candidate,
)

EPOCH_METRICS = ("train_loss", "train_accuracy", "val_loss", "val_accuracy")
SUMMARY_METRICS = ("best_epoch", "stopped_epoch", "best_val_accuracy", "best_val_loss")
SEED_PARAMS = ("seed.partition", "seed.shuffle", "seed.augmentation", "seed.init")
REQUIRED_TAGS = (
    "git_commit",
    "dvc_raw_md5",
    "quality_gate_status",
    "dataset_version",
    "manifest_sha256",
    "classes",
    "initial_weights",
    "initial_state_sha256",
    "epoch1_order_sha256",
    "final_state_sha256",
    "checkpoint_sha256",
    "weights_changed",
)
REQUIRED_ARTIFACTS = (
    "model.pt",
    "curves.png",
    "history.json",
    "config.json",
    "class_map.json",
    "environment.json",
    "sample_order.json",
)
PREDICTIONS_CSV = "test_predictions.csv"


def config_from_params(params: dict[str, str]) -> dict[str, object]:
    """Invert ``TrainingConfig.mlflow_params``: MLflow's flat strings back to a payload."""

    fields = TrainingConfig.model_fields
    payload: dict[str, object] = {}
    for key, value in params.items():
        group, _, sub = key.partition(".")
        if sub and group in fields:
            payload.setdefault(group, {})[sub] = json.loads(value)  # type: ignore[index]
        elif key in fields:
            payload[key] = json.loads(value) if value.startswith("[") else value
    return payload


def _logging_gaps(client: MlflowClient, run) -> list[str]:
    params, tags, metrics = run.data.params, run.data.tags, run.data.metrics
    missing = [f"param {p}" for p in (*SEARCHED_HYPERPARAMETERS, *SEED_PARAMS) if p not in params]
    missing += [f"tag {t}" for t in REQUIRED_TAGS if not tags.get(t)]
    missing += [f"metric {m}" for m in SUMMARY_METRICS if m not in metrics]
    epochs = list(range(1, int(metrics.get("stopped_epoch", 0)) + 1))
    for key in EPOCH_METRICS:
        steps = sorted(point.step for point in client.get_metric_history(run.info.run_id, key))
        if steps != epochs:
            missing.append(f"per-epoch {key} (steps {steps}, expected {epochs})")
    artifacts = {artifact.path for artifact in client.list_artifacts(run.info.run_id)}
    missing += [f"artifact {a}" for a in REQUIRED_ARTIFACTS if a not in artifacts]
    return missing


def audit_runs(
    client: MlflowClient, experiment_name: str, manifest_sha256: str, classes: list[str]
) -> dict:
    rows = valid_runs(client, experiment_name, manifest_sha256, classes)
    for row in rows:
        run = client.get_run(row["run_id"])
        tags = run.data.tags
        issues = validation_issues(config_from_params(run.data.params))
        row["manifest_sha256"] = tags.get("manifest_sha256")
        row["classes"] = json.loads(tags["classes"]) if tags.get("classes") else None
        row["weights_changed"] = tags.get("weights_changed") == "true"
        row["config_valid"] = not issues
        row["config_issues"] = issues
        row["logging_gaps"] = _logging_gaps(client, run) if row["valid"] else None

    valid = [row for row in rows if row["valid"]]
    coverage = {
        name: sorted({str(row["params"][name]) for row in valid})
        for name in SEARCHED_HYPERPARAMETERS
    }
    signatures = [tuple(row["params"][n] for n in SEARCHED_HYPERPARAMETERS) for row in valid]
    checks = {
        "at_least_10_valid_runs": len(valid) >= 10,
        "valid_runs_finished": all(row["status"] == "FINISHED" for row in valid),
        "valid_runs_same_manifest": all(row["manifest_sha256"] == manifest_sha256 for row in valid),
        "valid_runs_same_classes": all(row["classes"] == classes for row in valid),
        "valid_runs_weights_changed": all(row["weights_changed"] for row in valid),
        "valid_runs_at_least_2_epochs": all((row["stopped_epoch"] or 0) >= 2 for row in valid),
        "valid_runs_config_valid": all(row["config_valid"] for row in valid),
        "valid_runs_no_exact_duplicates": len(set(signatures)) == len(signatures),
        "each_hyperparameter_two_values": all(len(v) >= 2 for v in coverage.values()),
        "valid_runs_logging_complete": all(not row["logging_gaps"] for row in valid),
    }
    return {
        "experiment": experiment_name,
        "manifest_sha256": manifest_sha256,
        "classes": classes,
        "runs_total": len(rows),
        "valid_runs": len(valid),
        "coverage_among_valid_runs": coverage,
        "checks": checks,
        "meets_rubric": all(checks.values()),
        "runs": rows,
    }


def audit_selection(
    client: MlflowClient,
    *,
    report_dir: Path,
    policy_path: Path,
    experiment_name: str,
    manifest_sha256: str,
    classes: list[str],
) -> dict:
    selection = json.loads((report_dir / SELECTION_REPORT).read_text(encoding="utf-8"))
    evaluation_path = report_dir / EVALUATION_REPORT
    evaluation = (
        json.loads(evaluation_path.read_text(encoding="utf-8"))
        if evaluation_path.exists()
        else None
    )
    policy = SelectionPolicy.load(policy_path)
    ranked = rank_candidates(valid_runs(client, experiment_name, manifest_sha256, classes), policy)
    tags = client.get_run(selection["run_id"]).data.tags

    reselection_refused = None
    if evaluation is not None:
        # Only once the test is open: select_candidate then refuses on its first line, before
        # reading MLflow or writing anything. Without an evaluation it would really select.
        try:
            select_candidate(
                policy_path=policy_path,
                experiment_name=experiment_name,
                manifest_sha256=manifest_sha256,
                classes=classes,
                report_dir=report_dir,
                artifact_dir=report_dir / ".never-written",
            )
            reselection_refused = False
        except SelectionError as error:
            reselection_refused = "test evaluation already exists" in str(error)

    checks = {
        "policy_file_unchanged": policy.sha256 == selection["policy"]["sha256"],
        "policy_uses_validation_metrics_only": True,  # SelectionPolicy.load refuses otherwise
        "manifest_matches": selection["manifest_sha256"] == manifest_sha256,
        "enough_valid_runs": len(ranked) >= policy.min_valid_runs,
        "selected_run_is_first_by_policy": bool(ranked)
        and ranked[0]["run_id"] == selection["run_id"],
        "ranking_matches_mlflow": [r["run_id"] for r in ranked]
        == [r["run_id"] for r in selection["ranking"]],
        "checkpoint_sha256_matches_mlflow": tags.get("checkpoint_sha256")
        == selection["checkpoint_sha256"],
        "mlflow_marks_selected_run": tags.get("selected_candidate") == "true"
        and tags.get("selected_at") == selection["selected_at"],
    }
    if evaluation is not None:
        checks.update(
            {
                "evaluated_the_selected_run": evaluation["run_id"] == selection["run_id"]
                and evaluation["checkpoint_sha256"] == selection["checkpoint_sha256"],
                "selected_before_test_opened": selection["selected_at"]
                < evaluation["evaluated_at"],
                "selection_records_the_same_test_opening": selection.get("test_evaluated_at")
                == evaluation["evaluated_at"],
                "reselection_now_refused": reselection_refused,
            }
        )
    return {
        "policy": {"metric": policy.metric, "mode": policy.mode, "sha256": policy.sha256},
        "run_id": selection["run_id"],
        "run_name": selection["run_name"],
        "checkpoint_sha256": selection["checkpoint_sha256"],
        "selected_at": selection["selected_at"],
        "test_evaluated_at": evaluation["evaluated_at"] if evaluation else None,
        "valid_runs": len(ranked),
        "ranking": [
            {k: r[k] for k in ("run_id", "run_name", policy.metric, "best_val_loss")}
            for r in ranked
        ],
        "checks": checks,
        "passes": all(checks.values()),
    }


def _run_artifact_json(run_id: str, name: str) -> object | None:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            local = mlflow.artifacts.download_artifacts(
                run_id=run_id, artifact_path=name, dst_path=tmp
            )
        except (MlflowException, OSError):
            return None
        return json.loads(Path(local).read_text(encoding="utf-8"))


def _run_facts(client: MlflowClient, run_id: str) -> dict:
    run = client.get_run(run_id)
    params, tags = run.data.params, run.data.tags
    environment = _run_artifact_json(run_id, "environment.json") or {}
    return {
        "run_id": run_id,
        "run_name": run.info.run_name,
        "status": run.info.status,
        "manifest_sha256": tags.get("manifest_sha256"),
        "config": config_from_params(params),
        "seeds": {name: params.get(name) for name in SEED_PARAMS},
        "device": params.get("device", environment.get("device")),
        "device_name": tags.get("device_name", environment.get("cuda_device_name")),
        "packages": environment.get("packages"),
        "git_commit": tags.get("git_commit"),
        "test_split_used": tags.get("test_split_used"),
        "initial_state_sha256": tags.get("initial_state_sha256"),
        "sample_order": _run_artifact_json(run_id, "sample_order.json"),
        "final_state_sha256": tags.get("final_state_sha256"),
        "history": {
            key: [
                p.value
                for p in sorted(client.get_metric_history(run_id, key), key=lambda p: p.step)
            ]
            for key in EPOCH_METRICS
        },
    }


def compare_runs(client: MlflowClient, run_a: str, run_b: str, tolerance: float = 1e-6) -> dict:
    a, b = _run_facts(client, run_a), _run_facts(client, run_b)
    differences = {
        key: max(
            (abs(x - y) for x, y in zip(a["history"][key], b["history"][key], strict=False)),
            default=0.0,
        )
        for key in EPOCH_METRICS
    }
    same_epochs = all(len(a["history"][k]) == len(b["history"][k]) for k in EPOCH_METRICS)
    inputs = {
        "same_manifest": a["manifest_sha256"] == b["manifest_sha256"],
        "same_config": a["config"] == b["config"],
        "same_seeds": a["seeds"] == b["seeds"],
        "same_device": (a["device"], a["device_name"]) == (b["device"], b["device_name"]),
        "same_library_versions": a["packages"] == b["packages"],
        "same_code": a["git_commit"] == b["git_commit"],
        "test_split_untouched": a["test_split_used"] == b["test_split_used"] == "false",
        "both_finished": a["status"] == b["status"] == "FINISHED",
    }
    outcomes = {
        "same_sample_order": a["sample_order"] is not None
        and a["sample_order"] == b["sample_order"],
        "same_initial_weights": a["initial_state_sha256"] == b["initial_state_sha256"],
        "same_number_of_epochs": same_epochs,
        "metrics_within_tolerance": same_epochs
        and all(value <= tolerance for value in differences.values()),
        "same_final_weights": a["final_state_sha256"] == b["final_state_sha256"],
    }
    required = {k: v for k, v in outcomes.items() if k != "same_final_weights"}
    return {
        "run_a": {k: v for k, v in a.items() if k not in ("packages",)},
        "run_b": {k: v for k, v in b.items() if k not in ("packages",)},
        "tolerance": tolerance,
        "max_abs_metric_difference": differences,
        "inputs": inputs,
        "outcomes": outcomes,
        "reproducible": all(inputs.values()) and all(required.values()),
    }


def audit_test_predictions(
    *,
    report_dir: Path,
    manifest_path: Path | None = None,
    client: MlflowClient | None = None,
) -> dict:
    """Recompute the final metrics from the CSV alone and compare with every stored copy."""

    recomputed = metrics_from_predictions_csv(report_dir / PREDICTIONS_CSV)
    recomputed["meets_target_0.85"] = meets_threshold(recomputed["correct"], recomputed["total"])
    stored = json.loads((report_dir / EVALUATION_REPORT).read_text(encoding="utf-8"))

    compared = ("total", "correct", "accuracy", "macro_f1", "confusion_matrix", "per_class")
    against_report = {key: stored.get(key) == recomputed[key] for key in compared}
    against_report["meets_target"] = stored.get("meets_target") == recomputed["meets_target_0.85"]

    baseline = None
    if manifest_path is not None:
        # Same rule as evaluation.py: the most frequent class of the *train* split, scored on
        # the test predictions (reading train labels never touches the test).
        manifest = load_manifest(manifest_path).manifest
        train = Counter(r.category_name for r in split_records(manifest, "train"))
        majority = max(sorted(train), key=train.__getitem__)
        with (report_dir / PREDICTIONS_CSV).open(newline="", encoding="utf-8") as handle:
            truths = [row["true_label"] for row in csv.DictReader(handle)]
        correct = sum(1 for truth in truths if truth == majority)
        baseline = {"class": majority, "correct": correct, "accuracy": correct / len(truths)}
        against_report["majority_baseline"] = {
            k: stored["majority_baseline"][k] for k in ("class", "correct", "accuracy")
        } == baseline

    against_mlflow = None
    if client is not None:
        metrics = client.get_run(stored["run_id"]).data.metrics
        expected = {
            "test_total": recomputed["total"],
            "test_correct": recomputed["correct"],
            "test_accuracy": recomputed["accuracy"],
            "test_macro_f1": recomputed["macro_f1"],
            **{
                f"test_{name}_{key}": values[key]
                for name, values in recomputed["per_class"].items()
                for key in ("precision", "recall", "f1")
            },
        }
        if baseline is not None:
            expected["test_majority_baseline_accuracy"] = baseline["accuracy"]
        against_mlflow = {key: metrics.get(key) == value for key, value in expected.items()}

    return {
        "run_id": stored["run_id"],
        "recomputed": recomputed,
        "majority_baseline": baseline,
        "matches_test_evaluation_json": against_report,
        "matches_mlflow": against_mlflow,
        "matches": all(against_report.values())
        and (against_mlflow is None or all(against_mlflow.values())),
    }
