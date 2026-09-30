"""T3-3.3: confusion matrix and metrics against hand-computed values (rubric 4.2 / 4.3)."""

from __future__ import annotations

import csv

import pytest

from dataset_quality.classifier.metrics import (
    classification_metrics,
    confusion_matrix,
    meets_threshold,
    metrics_from_predictions_csv,
    most_confused_pair,
)

CLASSES = ["car", "person"]
# 6 car, 4 person; true car -> 5 car + 1 person; true person -> 2 car + 2 person
Y_TRUE = [0, 0, 0, 0, 0, 0, 1, 1, 1, 1]
Y_PRED = [0, 0, 0, 0, 0, 1, 0, 0, 1, 1]


def test_matrix_rows_are_true_columns_are_predicted() -> None:
    assert confusion_matrix(Y_TRUE, Y_PRED, 2) == [[5, 1], [2, 2]]


def test_metrics_match_hand_computation() -> None:
    metrics = classification_metrics(confusion_matrix(Y_TRUE, Y_PRED, 2), CLASSES)

    assert metrics["total"] == 10 and metrics["correct"] == 7
    assert metrics["accuracy"] == pytest.approx(0.7)
    car, person = metrics["per_class"]["car"], metrics["per_class"]["person"]
    assert car["precision"] == pytest.approx(5 / 7)
    assert car["recall"] == pytest.approx(5 / 6)
    assert person["precision"] == pytest.approx(2 / 3)
    assert person["recall"] == pytest.approx(0.5)
    assert person["support"] == 4
    car_f1 = 2 * (5 / 7) * (5 / 6) / ((5 / 7) + (5 / 6))
    person_f1 = 2 * (2 / 3) * 0.5 / ((2 / 3) + 0.5)
    assert metrics["macro_f1"] == pytest.approx((car_f1 + person_f1) / 2)


def test_a_class_never_predicted_gets_zero_not_nan() -> None:
    metrics = classification_metrics(confusion_matrix([0, 1], [0, 0], 2), CLASSES)

    assert metrics["per_class"]["person"] == {
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
        "support": 1,
        "predicted": 0,
    }


def test_threshold_is_compared_without_rounding() -> None:
    assert meets_threshold(17, 20) is True  # exactly 0.85
    assert meets_threshold(849_999, 1_000_000) is False  # 0.849999 would round to 0.85
    assert meets_threshold(0, 0) is False


def test_most_confused_pair() -> None:
    assert most_confused_pair([[5, 1], [2, 2]], CLASSES) == {
        "true": "person",
        "predicted": "car",
        "count": 2,
    }
    assert most_confused_pair([[3, 0], [0, 3]], CLASSES) is None


def test_recompute_from_predictions_csv_alone(tmp_path) -> None:
    path = tmp_path / "predictions.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["true_label", "predicted_label", "prob_car", "prob_person"]
        )
        writer.writeheader()
        for truth, predicted in zip(Y_TRUE, Y_PRED, strict=True):
            writer.writerow(
                {
                    "true_label": CLASSES[truth],
                    "predicted_label": CLASSES[predicted],
                    "prob_car": 0.5,
                    "prob_person": 0.5,
                }
            )

    recomputed = metrics_from_predictions_csv(path)

    assert recomputed == classification_metrics(confusion_matrix(Y_TRUE, Y_PRED, 2), CLASSES)
