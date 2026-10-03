"""T3-3.6: packaging the selected candidate and publishing/verifying it in the releases bucket.

These tests exercise the deterministic build, the SHA-256 integrity manifest, the refusal of
anything that is not the selected/test-evaluated checkpoint, and the upload/fetch round trip.
They deliberately inject a fake ``checkpoint_reader`` and an in-memory object store, so they
run without torch, MLflow, network or AWS — a separate contract test
(``tests/classifier/test_t3_classifier_release.py``) drives the real torch checkpoint path.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dataset_quality.classifier.__main__ import main as cli
from dataset_quality.classifier.release import (
    CHECKSUMS_FILE,
    CLASS_MAP_FILE,
    CONFIG_FILE,
    METADATA_FILE,
    MODEL_CARD_FILE,
    MODEL_FILE,
    PACKAGE_FILES,
    CheckpointFacts,
    ReleaseError,
    build_package,
    fetch_package,
    package_key,
    parse_semver,
    upload_package,
    verify_package,
)

RUN_ID = "44725ac6b1704fed8b06bc4f846651d8"
MANIFEST_SHA256 = "394743403f8a263b462687b733272e9993d7dddaea6a1229f8ee2896b82f3f7d"
DVC_MD5 = "0ac4ecdbbd5a9b3144624ec86009b9e7"

CONFIG = {
    "optimizer": "adamw",
    "batch_size": 32,
    "max_epochs": 15,
    "learning_rate": 1e-4,
    "image_size": 128,
    "hidden_layers": [256],
    "dropout": 0.3,
}
LINEAGE = {
    "dataset_version": "v1.0.0",
    "manifest_sha256": MANIFEST_SHA256,
    "dvc_raw_md5": DVC_MD5,
    "quality_gate_status": "pass",
    "coco_sha256": "a" * 64,
}
WEIGHTS = {
    "architecture": "resnet18",
    "initial_weights": "from scratch (random init, seeds.init)",
    "trainable_layers": "all layers",
    "trainable_parameters": 11178378,
    "total_parameters": 11178378,
}
PREPROCESSING = {
    "resize": [128, 128],
    "color_mode": "RGB",
    "to_tensor": "scale to [0, 1]",
    "normalize_mean": [0.485, 0.456, 0.406],
    "normalize_std": [0.229, 0.224, 0.225],
}


def _reader(**overrides):
    values: dict = {
        "config": CONFIG,
        "class_names": ["car", "person"],
        "run_id": RUN_ID,
        "lineage": LINEAGE,
        "weights": WEIGHTS,
        "best_epoch": 7,
        "monitor": "val_loss",
        "best_value": 0.04,
        "preprocessing": PREPROCESSING,
    }
    values.update(overrides)
    facts = CheckpointFacts(**values)
    return lambda _path: facts


def _write_reports(
    tmp_path: Path, checkpoint_sha256: str, *, selection=None, evaluation=None
) -> tuple[Path, Path]:
    selection_doc = {
        "run_id": RUN_ID,
        "run_name": "r03-adamw-lr1e-4",
        "experiment_name": "t3-classifier",
        "checkpoint_sha256": checkpoint_sha256,
        "manifest_sha256": MANIFEST_SHA256,
        "classes": ["car", "person"],
        "selected_at": "2026-09-30T14:48:58.317648+00:00",
        "selected_metric_value": 0.9802955665024631,
        "policy": {
            "metric": "best_val_accuracy",
            "mode": "max",
            "tie_breakers": [["best_val_loss", "min"]],
            "file": "selection_policy.yaml",
        },
    }
    evaluation_doc = {
        "run_id": RUN_ID,
        "checkpoint_sha256": checkpoint_sha256,
        "manifest_sha256": MANIFEST_SHA256,
        "dataset_version": "v1.0.0",
        "classes": ["car", "person"],
        "total": 95,
        "correct": 94,
        "accuracy": 0.9894736842105263,
        "macro_f1": 0.9892400045305243,
        "per_class": {
            "car": {"precision": 0.9818, "recall": 1.0, "f1": 0.9908, "support": 54},
            "person": {"precision": 1.0, "recall": 0.9756, "f1": 0.9877, "support": 41},
        },
        "confusion_matrix": {
            "labels": ["car", "person"],
            "matrix": [[54, 0], [1, 40]],
            "rows": "true",
            "columns": "predicted",
        },
        "majority_baseline": {
            "class": "car",
            "accuracy": 0.5684210526315789,
            "correct": 54,
            "chosen_from": "train split label frequency",
        },
        "most_confused": {"true": "person", "predicted": "car", "count": 1},
        "meets_target": True,
        "target_accuracy": 0.85,
        "evaluated_at": "2026-09-30T14:49:23.191936+00:00",
    }
    selection_doc.update(selection or {})
    evaluation_doc.update(evaluation or {})
    selection_path = tmp_path / "selection.json"
    evaluation_path = tmp_path / "test_evaluation.json"
    selection_path.write_text(json.dumps(selection_doc), encoding="utf-8")
    evaluation_path.write_text(json.dumps(evaluation_doc), encoding="utf-8")
    return selection_path, evaluation_path


def _build(tmp_path: Path, *, version: str = "v1.0.0", reader=None, **report_overrides):
    checkpoint = tmp_path / "selected-model.pt"
    checkpoint.write_bytes(b"synthetic-checkpoint-bytes")
    sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    selection_path, evaluation_path = _write_reports(tmp_path, sha, **report_overrides)
    result = build_package(
        checkpoint=checkpoint,
        version=version,
        selection_path=selection_path,
        evaluation_path=evaluation_path,
        output_dir=tmp_path / "release",
        checkpoint_reader=reader or _reader(),
    )
    return result, checkpoint


class FakeObjectStore:
    """In-memory stand-in for ``ObjectStore`` (no boto3, no network)."""

    def __init__(self, bucket: str = "dataset-releases-dev-000000000000") -> None:
        self.bucket = bucket
        self.objects: dict[str, bytes] = {}

    def put_file(self, key: str, path: Path, content_type: str | None = None) -> None:
        self.objects[key] = Path(path).read_bytes()

    def download_file(self, key: str, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.objects[key])

    def head(self, key: str) -> dict:
        data = self.objects[key]
        return {"ContentLength": len(data), "ETag": '"' + hashlib.md5(data).hexdigest() + '"'}

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(key for key in self.objects if key.startswith(prefix))


# --------------------------------------------------------------------------- build


def test_build_is_deterministic(tmp_path: Path) -> None:
    first, checkpoint = _build(tmp_path)

    # Build again into a *different* tree from the same inputs: nothing ambient (a clock, a
    # set-order, an absolute path) may leak into the package.
    elsewhere = build_package(
        checkpoint=checkpoint,
        version="v1.0.0",
        selection_path=tmp_path / "selection.json",
        evaluation_path=tmp_path / "test_evaluation.json",
        output_dir=tmp_path / "elsewhere",
        checkpoint_reader=_reader(),
    )

    first_dir, second_dir = Path(first["package_dir"]), Path(elsewhere["package_dir"])
    for name in (*PACKAGE_FILES, CHECKSUMS_FILE):
        assert (first_dir / name).read_bytes() == (second_dir / name).read_bytes(), name
    assert first["checksums"] == elsewhere["checksums"]


def test_package_has_the_required_files_and_a_self_consistent_manifest(tmp_path: Path) -> None:
    result, _ = _build(tmp_path)
    package_dir = Path(result["package_dir"])

    names = {path.name for path in package_dir.iterdir()}
    assert names == set(PACKAGE_FILES) | {CHECKSUMS_FILE}

    listed = {}
    for line in (package_dir / CHECKSUMS_FILE).read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ")
        listed[name] = digest
    assert set(listed) == set(PACKAGE_FILES)
    for name, digest in listed.items():
        assert hashlib.sha256((package_dir / name).read_bytes()).hexdigest() == digest

    verification = verify_package(package_dir)
    assert verification["ok"] is True
    assert verification["mismatches"] == []


def test_model_card_is_rendered_from_the_reports(tmp_path: Path) -> None:
    result, _ = _build(tmp_path)
    card = (Path(result["package_dir"]) / MODEL_CARD_FILE).read_text(encoding="utf-8")

    assert "# Model card" in card
    assert RUN_ID in card
    assert MANIFEST_SHA256 in card
    assert "0.9895" in card  # test accuracy, 4 decimals
    assert "car" in card and "person" in card


def test_metadata_records_traceability_and_hashes(tmp_path: Path) -> None:
    result, _ = _build(tmp_path)
    package_dir = Path(result["package_dir"])
    metadata = json.loads((package_dir / METADATA_FILE).read_text("utf-8"))

    assert metadata["run_id"] == RUN_ID
    assert metadata["dataset"]["dataset_version"] == "v1.0.0"
    assert metadata["dataset"]["manifest_sha256"] == MANIFEST_SHA256
    assert metadata["dataset"]["dvc_raw_md5"] == DVC_MD5
    assert metadata["test_metrics"]["accuracy"] == 0.9894736842105263
    assert metadata["test_metrics"]["total"] == 95
    assert set(metadata["files"]) == {MODEL_FILE, CONFIG_FILE, CLASS_MAP_FILE, MODEL_CARD_FILE}
    for name, digest in metadata["files"].items():
        actual = hashlib.sha256((package_dir / name).read_bytes()).hexdigest()
        assert actual == digest


def test_config_and_class_map_come_from_the_checkpoint(tmp_path: Path) -> None:
    result, _ = _build(tmp_path)
    package_dir = Path(result["package_dir"])

    config = json.loads((package_dir / CONFIG_FILE).read_text("utf-8"))
    assert config["optimizer"] == "adamw"
    assert config["learning_rate"] == 1e-4
    assert json.loads((package_dir / CLASS_MAP_FILE).read_text("utf-8")) == {
        "0": "car",
        "1": "person",
    }


# ------------------------------------------------------------------ integrity


def test_verify_rejects_a_tampered_payload(tmp_path: Path) -> None:
    result, _ = _build(tmp_path)
    package_dir = Path(result["package_dir"])
    model = package_dir / MODEL_FILE
    model.write_bytes(model.read_bytes() + b"x")

    verification = verify_package(package_dir)

    assert verification["ok"] is False
    assert [m["name"] for m in verification["mismatches"]] == [MODEL_FILE]


def test_verify_rejects_a_missing_file(tmp_path: Path) -> None:
    result, _ = _build(tmp_path)
    package_dir = Path(result["package_dir"])
    (package_dir / CONFIG_FILE).unlink()

    verification = verify_package(package_dir)

    assert verification["ok"] is False
    assert verification["missing"] == [CONFIG_FILE]


def test_verify_rejects_an_extra_file(tmp_path: Path) -> None:
    result, _ = _build(tmp_path)
    package_dir = Path(result["package_dir"])
    (package_dir / "backdoor.py").write_text("print('nope')", encoding="utf-8")

    verification = verify_package(package_dir)

    assert verification["ok"] is False
    assert verification["unexpected"] == ["backdoor.py"]


def test_verify_reports_a_missing_manifest(tmp_path: Path) -> None:
    verification = verify_package(tmp_path / "empty")

    assert verification["ok"] is False
    assert CHECKSUMS_FILE in verification["error"]


def test_verify_rejects_manifest_paths_outside_the_package(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / CHECKSUMS_FILE).write_text(f"{'a' * 64}  ../outside.txt\n", encoding="utf-8")

    verification = verify_package(package_dir)

    assert verification["ok"] is False
    assert "invalid file name" in verification["error"]


def test_upload_refuses_package_metadata_for_a_different_version(tmp_path: Path) -> None:
    result, _ = _build(tmp_path, version="v1.0.0")
    package_dir = Path(result["package_dir"])

    with pytest.raises(ReleaseError, match="refusing to upload"):
        upload_package(store=FakeObjectStore(), package_dir=package_dir, version="v2.0.0")


# ----------------------------------------------------------------- refusals


def test_build_refuses_a_checkpoint_that_is_not_the_selected_one(tmp_path: Path) -> None:
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"a different model than the one selected")
    # Reports keep the SHA-256 of *the selected* checkpoint, which is not this file.
    selection_path, evaluation_path = _write_reports(tmp_path, "f" * 64)

    with pytest.raises(ReleaseError, match="does not match the one recorded"):
        build_package(
            checkpoint=checkpoint,
            version="v1.0.0",
            selection_path=selection_path,
            evaluation_path=evaluation_path,
            output_dir=tmp_path / "release",
            checkpoint_reader=_reader(),
        )


def test_build_refuses_a_different_run_or_manifest(tmp_path: Path) -> None:
    with pytest.raises(ReleaseError, match="different MLflow runs"):
        _build(tmp_path, selection={"run_id": "0" * 32})

    with pytest.raises(ReleaseError, match="different manifests"):
        _build(tmp_path, evaluation={"manifest_sha256": "b" * 64})


def test_build_requires_checkpoint_run_and_lineage(tmp_path: Path) -> None:
    with pytest.raises(ReleaseError, match="checkpoint run id"):
        _build(tmp_path, reader=_reader(run_id=None))

    with pytest.raises(ReleaseError, match="lineage manifest"):
        _build(tmp_path, reader=_reader(lineage={}))


def test_build_refuses_classes_that_do_not_match_the_checkpoint(tmp_path: Path) -> None:
    with pytest.raises(ReleaseError, match="selected classes"):
        _build(tmp_path, reader=_reader(class_names=["car", "person", "dog"]))


def test_build_refuses_a_non_semantic_version(tmp_path: Path) -> None:
    with pytest.raises(ReleaseError, match="MAJOR"):
        _build(tmp_path, version="1.0")


@pytest.mark.parametrize("version", ["1.0.0", "v1.0", "v1.0.0-rc1", "vX.0.0", "v1.0.0.0"])
def test_parse_semver_rejects_anything_but_major_minor_patch(version: str) -> None:
    with pytest.raises(ReleaseError):
        parse_semver(version)


def test_parse_semver_accepts_plain_major_minor_patch() -> None:
    assert parse_semver("v1.0.0") == (1, 0, 0)
    assert parse_semver("v2.11.3") == (2, 11, 3)


# --------------------------------------------------------------- upload / fetch


def test_upload_then_fetch_round_trips_and_keys_are_versioned(tmp_path: Path) -> None:
    result, _ = _build(tmp_path)
    package_dir = Path(result["package_dir"])
    store = FakeObjectStore()

    uploaded = upload_package(store=store, package_dir=package_dir, version="v1.0.0")

    assert uploaded["objects"][MODEL_FILE]["key"] == "t3-classifier/v1.0.0/model.pt"
    assert package_key("t3-classifier", "v1.0.0", CHECKSUMS_FILE) in store.objects
    assert uploaded["objects"][MODEL_FILE]["size"] == (package_dir / MODEL_FILE).stat().st_size

    fetched = fetch_package(store=store, version="v1.0.0", destination=tmp_path / "clean")

    assert fetched["ok"] is True
    downloaded = Path(fetched["destination"]) / MODEL_FILE
    assert downloaded.read_bytes() == (package_dir / MODEL_FILE).read_bytes()


def test_upload_refuses_an_invalid_package(tmp_path: Path) -> None:
    result, _ = _build(tmp_path)
    package_dir = Path(result["package_dir"])
    model = package_dir / MODEL_FILE
    model.write_bytes(model.read_bytes() + b"x")

    with pytest.raises(ReleaseError, match="refusing to upload"):
        upload_package(store=FakeObjectStore(), package_dir=package_dir, version="v1.0.0")


def test_fetch_detects_a_tampered_object(tmp_path: Path) -> None:
    result, _ = _build(tmp_path)
    store = FakeObjectStore()
    upload_package(store=store, package_dir=Path(result["package_dir"]), version="v1.0.0")
    key = package_key("t3-classifier", "v1.0.0", MODEL_FILE)
    store.objects[key] = store.objects[key] + b"x"

    fetched = fetch_package(store=store, version="v1.0.0", destination=tmp_path / "clean")

    assert fetched["ok"] is False
    assert [m["name"] for m in fetched["mismatches"]] == [MODEL_FILE]


# --------------------------------------------------------------------- CLI


def test_cli_verify_returns_success_then_failure_on_tampering(tmp_path: Path) -> None:
    result, _ = _build(tmp_path)
    package_dir = Path(result["package_dir"])

    assert cli(["release-verify", "--package-dir", str(package_dir)]) == 0

    (package_dir / MODEL_FILE).write_bytes(b"tampered")
    assert cli(["release-verify", "--package-dir", str(package_dir)]) == 2
