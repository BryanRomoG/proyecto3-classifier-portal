"""Rubric 2.3 / 3.1-3.3 / 4.2: the evidence audits pass on sound data and catch tampering.

Short runs on synthetic data through the real trainer, selection and final evaluation, then
each audit: it must pass on the untouched evidence and flip the specific check when one
piece is altered (a missing tag, a policy edit, an edited report, a different seed).
"""

from __future__ import annotations

import hashlib
import json

import pytest
from mlflow.tracking import MlflowClient
from tests_classifier_helpers import tiny_config

from dataset_quality.classifier.__main__ import main as cli
from dataset_quality.classifier.audit import (
    audit_runs,
    audit_selection,
    audit_test_predictions,
    compare_runs,
    config_from_params,
)
from dataset_quality.classifier.config import TrainingConfig
from dataset_quality.classifier.evaluation import evaluate_test
from dataset_quality.classifier.selection import select_candidate
from dataset_quality.classifier.training import train

CLASSES = ["car", "person"]


def _train(synthetic, tmp_path, name, experiment="exp", **overrides):
    return train(
        tiny_config(**overrides),
        manifest_path=synthetic.manifest_path,
        data_root=synthetic.root,
        output_root=tmp_path / "runs",
        pipeline_root=synthetic.root,
        experiment_name=experiment,
        run_name=name,
        device="cpu",
    )


def _sha(synthetic) -> str:
    return hashlib.sha256(synthetic.manifest_path.read_bytes()).hexdigest()


@pytest.fixture
def evaluated(synthetic, tmp_path, mlflow_tracking):
    for name, lr in (("a", 0.01), ("b", 0.003)):
        _train(synthetic, tmp_path, name, learning_rate=lr, max_epochs=3)
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        "metric: best_val_accuracy\nmode: max\ntie_breakers:\n"
        "  - {metric: best_val_loss, mode: min}\nmin_valid_runs: 2\n",
        encoding="utf-8",
    )
    report_dir = tmp_path / "reports"
    selection = select_candidate(
        policy_path=policy,
        experiment_name="exp",
        manifest_sha256=_sha(synthetic),
        classes=CLASSES,
        report_dir=report_dir,
        artifact_dir=tmp_path / "selected",
    )
    evaluate_test(
        report_dir=report_dir,
        checkpoint=tmp_path / "selected" / selection["run_id"] / "model.pt",
        manifest_path=synthetic.manifest_path,
        data_root=synthetic.root,
    )
    return {"policy": policy, "report_dir": report_dir, "selection": selection}


def test_logged_params_round_trip_to_the_same_config() -> None:
    config = TrainingConfig(hidden_layers=[], augment=False, early_stopping={"patience": 3})

    assert TrainingConfig.model_validate(config_from_params(config.mlflow_params())) == config


def test_audit_runs_checks_real_runs_and_reports_logging_gaps(
    synthetic, tmp_path, mlflow_tracking
) -> None:
    first = _train(synthetic, tmp_path, "a", learning_rate=0.01)
    _train(synthetic, tmp_path, "b", learning_rate=0.003, batch_size=4)

    audit = audit_runs(MlflowClient(), "exp", _sha(synthetic), CLASSES)

    assert audit["valid_runs"] == 2
    assert audit["coverage_among_valid_runs"]["learning_rate"] == ["0.003", "0.01"]
    assert audit["checks"]["at_least_10_valid_runs"] is False
    assert audit["checks"]["each_hyperparameter_two_values"] is False  # optimizer constant
    for check in (
        "valid_runs_same_manifest",
        "valid_runs_same_classes",
        "valid_runs_weights_changed",
        "valid_runs_config_valid",
        "valid_runs_no_exact_duplicates",
        "valid_runs_logging_complete",
    ):
        assert audit["checks"][check] is True, check
    assert audit["meets_rubric"] is False

    MlflowClient().delete_tag(first.run_id, "dvc_raw_md5")
    audit = audit_runs(MlflowClient(), "exp", _sha(synthetic), CLASSES)
    gaps = next(r for r in audit["runs"] if r["run_id"] == first.run_id)["logging_gaps"]
    assert gaps == ["tag dvc_raw_md5"]
    assert audit["checks"]["valid_runs_logging_complete"] is False


