from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataset_quality.analyzers.m3 import calculate_m3_baseline, load_coco_dataset, source_sha256
from dataset_quality.ingestion.models import CocoAnnotation, CocoCategory, CocoDataset, CocoImage


def make_dataset() -> CocoDataset:
    return CocoDataset(
        images=[
            CocoImage(id=1, file_name="one.jpg", width=100, height=100),
            CocoImage(id=2, file_name="two.jpg", width=100, height=100),
            CocoImage(id=3, file_name="three.jpg", width=100, height=100),
        ],
        categories=[
            CocoCategory(id=1, name="person"),
            CocoCategory(id=2, name="car"),
            CocoCategory(id=3, name="dog"),
        ],
        annotations=[
            CocoAnnotation(id=1, image_id=1, category_id=1, bbox=[10, 10, 20, 20]),
            CocoAnnotation(id=2, image_id=1, category_id=1, bbox=[40, 10, 20, 20]),
            CocoAnnotation(id=3, image_id=1, category_id=2, bbox=[10, 10, 20, 20]),
            CocoAnnotation(id=4, image_id=2, category_id=1, bbox=[90, 10, 20, 20]),
            CocoAnnotation(id=5, image_id=2, category_id=3, bbox=[10, 10, 20, 20]),
        ],
    )


def test_m3_counts_distinct_images_and_excludes_out_of_bounds_boxes() -> None:
    report = calculate_m3_baseline(
        make_dataset(),
        target_category_names=["person", "car"],
        source_name="official-coco.json",
        source_sha256_value="a" * 64,
    )

    counts = {result.category: result.distinct_images_with_valid_box for result in report.classes}
    assert counts == {"person": 1, "car": 1}
    assert report.valid_target_annotations == 3
    assert report.excluded_invalid_boxes == 1
    assert report.images_without_valid_target_box == 2


def test_m3_requires_two_existing_target_categories() -> None:
    with pytest.raises(ValueError, match="target categories"):
        calculate_m3_baseline(
            make_dataset(),
            target_category_names=["person", "bicycle"],
            source_name="official-coco.json",
            source_sha256_value="a" * 64,
        )


def test_load_coco_dataset_and_hash_source_file(tmp_path: Path) -> None:
    source_path = tmp_path / "coco-dataset.json"
    source_path.write_text(json.dumps(make_dataset().model_dump(mode="json")), encoding="utf-8")

    loaded = load_coco_dataset(source_path)

    assert loaded == make_dataset()
    assert len(source_sha256(source_path)) == 64
