"""T3-3.3: the one-time final evaluation on the frozen test split (rubric 4.1-4.4).

Preconditions, all checked before a single test image is read:

* ``selection.json`` exists, and its manifest hash equals the manifest being evaluated;
* the checkpoint on disk has exactly the SHA-256 recorded at selection time;
* no final evaluation exists yet. ``audit=True`` re-runs the same checkpoint on the same
  manifest and *compares* with the stored result without overwriting anything — the
  evaluation can be repeated for audit, never used to pick another model.

Outputs in ``reports/classifier/``: ``test_predictions.csv`` (one row per test crop with
true label, prediction and every class probability), ``test_evaluation.json`` (matrix,
accuracy, macro F1, per-class metrics, majority baseline, most confused pair, examples,
the 85% check) and ``confusion_matrix.png``. The same numbers are logged to the selected
MLflow run.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import mlflow

from dataset_quality.classifier.data import load_manifest, split_records
from dataset_quality.classifier.metrics import (
    classification_metrics,
    confusion_matrix,
    meets_threshold,
    metrics_from_predictions_csv,
    most_confused_pair,
)
from dataset_quality.classifier.predict import load_checkpoint, predict_paths
from dataset_quality.classifier.selection import EVALUATION_REPORT, SELECTION_REPORT

PREDICTIONS_CSV = "test_predictions.csv"
MATRIX_PNG = "confusion_matrix.png"
TARGET_ACCURACY = 0.85
EXAMPLES_PER_CLASS = 5


class EvaluationError(RuntimeError):
    """The final evaluation's preconditions do not hold."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plot_matrix(matrix: list[list[int]], labels: list[str], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(1.6 * len(labels) + 2, 1.6 * len(labels) + 1.5))
    axis.imshow(matrix, cmap="Blues")
    axis.set_xticks(range(len(labels)), labels)
    axis.set_yticks(range(len(labels)), labels)
    axis.set_xlabel("predicted")
    axis.set_ylabel("true")
    for i, row in enumerate(matrix):
        for j, count in enumerate(row):
            axis.text(j, i, str(count), ha="center", va="center")
    axis.set_title("Confusion matrix (test)")
    figure.tight_layout()
    figure.savefig(path, dpi=100)
    plt.close(figure)


def _examples(rows: list[dict], class_names: list[str]) -> dict:
    examples: dict[str, dict[str, list[dict]]] = {}
    for name in class_names:
        of_class = [row for row in rows if row["true_label"] == name]
        correct = sorted((r for r in of_class if r["correct"]), key=lambda r: -r["confidence"])
        wrong = sorted((r for r in of_class if not r["correct"]), key=lambda r: -r["confidence"])
        examples[name] = {
            "correct": correct[:EXAMPLES_PER_CLASS],
            "errors": wrong[:EXAMPLES_PER_CLASS],
        }
    return examples


def _predict_test(checkpoint: Path, manifest_path: Path, data_root: Path):
    loaded = load_manifest(manifest_path)
    classifier = load_checkpoint(checkpoint)
    records = split_records(loaded.manifest, "test", allow_test=True)
    predictions = predict_paths(classifier, [data_root / r.relative_path for r in records])
    rows = []
    for record, prediction in zip(records, predictions, strict=True):
        rows.append(
            {
                "annotation_id": record.annotation_id,
                "source_image_id": record.source_image_id,
                "relative_path": record.relative_path,
                "true_label": record.category_name,
                "predicted_label": prediction.label,
                "correct": prediction.label == record.category_name,
                "confidence": prediction.confidence,
                **{f"prob_{k}": v for k, v in prediction.probabilities.items()},
            }
        )
    return loaded, classifier, rows


