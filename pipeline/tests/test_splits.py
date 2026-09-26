from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from dataset_quality.config.models import SplitConfig
from dataset_quality.ingestion.models import CocoAnnotation, CocoCategory, CocoDataset, CocoImage
from dataset_quality.splits.generator import _SPLIT_NAMES, generate_splits
from dataset_quality.splits.models import SplitResult

DEFAULT_CONFIG = SplitConfig(train=0.70, val=0.15, test=0.15, seed=42)


def _make_dataset(image_class_map: dict[int, list[str]]) -> CocoDataset:
    """Build a small COCO dataset from {image_id: [class_name, ...]}."""

    category_names = sorted({name for names in image_class_map.values() for name in names})
    category_id_by_name = {name: index + 1 for index, name in enumerate(category_names)}

    images = [
        CocoImage(id=image_id, file_name=f"images/img_{image_id:05d}.jpg", width=640, height=480)
        for image_id in image_class_map
    ]
    categories = [CocoCategory(id=cid, name=name) for name, cid in category_id_by_name.items()]

    annotations = []
    next_id = 1
    for image_id, class_names in image_class_map.items():
        for name in class_names:
            annotations.append(
                CocoAnnotation(
                    id=next_id,
                    image_id=image_id,
                    category_id=category_id_by_name[name],
                    bbox=[10, 10, 20, 20],
                )
            )
            next_id += 1

    return CocoDataset(images=images, annotations=annotations, categories=categories)


def _balanced_dataset(total_images: int = 60) -> CocoDataset:
    """car / bicycle / traffic_light spread across ``total_images`` images."""

    image_class_map: dict[int, list[str]] = {}
    for image_id in range(1, total_images + 1):
        classes = []
        if image_id % 2 == 0:
            classes.append("car")
        if image_id % 3 == 0:
            classes.append("bicycle")
        if image_id % 5 == 0:
            classes.append("traffic_light")
        if not classes:
            classes.append("car")
        image_class_map[image_id] = classes
    return _make_dataset(image_class_map)


def test_generates_train_validation_and_test_splits() -> None:
    result = generate_splits(_balanced_dataset(), DEFAULT_CONFIG, "v-test")

    assert result.assignment["train"]
    assert result.assignment["val"]
    assert result.assignment["test"]


def test_split_counts_sum_to_total_images() -> None:
    dataset = _balanced_dataset(60)
    result = generate_splits(dataset, DEFAULT_CONFIG, "v-test")

    totals = result.report.totals
    assert totals.images == 60
    assert totals.train + totals.val + totals.test == 60
    assert len(result.assignment["train"]) == totals.train
    assert len(result.assignment["val"]) == totals.val
    assert len(result.assignment["test"]) == totals.test


def test_ratios_are_configurable_and_respected_within_tolerance() -> None:
    dataset = _balanced_dataset(200)
    config = SplitConfig(train=0.60, val=0.20, test=0.20, seed=7)

    result = generate_splits(dataset, config, "v-test", tolerance=0.03)

    total = result.report.totals.images
    for split_name, target_proportion in (("train", 0.60), ("val", 0.20), ("test", 0.20)):
        achieved = getattr(result.report.totals, split_name) / total
        assert abs(achieved - target_proportion) <= 0.03


def test_seed_is_configurable_field_on_split_config() -> None:
    config = SplitConfig(train=0.7, val=0.15, test=0.15, seed=123)
    assert config.seed == 123

    result = generate_splits(_balanced_dataset(30), config, "v-test")
    assert result.report.seed == 123


def test_all_classes_appear_in_validation_and_test_splits() -> None:
    dataset = _balanced_dataset(90)
    result = generate_splits(dataset, DEFAULT_CONFIG, "v-test")

    for split_name in ("val", "test"):
        distribution = getattr(result.report.class_distribution, split_name)
        for category in dataset.categories:
            assert distribution.get(category.name, 0) > 0, (
                f"{category.name} is missing from the {split_name} split"
            )


