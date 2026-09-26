from __future__ import annotations

import pytest
from pydantic import ValidationError

from dataset_quality.analyzers.dq04 import (
    ClassImbalanceConfig,
    SmallObjectsConfig,
    analyze_class_imbalance,
    analyze_small_objects,
)
from dataset_quality.ingestion.models import CocoAnnotation, CocoCategory, CocoDataset, CocoImage


def make_dataset() -> CocoDataset:
    return CocoDataset(
        images=[
            CocoImage(id=1, file_name="one.jpg", width=100, height=100),
            CocoImage(id=2, file_name="two.jpg", width=100, height=100),
            CocoImage(id=3, file_name="three.jpg", width=100, height=100),
            CocoImage(id=4, file_name="four.jpg", width=100, height=100),
        ],
        categories=[
            CocoCategory(id=1, name="person"),
            CocoCategory(id=2, name="car"),
            CocoCategory(id=3, name="dog"),
        ],
        annotations=[
            CocoAnnotation(id=1, image_id=1, category_id=1, bbox=[0, 0, 32, 32]),
            CocoAnnotation(id=2, image_id=1, category_id=1, bbox=[40, 40, 16, 20]),
            CocoAnnotation(id=3, image_id=2, category_id=1, bbox=[10, 10, 20, 20]),
            CocoAnnotation(id=4, image_id=3, category_id=2, bbox=[10, 10, 40, 40]),
            CocoAnnotation(id=5, image_id=4, category_id=2, bbox=[90, 10, 20, 20]),
        ],
    )


def test_small_objects_uses_32px_default_and_excludes_out_of_bounds_boxes() -> None:
    result = analyze_small_objects(make_dataset())

    assert result.valid_annotations == 4
    assert result.small_objects == 3
    assert result.percentage == pytest.approx(75.0)
    assert result.most_affected_class == "person"
    assert [sample.annotation_id for sample in result.offending_samples] == [1, 2, 3]


def test_small_objects_accepts_a_custom_geometry_threshold_and_validates_it() -> None:
    result = analyze_small_objects(
        make_dataset(), SmallObjectsConfig(max_width=40, max_height=40, sample_limit=2)
    )

    assert result.small_objects == 4
    assert result.percentage == pytest.approx(100.0)
    assert [sample.annotation_id for sample in result.offending_samples] == [1, 2]

    with pytest.raises(ValidationError):
        SmallObjectsConfig(max_width=0)


def test_class_imbalance_counts_distinct_images_and_reports_absent_classes() -> None:
    result = analyze_class_imbalance(make_dataset(), ClassImbalanceConfig(min_images_per_class=3))

    assert result.images_per_class == {"person": 2, "car": 1, "dog": 0}
    assert result.majority_class == "person"
    assert result.majority_count == 2
    assert result.minority_class == "car"
    assert result.minority_count == 1
    assert result.imbalance_ratio == pytest.approx(2.0)
    assert set(result.classes_below_minimum) == {"person", "car", "dog"}


def test_class_imbalance_reports_a_missing_ratio_when_fewer_than_two_classes_are_active() -> None:
    dataset = make_dataset().model_copy(
        update={
            "annotations": [
                CocoAnnotation(id=1, image_id=1, category_id=1, bbox=[0, 0, 20, 20]),
            ]
        }
    )

    result = analyze_class_imbalance(dataset)

    assert result.majority_class == "person"
    assert result.minority_class is None
    assert result.imbalance_ratio is None