def _write_predictions(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def evaluate_test(
    *,
    report_dir: Path,
    checkpoint: Path,
    manifest_path: Path,
    data_root: Path,
    audit: bool = False,
) -> dict:
    selection_path = report_dir / SELECTION_REPORT
    report_path = report_dir / EVALUATION_REPORT
    if not selection_path.is_file():
        raise EvaluationError("no selection.json: select the candidate by validation first")
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if report_path.exists() and not audit:
        raise EvaluationError(
            "the test was already evaluated; use --audit to recompute without overwriting"
        )
    if audit and not report_path.exists():
        raise EvaluationError("nothing to audit: no final evaluation exists yet")
    if _sha256(manifest_path) != selection["manifest_sha256"]:
        raise EvaluationError("manifest sha256 differs from the one the candidate was chosen on")
    if _sha256(checkpoint) != selection["checkpoint_sha256"]:
        raise EvaluationError("checkpoint sha256 differs from the selected checkpoint")

    loaded, classifier, rows = _predict_test(checkpoint, manifest_path, data_root)
    class_names = classifier.class_names
    if class_names != selection["classes"]:
        raise EvaluationError(f"checkpoint classes {class_names} != {selection['classes']}")
    index = {name: i for i, name in enumerate(class_names)}
    matrix = confusion_matrix(
        [index[r["true_label"]] for r in rows],
        [index[r["predicted_label"]] for r in rows],
        len(class_names),
    )
    metrics = classification_metrics(matrix, class_names)

    train_counts = Counter(r.category_name for r in split_records(loaded.manifest, "train"))
    majority = max(sorted(train_counts), key=train_counts.__getitem__)
    majority_correct = sum(1 for r in rows if r["true_label"] == majority)
    low_recall = {
        name: values["recall"]
        for name, values in metrics["per_class"].items()
        if values["recall"] < TARGET_ACCURACY
    }

    result = {
        "run_id": selection["run_id"],
        "checkpoint_sha256": selection["checkpoint_sha256"],
        "manifest_sha256": selection["manifest_sha256"],
        "dataset_version": loaded.manifest.dataset_version,
        "selected_at": selection["selected_at"],
        "classes": class_names,
        **metrics,
        "target_accuracy": TARGET_ACCURACY,
        "meets_target": meets_threshold(metrics["correct"], metrics["total"], TARGET_ACCURACY),
        "majority_baseline": {
            "class": majority,
            "chosen_from": "train split label frequency",
            "correct": majority_correct,
            "accuracy": majority_correct / len(rows),
        },
        "most_confused": most_confused_pair(matrix, class_names),
        "classes_below_target_recall": low_recall,
        "examples": _examples(rows, class_names),
    }

    if audit:
        stored = json.loads(report_path.read_text(encoding="utf-8"))
        from_csv = metrics_from_predictions_csv(report_dir / PREDICTIONS_CSV)
        differences = {
            key: {"stored": stored.get(key), "recomputed": result[key], "from_csv": from_csv[key]}
            for key in ("total", "correct", "accuracy", "macro_f1", "confusion_matrix")
            if not (stored.get(key) == result[key] == from_csv[key])
        }
        return {"audit": True, "matches": not differences, "differences": differences}

    evaluated_at = datetime.now(UTC).isoformat()
    if evaluated_at <= selection["selected_at"]:
        raise EvaluationError("evaluation timestamp is not after the selection timestamp")
    result["evaluated_at"] = evaluated_at

    report_dir.mkdir(parents=True, exist_ok=True)
    _write_predictions(rows, report_dir / PREDICTIONS_CSV)
    _plot_matrix(matrix, class_names, report_dir / MATRIX_PNG)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    selection["test_opened"] = True
    selection["test_evaluated_at"] = evaluated_at
    selection_path.write_text(json.dumps(selection, indent=2, sort_keys=True), encoding="utf-8")

    with mlflow.start_run(run_id=selection["run_id"]):
        mlflow.log_metrics(
            {
                "test_accuracy": metrics["accuracy"],
                "test_macro_f1": metrics["macro_f1"],
                "test_total": metrics["total"],
                "test_correct": metrics["correct"],
                "test_majority_baseline_accuracy": result["majority_baseline"]["accuracy"],
                **{
                    f"test_{name}_{key}": values[key]
                    for name, values in metrics["per_class"].items()
                    for key in ("precision", "recall", "f1")
                },
            }
        )
        mlflow.set_tags({"test_evaluated_at": evaluated_at, "test_split_used": "final_eval_only"})
        for name in (EVALUATION_REPORT, PREDICTIONS_CSV, MATRIX_PNG, SELECTION_REPORT):
            mlflow.log_artifact(str(report_dir / name), artifact_path="test_evaluation")
    return result