def test_same_seed_produces_identical_image_id_assignments() -> None:
    dataset = _balanced_dataset(80)

    first = generate_splits(dataset, DEFAULT_CONFIG, "v-test")
    second = generate_splits(dataset, DEFAULT_CONFIG, "v-test")

    assert first.assignment == second.assignment
    assert first.report.reproducibility_check.status == "pass"


def test_different_seeds_can_produce_different_assignments() -> None:
    dataset = _balanced_dataset(80)

    first = generate_splits(dataset, SplitConfig(train=0.7, val=0.15, test=0.15, seed=1), "v-test")
    second = generate_splits(dataset, SplitConfig(train=0.7, val=0.15, test=0.15, seed=2), "v-test")

    assert first.assignment != second.assignment


def test_near_duplicate_pairs_are_kept_in_the_same_split() -> None:
    dataset = _balanced_dataset(80)
    duplicate_pairs = [(2, 4)]

    result = generate_splits(dataset, DEFAULT_CONFIG, "v-test", duplicate_pairs=duplicate_pairs)

    split_of = {
        image_id: split_name
        for split_name, image_ids in result.assignment.items()
        for image_id in image_ids
    }
    assert split_of[2] == split_of[4]
    assert result.report.leakage_check.leaked_pairs == 0
    assert result.report.leakage_check.near_duplicate_pairs_checked == 1
    assert result.report.leakage_check.near_duplicate_pairs_same_split == 1
    assert result.report.leakage_check.status == "pass"


def test_generate_splits_rejects_duplicate_pair_with_unknown_image_id() -> None:
    dataset = _balanced_dataset(10)

    with pytest.raises(ValueError, match="unknown image_id"):
        generate_splits(dataset, DEFAULT_CONFIG, "v-test", duplicate_pairs=[(1, 9999)])


def test_report_round_trips_through_json_like_the_pipeline_serializes_it() -> None:
    dataset = _balanced_dataset(60)
    result = generate_splits(dataset, DEFAULT_CONFIG, "v-test")

    payload = json.loads(result.report.model_dump_json())
    revalidated = SplitResult.model_validate(payload)

    assert revalidated == result.report


def test_split_result_rejects_fields_outside_the_contract() -> None:
    dataset = _balanced_dataset(20)
    result = generate_splits(dataset, DEFAULT_CONFIG, "v-test")
    payload = json.loads(result.report.model_dump_json())
    payload["_note"] = "not part of the contract"

    with pytest.raises(ValidationError, match="_note"):
        SplitResult.model_validate(payload)


def test_versioned_splits_contract_example_validates_with_pydantic() -> None:
    project_root = Path(os.environ.get("PROJECT_ROOT", Path(__file__).parents[2]))
    contract_path = project_root / "contracts" / "splits.json"
    payload = json.loads(contract_path.read_text(encoding="utf-8"))

    report = SplitResult.model_validate(payload)

    assert report.seed == 42
    assert report.leakage_check.status == "pass"
    assert report.reproducibility_check.status == "pass"


# ---------------------------------------------------------------------------
# Review fix (Mau, PR #34): the assignment only balanced *total* image count,
# so a minority class could end up lopsided across splits even while overall
# totals looked fine, and the coverage-completion phase could move a group
# between val/test in a way that dropped a class a split already had. These
# tests cover per-class stratification and coverage-safety directly, with
# minority classes and multilabel images (an image carrying more than one
# class at once).
# ---------------------------------------------------------------------------


def test_splits_are_stratified_by_class_not_just_overall_totals() -> None:
    """A minority class's own train/val/test proportions must track the
    configured ratios, not just the overall image totals.

    seed=18 is not cherry-picked to look nice — it's a seed under which the
    old, total-count-only balancing visibly failed this (train/val/test
    bicycle counts of 18/1/1 against a 14/3/3 target), while still passing
    the pre-existing "totals only" tests. The fix targets each class's own
    deficit, so it hits 14/3/3 regardless of seed.
    """
    image_class_map = {
        image_id: (["bicycle"] if image_id <= 20 else ["car"]) for image_id in range(1, 101)
    }
    dataset = _make_dataset(image_class_map)
    config = SplitConfig(train=0.70, val=0.15, test=0.15, seed=18)

    result = generate_splits(dataset, config, "v-test")

    bicycle_by_split = {
        split_name: getattr(result.report.class_distribution, split_name).get("bicycle", 0)
        for split_name in _SPLIT_NAMES
    }
    assert sum(bicycle_by_split.values()) == 20
    # 70/15/15 of 20 minority images -> 14/3/3, allow slack for integer/group rounding.
    for split_name, target in (("train", 14), ("val", 3), ("test", 3)):
        assert abs(bicycle_by_split[split_name] - target) <= 2, bicycle_by_split


