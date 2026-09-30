"""T3-3.1 / T3-3.2: the committed snapshot of MLflow matches the runs it was read from.

Two short runs on synthetic data (one of them a bit-identical repeat, which must be exported
but marked invalid), then ``export-runs`` through the CLI: every run is present with its
parameters, lineage tags, per-epoch history and curves, and nothing is invented.
"""

from __future__ import annotations

import hashlib
import json

from mlflow.tracking import MlflowClient
from tests_classifier_helpers import tiny_config

from dataset_quality.classifier.__main__ import main as cli
from dataset_quality.classifier.training import train


def test_export_runs_snapshots_every_run_with_history_and_curves(
    synthetic, tmp_path, mlflow_tracking
) -> None:
    outcomes = [
        train(
            tiny_config(max_epochs=3),
            manifest_path=synthetic.manifest_path,
            data_root=synthetic.root,
            output_root=tmp_path / "runs",
            pipeline_root=synthetic.root,
            experiment_name="exp",
            run_name=name,
            device="cpu",
        )
        for name in ("first", "repeat")
    ]
    report_dir = tmp_path / "reports"

    code = cli(
        [
            "export-runs",
            "--experiment",
            "exp",
            "--manifest",
            str(synthetic.manifest_path),
            "--report-dir",
            str(report_dir),
        ]
    )

    assert code == 0
    snapshot = json.loads((report_dir / "mlflow_runs.json").read_text(encoding="utf-8"))
    assert (
        snapshot["manifest_sha256"]
        == hashlib.sha256(synthetic.manifest_path.read_bytes()).hexdigest()
    )
    (experiment,) = snapshot["experiments"]
    assert experiment["runs"] == 2
    assert experiment["valid_runs"] == 1
    first, repeat = experiment["run_list"]
    assert [first["run_id"], repeat["run_id"]] == [o.run_id for o in outcomes]
    assert first["valid"] and not first["invalid_reasons"]
    assert not repeat["valid"] and repeat["invalid_reasons"]

    logged = MlflowClient().get_run(first["run_id"]).data
    assert first["params"] == logged.params
    assert first["metrics"] == logged.metrics
    assert first["tags"]["manifest_sha256"] == snapshot["manifest_sha256"]
    assert not any(key.startswith("mlflow.") for key in first["tags"])
    assert [row["epoch"] for row in first["history"]] == list(
        range(1, int(logged.metrics["stopped_epoch"]) + 1)
    )
    assert first["history"][-1]["val_loss"] == logged.metrics["val_loss"]
    assert "model.pt" in first["artifacts"]
    assert (report_dir / first["curves"]).is_file()
    assert (report_dir / repeat["curves"]).is_file()
