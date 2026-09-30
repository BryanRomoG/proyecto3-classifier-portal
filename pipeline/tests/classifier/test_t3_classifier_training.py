"""T3-1.4 / T3-2.1 / T3-2.5: a real short run, logged to MLflow, reproducible, test untouched."""

from __future__ import annotations

import json
import math

import pytest
import torch
from mlflow.tracking import MlflowClient
from PIL import Image
from tests_classifier_helpers import tiny_config

from dataset_quality.classifier.data import eval_transform, split_records
from dataset_quality.classifier.predict import CheckpointError, load_checkpoint, predict_paths
from dataset_quality.classifier.training import train


def _train(synthetic, tmp_path, **overrides):
    return train(
        tiny_config(**overrides),
        manifest_path=synthetic.manifest_path,
        data_root=synthetic.root,
        output_root=tmp_path / "runs",
        pipeline_root=synthetic.root,
        experiment_name="test-exp",
        run_name="smoke",
        device="cpu",
    )


def test_run_is_logged_with_params_lineage_curves_and_checkpoint(
    synthetic, tmp_path, mlflow_tracking
) -> None:
    outcome = _train(synthetic, tmp_path)
    run = MlflowClient().get_run(outcome.run_id)

    assert run.info.status == "FINISHED"
    params, tags = run.data.params, run.data.tags
    assert params["batch_size"] == "8" and params["optimizer"] == "adam"
    assert params["hidden_layers"] == "[16]" and params["image_size"] == "32"
    assert {"seed.partition", "seed.shuffle", "seed.augmentation", "seed.init"} <= set(params)
    assert tags["manifest_sha256"] == outcome_manifest_sha(synthetic)
    assert tags["dataset_version"] == "v-test"
    assert tags["classes"] == json.dumps(["car", "person"])
    assert tags["git_commit"]
    assert tags["weights_changed"] == "true"
    assert tags["test_split_used"] == "false"

    history = MlflowClient().get_metric_history(outcome.run_id, "val_accuracy")
    assert [m.step for m in history] == list(range(1, outcome.stopped_epoch + 1))
    for metric in ("train_loss", "train_accuracy", "val_loss"):
        assert len(MlflowClient().get_metric_history(outcome.run_id, metric)) == len(history)

    artifacts = {a.path for a in MlflowClient().list_artifacts(outcome.run_id)}
    assert {"model.pt", "curves.png", "history.json", "environment.json", "config.json"} <= (
        artifacts
    )
    status = json.loads((outcome.output_dir / "status.json").read_text(encoding="utf-8"))
    assert status["state"] == "finished"


def outcome_manifest_sha(synthetic) -> str:
    import hashlib

    return hashlib.sha256(synthetic.manifest_path.read_bytes()).hexdigest()


def test_one_optimizer_step_per_minibatch(synthetic, tmp_path, mlflow_tracking) -> None:
    outcome = _train(synthetic, tmp_path, batch_size=5)
    n_train = len(split_records(synthetic.manifest, "train"))

    assert outcome.optimizer_steps == math.ceil(n_train / 5) * outcome.stopped_epoch


def test_same_seeds_same_order_and_same_weights(synthetic, tmp_path, mlflow_tracking) -> None:
    first = _train(synthetic, tmp_path)
    second = _train(synthetic, tmp_path)
    client = MlflowClient()
    tags_a, tags_b = client.get_run(first.run_id).data.tags, client.get_run(second.run_id).data.tags

    assert tags_a["epoch1_order_sha256"] == tags_b["epoch1_order_sha256"]
    assert tags_a["final_state_sha256"] == tags_b["final_state_sha256"]
    assert first.best_val_accuracy == second.best_val_accuracy


def test_a_different_shuffle_seed_changes_the_order(synthetic, tmp_path, mlflow_tracking) -> None:
    first = _train(synthetic, tmp_path)
    second = _train(synthetic, tmp_path, seeds={"shuffle": 7})
    client = MlflowClient()

    assert (
        client.get_run(first.run_id).data.tags["epoch1_order_sha256"]
        != client.get_run(second.run_id).data.tags["epoch1_order_sha256"]
    )


