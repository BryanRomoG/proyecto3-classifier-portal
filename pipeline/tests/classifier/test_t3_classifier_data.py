"""T3-2.1 / M3: manifest isolation, sealed test split, train-only augmentation, seeded order."""

from __future__ import annotations

import pytest
import torch

from dataset_quality.classifier.data import (
    ManifestIntegrityError,
    SealedTestSplitError,
    SeededEpochSampler,
    build_datasets,
    class_names_from_manifest,
    eval_transform,
    load_manifest,
    split_records,
    verify_manifest_isolation,
)


def test_test_split_is_sealed_unless_explicitly_opened(synthetic) -> None:
    with pytest.raises(SealedTestSplitError):
        split_records(synthetic.manifest, "test")

    assert split_records(synthetic.manifest, "test", allow_test=True)


def test_training_datasets_never_contain_test_crops(synthetic) -> None:
    loaded = load_manifest(synthetic.manifest_path)
    train, val = build_datasets(
        loaded,
        class_names_from_manifest(loaded.manifest),
        synthetic.root,
        image_size=32,
        augment=True,
    )
    test_ids = {c.annotation_id for c in split_records(loaded.manifest, "test", allow_test=True)}

    used = {r.annotation_id for r in train.records} | {r.annotation_id for r in val.records}
    assert used and not used & test_ids


def _move_first_crop(manifest, source: str, target: str):
    data = manifest.model_dump(mode="json")
    sections = {s["name"]: s for s in data["splits"]}
    sections[target]["crops"].append(sections[source]["crops"][0])
    return type(manifest).model_validate(data)


def test_a_crop_in_two_splits_is_refused(synthetic) -> None:
    leaked = _move_first_crop(synthetic.manifest, "test", "train")

    with pytest.raises(ManifestIntegrityError):
        verify_manifest_isolation(leaked)


def test_an_image_in_two_splits_is_refused(synthetic) -> None:
    data = synthetic.manifest.model_dump(mode="json")
    sections = {s["name"]: s for s in data["splits"]}
    sections["val"]["image_ids"].append(sections["train"]["image_ids"][0])

    with pytest.raises(ManifestIntegrityError, match="source image"):
        verify_manifest_isolation(type(synthetic.manifest).model_validate(data))


def test_a_failed_duplicate_leakage_check_is_refused(synthetic) -> None:
    data = synthetic.manifest.model_dump(mode="json")
    data["leakage_check"].update(status="fail", leaked_pairs=1)

    with pytest.raises(ManifestIntegrityError, match="leakage_check"):
        verify_manifest_isolation(type(synthetic.manifest).model_validate(data))


def test_augmentation_only_touches_train(synthetic) -> None:
    loaded = load_manifest(synthetic.manifest_path)
    train, val = build_datasets(
        loaded,
        class_names_from_manifest(loaded.manifest),
        synthetic.root,
        image_size=32,
        augment=True,
    )
    assert train.augmented and not val.augmented

    torch.manual_seed(0)
    val_a, val_b = val[0][0], val[0][0]
    assert torch.equal(val_a, val_b), "validation preprocessing must be deterministic"

    torch.manual_seed(0)
    train_draws = [train[0][0] for _ in range(5)]
    assert any(not torch.equal(train_draws[0], d) for d in train_draws[1:])


def test_validation_and_inference_share_the_same_preprocessing(synthetic) -> None:
    from PIL import Image

    loaded = load_manifest(synthetic.manifest_path)
    _, val = build_datasets(
        loaded,
        class_names_from_manifest(loaded.manifest),
        synthetic.root,
        image_size=32,
        augment=True,
    )
    with Image.open(synthetic.root / val.records[0].relative_path) as image:
        inference_tensor = eval_transform(32)(image.convert("RGB"))

    assert torch.equal(val[0][0], inference_tensor)


def test_sampler_order_depends_only_on_seed_and_epoch() -> None:
    first, second = SeededEpochSampler(50, seed=7), SeededEpochSampler(50, seed=7)
    torch.rand(100)  # consuming the global RNG must not change the order

    assert first.order(1) == second.order(1)
    assert first.order(1) != first.order(2)
    assert first.order(1) != SeededEpochSampler(50, seed=8).order(1)
    assert sorted(first.order(3)) == list(range(50))