def test_multilabel_images_are_stratified_per_class_even_when_categories_overlap() -> None:
    """An image can carry more than one class; each class's proportions must
    still land close to the configured ratios despite the overlap.

    seed=32 is, again, a seed the old total-count-only balancing visibly
    mishandled (bicycle landed 10/4/6 against a 14/3/3 target).
    """
    image_class_map: dict[int, list[str]] = {}
    for image_id in range(1, 101):
        classes = ["car"]
        if image_id <= 20:
            classes.append("bicycle")
        if image_id <= 10:
            classes.append("truck")
        image_class_map[image_id] = classes
    dataset = _make_dataset(image_class_map)
    config = SplitConfig(train=0.70, val=0.15, test=0.15, seed=32)

    result = generate_splits(dataset, config, "v-test")

    for class_name, total in (("bicycle", 20), ("truck", 10)):
        by_split = {
            split_name: getattr(result.report.class_distribution, split_name).get(class_name, 0)
            for split_name in _SPLIT_NAMES
        }
        assert sum(by_split.values()) == total, (class_name, by_split)
        for split_name, ratio in (("train", 0.70), ("val", 0.15), ("test", 0.15)):
            target = ratio * total
            assert abs(by_split[split_name] - target) <= 2, (class_name, split_name, by_split)


def test_coverage_fill_does_not_drop_a_class_a_split_already_had() -> None:
    """A multilabel group is the *only* carrier of two rare classes and is
    already covering both in val. Filling test's coverage for either class
    must not silently un-cover val — even though there's no other group left
    to give test that same coverage (a genuine data-scarcity limit, not a
    bug: val, filled first, keeps what it already had)."""
    from dataset_quality.splits.generator import _fill_class_coverage_gaps

    dataset = _make_dataset({101: ["bicycle", "truck"], 102: ["car"]})
    category_id = {category.name: category.id for category in dataset.categories}
    groups = {1: [101], 2: [102]}
    image_categories = {
        101: {category_id["bicycle"], category_id["truck"]},
        102: {category_id["car"]},
    }
    assignment = {"train": [102], "val": [101], "test": []}
    group_split = {1: "val", 2: "train"}

    _fill_class_coverage_gaps(groups, group_split, assignment, image_categories, dataset)

    assert 101 in assignment["val"]
    assert 101 not in assignment["test"]


def test_coverage_fill_still_covers_both_val_and_test_when_a_safe_donor_exists() -> None:
    """Unlike the scarcity case above, two independent groups carry the rare
    class here, both still sitting in train (always a safe donor) — so both
    val and test can get their own, without touching each other."""
    from dataset_quality.splits.generator import _fill_class_coverage_gaps

    dataset = _make_dataset({101: ["bicycle"], 102: ["bicycle"], 103: ["car"]})
    category_id = {category.name: category.id for category in dataset.categories}
    groups = {1: [101], 2: [102], 3: [103]}
    image_categories = {
        101: {category_id["bicycle"]},
        102: {category_id["bicycle"]},
        103: {category_id["car"]},
    }
    assignment = {"train": [101, 102, 103], "val": [], "test": []}
    group_split = {1: "train", 2: "train", 3: "train"}

    _fill_class_coverage_gaps(groups, group_split, assignment, image_categories, dataset)

    assert any(image_id in assignment["val"] for image_id in (101, 102))
    assert any(image_id in assignment["test"] for image_id in (101, 102))