def test_training_never_opens_a_test_crop(
    synthetic, tmp_path, mlflow_tracking, monkeypatch
) -> None:
    opened: list[str] = []
    real_open = Image.open

    def spy(path, *args, **kwargs):
        opened.append(str(path).replace("\\", "/"))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Image, "open", spy)
    _train(synthetic, tmp_path)
    test_paths = {
        r.relative_path for r in split_records(synthetic.manifest, "test", allow_test=True)
    }

    assert opened
    assert not [p for p in opened if any(p.endswith(t) for t in test_paths)]


def test_checkpoint_reloads_in_a_clean_loader_and_predicts(
    synthetic, tmp_path, mlflow_tracking
) -> None:
    outcome = _train(synthetic, tmp_path, max_epochs=6)
    classifier = load_checkpoint(outcome.checkpoint_path)
    val = split_records(synthetic.manifest, "val")

    predictions = predict_paths(classifier, [synthetic.root / r.relative_path for r in val])

    assert classifier.class_names == ["car", "person"]
    for prediction in predictions:
        assert sum(prediction.probabilities.values()) == pytest.approx(1.0, abs=1e-5)
    correct = sum(p.label == r.category_name for p, r in zip(predictions, val, strict=True))
    assert correct / len(val) >= 0.8, "the synthetic classes are trivially separable"


def test_reloaded_model_preprocesses_exactly_like_validation_and_test(
    synthetic, tmp_path, mlflow_tracking
) -> None:
    # T3-4.2 mutation "wrong-preprocessing" survived the suite before this test existed.
    outcome = _train(synthetic, tmp_path, max_epochs=1)
    classifier = load_checkpoint(outcome.checkpoint_path)
    record = split_records(synthetic.manifest, "val")[0]
    with Image.open(synthetic.root / record.relative_path) as image:
        rgb = image.convert("RGB")

    reloaded = classifier.transform(rgb)
    evaluated = eval_transform(classifier.config.image_size)(rgb)

    assert list(reloaded.shape[-2:]) == classifier.checkpoint["preprocessing"]["resize"]
    assert torch.equal(reloaded, evaluated)


def test_an_empty_or_foreign_checkpoint_is_refused(tmp_path) -> None:
    empty = tmp_path / "empty.pt"
    empty.write_bytes(b"")

    with pytest.raises(CheckpointError):
        load_checkpoint(empty)


def test_auto_device_and_explicit_cpu_resolve() -> None:
    import torch

    from dataset_quality.classifier.training import resolve_device

    assert resolve_device("cpu").type == "cpu"
    assert resolve_device("auto").type == ("cuda" if torch.cuda.is_available() else "cpu")


def test_gpu_training_saves_a_cpu_loadable_checkpoint(synthetic, tmp_path, mlflow_tracking) -> None:
    import torch

    if not torch.cuda.is_available():
        pytest.skip("no CUDA device on this machine")
    outcome = train(
        tiny_config(max_epochs=2),
        manifest_path=synthetic.manifest_path,
        data_root=synthetic.root,
        output_root=tmp_path / "runs",
        pipeline_root=synthetic.root,
        experiment_name="test-exp",
        run_name="gpu",
        device="cuda",
    )
    run = MlflowClient().get_run(outcome.run_id)
    checkpoint = torch.load(outcome.checkpoint_path, map_location="cpu", weights_only=True)

    assert run.data.params["device"] == "cuda"
    assert all(t.device.type == "cpu" for t in checkpoint["state_dict"].values())
    assert load_checkpoint(outcome.checkpoint_path).class_names == ["car", "person"]


def test_a_max_epochs_change_that_never_bites_is_not_a_new_valid_run(
    synthetic, tmp_path, mlflow_tracking
) -> None:
    """Early stopping at epoch 2 makes max_epochs 3 vs 5 produce bit-identical weights."""

    from dataset_quality.classifier.experiments import valid_runs

    stop_early = {"monitor": "val_loss", "patience": 1, "min_delta": 1.0}
    first = _train(synthetic, tmp_path, max_epochs=3, early_stopping=stop_early)
    second = _train(synthetic, tmp_path, max_epochs=5, early_stopping=stop_early)
    rows = {
        row["run_id"]: row
        for row in valid_runs(
            MlflowClient(), "test-exp", outcome_manifest_sha(synthetic), ["car", "person"]
        )
    }

    assert rows[first.run_id]["valid"] is True
    assert rows[second.run_id]["valid"] is False
    assert rows[second.run_id]["invalid_reasons"][0].startswith("identical final weights")