def test_audit_selection_passes_then_catches_an_edited_policy(synthetic, evaluated) -> None:
    kwargs = {
        "report_dir": evaluated["report_dir"],
        "policy_path": evaluated["policy"],
        "experiment_name": "exp",
        "manifest_sha256": _sha(synthetic),
        "classes": CLASSES,
    }

    audit = audit_selection(MlflowClient(), **kwargs)

    assert audit["passes"] is True, audit["checks"]
    assert audit["checks"]["selected_before_test_opened"] is True
    assert audit["checks"]["reselection_now_refused"] is True
    assert audit["run_id"] == evaluated["selection"]["run_id"]

    evaluated["policy"].write_text(
        evaluated["policy"].read_text(encoding="utf-8") + "# edited after the fact\n",
        encoding="utf-8",
    )
    audit = audit_selection(MlflowClient(), **kwargs)
    assert audit["checks"]["policy_file_unchanged"] is False
    assert audit["passes"] is False


def test_audit_test_matches_json_and_mlflow_then_catches_an_edited_report(
    synthetic, evaluated
) -> None:
    report_dir = evaluated["report_dir"]

    audit = audit_test_predictions(
        report_dir=report_dir, manifest_path=synthetic.manifest_path, client=MlflowClient()
    )

    assert audit["matches"] is True, (
        audit["matches_test_evaluation_json"],
        audit["matches_mlflow"],
    )
    assert audit["matches_test_evaluation_json"]["majority_baseline"] is True

    path = report_dir / "test_evaluation.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["accuracy"] = 0.123
    path.write_text(json.dumps(stored), encoding="utf-8")
    audit = audit_test_predictions(report_dir=report_dir, client=MlflowClient())
    assert audit["matches_test_evaluation_json"]["accuracy"] is False
    assert audit["matches"] is False


def test_compare_runs_accepts_true_repeats_and_rejects_a_different_seed(
    synthetic, tmp_path, mlflow_tracking
) -> None:
    a = _train(synthetic, tmp_path, "repro-a", max_epochs=2)
    b = _train(synthetic, tmp_path, "repro-b", max_epochs=2)
    c = _train(synthetic, tmp_path, "repro-c", max_epochs=2, seeds={"init": 7})

    same = compare_runs(MlflowClient(), a.run_id, b.run_id)
    assert same["reproducible"] is True, (same["inputs"], same["outcomes"])
    assert same["outcomes"]["same_final_weights"] is True
    assert set(same["max_abs_metric_difference"].values()) == {0.0}

    different = compare_runs(MlflowClient(), a.run_id, c.run_id)
    assert different["inputs"]["same_seeds"] is False
    assert different["outcomes"]["same_initial_weights"] is False
    assert different["reproducible"] is False


def test_repro_check_cli_trains_two_runs_in_the_repro_experiment_only(
    synthetic, tmp_path, mlflow_tracking
) -> None:
    common = ["--manifest", str(synthetic.manifest_path), "--data-root", str(synthetic.root)]
    common += ["--runs-dir", str(tmp_path / "runs")]
    config = json.dumps(tiny_config(max_epochs=2).model_dump(mode="json"))
    report = tmp_path / "repro.json"

    code = cli(
        [
            "repro-check",
            "--train",
            "--json",
            config,
            "--device",
            "cpu",
            "--report",
            str(report),
            *common,
        ]
    )

    assert code == 0
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["reproducible"] is True
    experiment = MlflowClient().get_experiment_by_name("t3-smoke-repro")
    assert experiment is not None
    assert cli(["repro-check", "--train", "--experiment", "t3-classifier", *common]) == 2
