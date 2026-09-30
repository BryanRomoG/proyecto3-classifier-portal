"""Confusion matrix and classification metrics, in plain Python (rubric 4.2).

Deliberately independent of torch and of any ML library, so the same code can recompute
the final numbers from nothing but the saved per-sample predictions CSV. Conventions:
rows are the **true** class, columns the **predicted** class; a class with no predictions
(or no support) gets precision/recall/F1 = 0.0 rather than NaN.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path


def confusion_matrix(
    y_true: Sequence[int], y_pred: Sequence[int], n_classes: int
) -> list[list[int]]:
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred must have the same length")
    matrix = [[0] * n_classes for _ in range(n_classes)]
    for truth, predicted in zip(y_true, y_pred, strict=True):
        matrix[truth][predicted] += 1
    return matrix


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def classification_metrics(matrix: list[list[int]], class_names: Sequence[str]) -> dict:
    n = len(class_names)
    total = sum(sum(row) for row in matrix)
    correct = sum(matrix[i][i] for i in range(n))
    per_class: dict[str, dict[str, float | int]] = {}
    for i, name in enumerate(class_names):
        true_positive = matrix[i][i]
        support = sum(matrix[i])
        predicted = sum(matrix[r][i] for r in range(n))
        precision = _ratio(true_positive, predicted)
        recall = _ratio(true_positive, support)
        per_class[name] = {
            "precision": precision,
            "recall": recall,
            "f1": _ratio(2 * precision * recall, precision + recall),
            "support": support,
            "predicted": predicted,
        }
    return {
        "total": total,
        "correct": correct,
        "accuracy": _ratio(correct, total),
        "macro_f1": sum(c["f1"] for c in per_class.values()) / n,
        "per_class": per_class,
        "confusion_matrix": {
            "rows": "true",
            "columns": "predicted",
            "labels": list(class_names),
            "matrix": matrix,
        },
    }


def most_confused_pair(matrix: list[list[int]], class_names: Sequence[str]) -> dict | None:
    best: tuple[int, int, int] | None = None
    for i, row in enumerate(matrix):
        for j, count in enumerate(row):
            if i != j and count and (best is None or count > best[0]):
                best = (count, i, j)
    if best is None:
        return None
    count, i, j = best
    return {"true": class_names[i], "predicted": class_names[j], "count": count}


def meets_threshold(correct: int, total: int, threshold: float = 0.85) -> bool:
    """``correct / total >= threshold`` with no rounding before the comparison."""

    return total > 0 and correct / total >= threshold


def metrics_from_predictions_csv(path: Path) -> dict:
    """Recompute everything from the per-sample CSV alone (independent audit, T3-3.8)."""

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path}: no predictions")
    class_names = sorted(
        column.removeprefix("prob_") for column in columns if column.startswith("prob_")
    )
    index = {name: i for i, name in enumerate(class_names)}
    for number, row in enumerate(rows, start=2):
        for column in ("true_label", "predicted_label"):
            if row[column] not in index:
                raise ValueError(
                    f"{path}:{number}: {column} {row[column]!r} is not one of {class_names}"
                )
        if "correct" in row:
            expected = row["true_label"] == row["predicted_label"]
            if row["correct"] != str(expected):
                raise ValueError(
                    f"{path}:{number}: correct={row['correct']!r} contradicts "
                    f"true_label={row['true_label']!r}, predicted_label={row['predicted_label']!r}"
                )
    y_true = [index[row["true_label"]] for row in rows]
    y_pred = [index[row["predicted_label"]] for row in rows]
    return classification_metrics(confusion_matrix(y_true, y_pred, len(class_names)), class_names)
