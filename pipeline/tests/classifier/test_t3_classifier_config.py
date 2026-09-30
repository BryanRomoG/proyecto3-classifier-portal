"""T3-1.4: the training config rejects invalid values before any job exists (rubric 2.2)."""

from __future__ import annotations

import json

import pytest

from dataset_quality.classifier.__main__ import main as cli
from dataset_quality.classifier.config import (
    SEARCHED_HYPERPARAMETERS,
    TrainingConfig,
    json_schema,
    validation_errors,
)


def test_defaults_are_valid() -> None:
    assert validation_errors({}) == []
    assert TrainingConfig().optimizer == "adam"


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"batch_size": 0}, "batch_size"),
        ({"batch_size": 1024}, "batch_size"),
        ({"learning_rate": 0}, "learning_rate"),
        ({"learning_rate": -0.1}, "learning_rate"),
        ({"max_epochs": 0}, "max_epochs"),
        ({"image_size": 16}, "image_size"),
        ({"dropout": 1.0}, "dropout"),
        ({"dropout": -0.1}, "dropout"),
        ({"optimizer": "rmsprop"}, "optimizer"),
        ({"hidden_layers": [4]}, "hidden_layers"),
        ({"hidden_layers": [64, 64, 64, 64, 64]}, "hidden_layers"),
        ({"early_stopping": {"patience": 0}}, "early_stopping.patience"),
        ({"early_stopping": {"monitor": "test_accuracy"}}, "early_stopping.monitor"),
        ({"batch_sise": 32}, "batch_sise"),
    ],
)
def test_invalid_values_are_rejected_with_a_useful_message(payload: dict, field: str) -> None:
    errors = validation_errors(payload)

    assert errors, f"{payload} must be rejected"
    assert any(error.startswith(field) for error in errors), errors


def test_cli_validate_config_exits_nonzero_and_lists_errors(capsys) -> None:
    code = cli(["validate-config", "--json", json.dumps({"batch_size": 0, "dropout": 2})])

    report = json.loads(capsys.readouterr().out)
    assert code == 2
    assert report["valid"] is False
    assert len(report["errors"]) == 2


def test_cli_train_refuses_invalid_config_before_touching_data(capsys, tmp_path) -> None:
    code = cli(
        [
            "train",
            "--json",
            json.dumps({"learning_rate": 0}),
            "--manifest",
            str(tmp_path / "does-not-exist.json"),
        ]
    )

    assert code == 2
    assert json.loads(capsys.readouterr().out)["valid"] is False
    assert not (tmp_path / "mlflow.db").exists()


def test_schema_exposes_every_searched_hyperparameter() -> None:
    properties = json_schema()["properties"]

    assert set(SEARCHED_HYPERPARAMETERS) <= set(properties)
    assert properties["batch_size"]["minimum"] == 1


def test_mlflow_params_are_the_effective_values() -> None:
    params = TrainingConfig(hidden_layers=[512, 128]).mlflow_params()

    assert params["hidden_layers"] == "[512, 128]"
    assert params["early_stopping.patience"] == "5"
    assert params["optimizer"] == "adam"
