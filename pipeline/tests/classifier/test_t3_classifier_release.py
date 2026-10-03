"""T3-3.6 contract: a real torch checkpoint packages, reloads and infers from the package.

The torch-free logic tests live in ``tests/test_t3_3_6_release.py``. Here a real
``simple_cnn`` checkpoint is written with ``torch.save`` and driven through the *real*
``release.read_checkpoint`` (which reuses ``predict.load_checkpoint``), so the package is
proven to contain weights a clean machine can actually load and run.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import torch
from tests_classifier_helpers import tiny_config

from dataset_quality.classifier import release
from dataset_quality.classifier.data import preprocessing_spec
from dataset_quality.classifier.model import build_model, describe_weights
from dataset_quality.classifier.predict import load_checkpoint, predict_paths
from dataset_quality.classifier.training import CHECKPOINT_FORMAT, CHECKPOINT_NAME

RUN_ID = "44725ac6b1704fed8b06bc4f846651d8"
MANIFEST_SHA256 = "a" * 64
CLASSES = ["car", "person"]


def _write_checkpoint(path: Path, config) -> None:
    torch.manual_seed(0)
    model = build_model(config, len(CLASSES), load_pretrained=False)
    torch.save(
        {
            "format": CHECKPOINT_FORMAT,
            "run_id": RUN_ID,
            "state_dict": {k: v.detach().cpu() for k, v in model.state_dict().items()},
            "config": config.model_dump(mode="json"),
            "class_names": list(CLASSES),
            "preprocessing": preprocessing_spec(config.image_size),
            "best_epoch": 2,
            "monitor": config.early_stopping.monitor,
            "best_value": 0.5,
            "weights": describe_weights(config, model),
            "lineage": {
                "dataset_version": "v-test",
                "manifest_sha256": MANIFEST_SHA256,
                "dvc_raw_md5": "b" * 32,
                "quality_gate_status": "pass",
                "coco_sha256": "c" * 64,
            },
        },
        path,
    )


def _write_reports(tmp_path: Path, checkpoint_sha256: str) -> tuple[Path, Path]:
    selection = {
        "run_id": RUN_ID,
        "run_name": "r03-adamw-lr1e-4",
        "experiment_name": "t3-classifier",
        "checkpoint_sha256": checkpoint_sha256,
        "manifest_sha256": MANIFEST_SHA256,
        "classes": list(CLASSES),
        "selected_at": "2026-09-30T14:48:58+00:00",
        "selected_metric_value": 0.98,
        "policy": {"metric": "best_val_accuracy", "mode": "max"},
    }
    evaluation = {
        "run_id": RUN_ID,
        "checkpoint_sha256": checkpoint_sha256,
        "manifest_sha256": MANIFEST_SHA256,
        "dataset_version": "v-test",
        "classes": list(CLASSES),
        "total": 10,
        "correct": 9,
        "accuracy": 0.9,
        "macro_f1": 0.9,
        "per_class": {
            name: {"precision": 0.9, "recall": 0.9, "f1": 0.9, "support": 5} for name in CLASSES
        },
        "confusion_matrix": {
            "labels": list(CLASSES),
            "matrix": [[5, 0], [1, 4]],
            "rows": "true",
            "columns": "predicted",
        },
        "majority_baseline": {
            "class": "car",
            "accuracy": 0.5,
            "correct": 5,
            "chosen_from": "train split label frequency",
        },
        "most_confused": {"true": "person", "predicted": "car", "count": 1},
        "meets_target": True,
        "target_accuracy": 0.85,
        "evaluated_at": "2026-09-30T14:49:23+00:00",
    }
    selection_path = tmp_path / "selection.json"
    evaluation_path = tmp_path / "test_evaluation.json"
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    evaluation_path.write_text(json.dumps(evaluation), encoding="utf-8")
    return selection_path, evaluation_path


def _first_train_crop(synthetic) -> Path:
    train = next(section for section in synthetic.manifest.splits if section.name == "train")
    return synthetic.root / train.crops[0].relative_path


def test_release_packages_a_real_checkpoint_and_infers_from_it(synthetic, tmp_path) -> None:
    config = tiny_config()
    checkpoint = tmp_path / "selected.pt"
    _write_checkpoint(checkpoint, config)
    sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    selection_path, evaluation_path = _write_reports(tmp_path, sha)

    result = release.build_package(
        checkpoint=checkpoint,
        version="v1.0.0",
        selection_path=selection_path,
        evaluation_path=evaluation_path,
        output_dir=tmp_path / "release",
    )

    package_dir = Path(result["package_dir"])
    assert release.verify_package(package_dir)["ok"] is True
    assert json.loads((package_dir / release.CLASS_MAP_FILE).read_text("utf-8")) == {
        "0": "car",
        "1": "person",
    }
    assert json.loads((package_dir / release.CONFIG_FILE).read_text("utf-8")) == config.model_dump(
        mode="json"
    )

    # Clean-machine inference: reload the packaged weights through the inference loader.
    loaded = load_checkpoint(package_dir / release.MODEL_FILE)
    assert loaded.class_names == CLASSES
    predictions = predict_paths(loaded, [_first_train_crop(synthetic)])
    assert predictions[0].label in CLASSES


def test_release_refuses_a_real_checkpoint_that_is_not_the_selected_one(
    synthetic, tmp_path
) -> None:
    checkpoint = tmp_path / "selected.pt"
    _write_checkpoint(checkpoint, tiny_config())
    selection_path, evaluation_path = _write_reports(tmp_path, "f" * 64)

    with pytest.raises(release.ReleaseError, match="does not match the one recorded"):
        release.build_package(
            checkpoint=checkpoint,
            version="v1.0.0",
            selection_path=selection_path,
            evaluation_path=evaluation_path,
            output_dir=tmp_path / "release",
        )


def test_release_constants_track_training() -> None:
    assert release.MODEL_FILE == CHECKPOINT_NAME
