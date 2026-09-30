"""T3-3.2 / T3-3.3: select by validation first, then open the test exactly once.

End to end on synthetic data: two short runs -> selection by the pre-declared validation
metric -> guarded final evaluation -> audit. Also checks the protocol's refusals: no
evaluation without selection or confirmation, no second evaluation, no re-selection after
the test was opened, no evaluation of a swapped checkpoint, and an audit that catches a
tampered predictions file.
"""

from __future__ import annotations

import csv
import json

import pytest
from mlflow.tracking import MlflowClient
from tests_classifier_helpers import tiny_config

from dataset_quality.classifier.__main__ import main as cli
from dataset_quality.classifier.evaluation import EvaluationError, evaluate_test
from dataset_quality.classifier.metrics import metrics_from_predictions_csv
from dataset_quality.classifier.selection import SelectionError, select_candidate
from dataset_quality.classifier.training import train


@pytest.fixture
def selected(synthetic, tmp_path, mlflow_tracking):
    for name, lr in (("a", 0.01), ("b", 0.003)):
        train(
            tiny_config(learning_rate=lr, max_epochs=4),
            manifest_path=synthetic.manifest_path,
            data_root=synthetic.root,
            output_root=tmp_path / "runs",
            pipeline_root=synthetic.root,
            experiment_name="exp",
            run_name=name,
        )
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        "metric: best_val_accuracy\nmode: max\ntie_breakers:\n"
        "  - {metric: best_val_loss, mode: min}\nmin_valid_runs: 2\n",
        encoding="utf-8",
    )
    import hashlib

    report_dir = tmp_path / "reports"
    selection = select_candidate(
        policy_path=policy,
        experiment_name="exp",
        manifest_sha256=hashlib.sha256(synthetic.manifest_path.read_bytes()).hexdigest(),
        classes=["car", "person"],
        report_dir=report_dir,
        artifact_dir=tmp_path / "selected",
    )
    checkpoint = tmp_path / "selected" / selection["run_id"] / "model.pt"
    return {
        "selection": selection,
        "report_dir": report_dir,
        "checkpoint": checkpoint,
        "policy": policy,
    }


def _evaluate(synthetic, selected, **kwargs):
    return evaluate_test(
        report_dir=selected["report_dir"],
        checkpoint=selected["checkpoint"],
        manifest_path=synthetic.manifest_path,
        data_root=synthetic.root,
        **kwargs,
    )


def test_selection_picks_the_best_validation_run_and_pins_its_checkpoint(selected) -> None:
    selection = selected["selection"]
    ranking = selection["ranking"]

    assert ranking[0]["run_id"] == selection["run_id"]
    assert ranking[0]["best_val_accuracy"] >= ranking[1]["best_val_accuracy"]
    assert selection["test_opened"] is False
    tags = MlflowClient().get_run(selection["run_id"]).data.tags
    assert tags["selected_candidate"] == "true"
    assert tags["checkpoint_sha256"] == selection["checkpoint_sha256"]


def test_final_evaluation_writes_per_sample_predictions_and_consistent_metrics(
    synthetic, selected
) -> None:
    result = _evaluate(synthetic, selected)
    report_dir = selected["report_dir"]

    n_test = sum(len(s.crops) for s in synthetic.manifest.splits if s.name == "test")
    assert result["total"] == n_test
    assert sum(map(sum, result["confusion_matrix"]["matrix"])) == n_test
    assert result["evaluated_at"] > result["selected_at"]
    assert result["meets_target"] == (result["correct"] / result["total"] >= 0.85)
    assert "accuracy" in result["majority_baseline"]

    with (report_dir / "test_predictions.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    test_ids = {
        c.annotation_id for s in synthetic.manifest.splits if s.name == "test" for c in s.crops
    }
    assert {int(r["annotation_id"]) for r in rows} == test_ids
    recomputed = metrics_from_predictions_csv(report_dir / "test_predictions.csv")
    assert recomputed["accuracy"] == result["accuracy"]
    assert recomputed["confusion_matrix"] == result["confusion_matrix"]

    metrics = MlflowClient().get_run(result["run_id"]).data.metrics
    assert metrics["test_accuracy"] == pytest.approx(result["accuracy"])
    assert metrics["test_total"] == n_test


def test_the_test_is_opened_only_once_and_selection_is_then_frozen(synthetic, selected) -> None:
    _evaluate(synthetic, selected)

    with pytest.raises(EvaluationError, match="already evaluated"):
        _evaluate(synthetic, selected)
    with pytest.raises(SelectionError, match="test evaluation already exists"):
        select_candidate(
            policy_path=selected["policy"],
            experiment_name="exp",
            manifest_sha256=selected["selection"]["manifest_sha256"],
            classes=["car", "person"],
            report_dir=selected["report_dir"],
            artifact_dir=selected["report_dir"],
        )


def test_audit_recomputes_and_detects_a_tampered_prediction(synthetic, selected) -> None:
    _evaluate(synthetic, selected)
    assert _evaluate(synthetic, selected, audit=True)["matches"] is True

    path = selected["report_dir"] / "test_predictions.csv"
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["predicted_label"] = "person" if rows[0]["predicted_label"] == "car" else "car"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    audit = _evaluate(synthetic, selected, audit=True)
    assert audit["matches"] is False


def test_a_swapped_checkpoint_is_refused(synthetic, selected) -> None:
    selected["checkpoint"].write_bytes(selected["checkpoint"].read_bytes() + b"x")

    with pytest.raises(EvaluationError, match="checkpoint sha256"):
        _evaluate(synthetic, selected)


def test_evaluation_requires_a_selection(synthetic, tmp_path) -> None:
    with pytest.raises(EvaluationError, match="no selection"):
        evaluate_test(
            report_dir=tmp_path / "empty",
            checkpoint=tmp_path / "model.pt",
            manifest_path=synthetic.manifest_path,
            data_root=synthetic.root,
        )


def test_cli_refuses_to_open_the_test_without_explicit_confirmation(
    synthetic, selected, capsys
) -> None:
    code = cli(
        [
            "evaluate",
            "--report-dir",
            str(selected["report_dir"]),
            "--manifest",
            str(synthetic.manifest_path),
        ]
    )

    assert code == 2
    assert not (selected["report_dir"] / "test_evaluation.json").exists()
    assert (
        json.loads((selected["report_dir"] / "selection.json").read_text())["test_opened"] is False
    )
