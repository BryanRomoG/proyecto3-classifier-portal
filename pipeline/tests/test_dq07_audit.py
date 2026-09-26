"""DQ-07: Unit tests for independent dataset audit engine (issue #32)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from dataset_quality.analyzers.dq07_audit import (
    audit_class_imbalance,
    audit_invalid_boxes,
    audit_small_objects,
    audit_transitive_duplicate_groups,
    collapse_duplicates_per_class,
    image_references_from_coco,
    run_independent_audit,
)


def test_transitive_duplicate_grouping_and_class_collapse() -> None:
    """A-B and B-C must collapse into one group {A, B, C} preserving class evidence."""
    pairs = [(1, 2), (2, 3), (10, 11)]
    groups = audit_transitive_duplicate_groups(pairs)

    # Must produce 2 groups: {1, 2, 3} and {10, 11}
    group_sets = [set(g) for g in groups]
    assert {1, 2, 3} in group_sets
    assert {10, 11} in group_sets
    assert len(group_sets) == 2

    # Image classes:
    # 1: person
    # 2: car
    # 3: person
    # 10: car
    # 11: car
    # 20: person (independent image)
    valid_images = {
        "person": {1, 3, 20},
        "car": {2, 10, 11},
    }

    collapsed_counts, redundant_removed = collapse_duplicates_per_class(valid_images, groups)

    # For {1, 2, 3}: group representative has both person (from 1,3) and car (from 2)
    # plus independent image 20 -> person has 2 distinct collapsed images
    assert collapsed_counts["person"] == 2

    # For car: group {1, 2, 3} has 1, group {10, 11} has 1 -> car has 2 distinct collapsed images
    assert collapsed_counts["car"] == 2

    # Redundant images removed: (3-1) + (2-1) = 3
    assert redundant_removed == 3


def test_audit_invalid_boxes_independent_detection() -> None:
    """Detects negative dimensions, out of bounds, and area mismatch independently."""
    raw = {
        "images": [{"id": 1, "width": 100, "height": 100}],
        "annotations": [
            {"id": 1, "image_id": 1, "bbox": [10, 10, -5, 20], "area": 0},  # negative width
            {"id": 2, "image_id": 1, "bbox": [10, 10, 20, 0], "area": 0},  # nonpositive height
            {"id": 3, "image_id": 1, "bbox": [-10, 10, 20, 20], "area": 400},  # negative coord
            {"id": 4, "image_id": 1, "bbox": [90, 90, 20, 20], "area": 400},  # exceeds bounds
            {"id": 5, "image_id": 1, "bbox": [10, 10, 20, 20], "area": 999},  # area mismatch
            {"id": 6, "image_id": 1, "bbox": [10, 10, 20, 20], "area": 400},  # valid
        ],
    }

    invalid_ids, issues = audit_invalid_boxes(raw)
    assert invalid_ids == {1, 2, 3, 4, 5}
    assert len(issues) == 5


def test_audit_small_objects_and_imbalance() -> None:
    """Computes small objects percentage and class imbalance ratio independently."""
    raw = {
        "annotations": [
            {"id": 1, "bbox": [0, 0, 10, 10]},  # small (10x10 <= 32x32)
            {"id": 2, "bbox": [0, 0, 32, 32]},  # small (32x32 <= 32x32)
            {"id": 3, "bbox": [0, 0, 50, 50]},  # large
            {"id": 4, "bbox": [0, 0, 5, 5]},  # excluded by caller
        ]
    }

    small_count, small_pct = audit_small_objects(
        raw, excluded_ann_ids={4}, max_width=32, max_height=32
    )
    assert small_count == 2
    assert small_pct == (2 / 3 * 100.0)

    ratio, maj, mino = audit_class_imbalance({"person": 300, "car": 150})
    assert ratio == 2.0
    assert maj == "person"
    assert mino == "car"


def test_run_independent_audit_cross_checks_with_production(tmp_path: Path) -> None:
    """Full independent audit runs and reports 0 discrepancies against production analyzers."""
    coco_path = tmp_path / "sample_coco.json"
    coco_content = {
        "images": [
            {"id": 1, "file_name": "one.jpg", "width": 100, "height": 100},
            {"id": 2, "file_name": "two.jpg", "width": 100, "height": 100},
        ],
        "categories": [
            {"id": 1, "name": "person"},
            {"id": 2, "name": "car"},
        ],
        "annotations": [
            {"id": 1, "image_id": 1, "category_id": 1, "bbox": [10, 10, 20, 20], "area": 400},
            {"id": 2, "image_id": 2, "category_id": 2, "bbox": [20, 20, 50, 50], "area": 2500},
        ],
    }
    coco_path.write_text(json.dumps(coco_content), encoding="utf-8")

    report = run_independent_audit(
        source_path=coco_path,
        target_classes=["person", "car"],
        min_images_per_class=1,
    )

    assert report.total_images == 2
    assert report.total_annotations == 2
    assert report.invalid_boxes_count == 0
    assert report.small_objects_count == 1  # 20x20 is small
    assert report.m3_passes_before_collapse is True
    assert report.discrepancies == []


def test_run_independent_audit_excludes_raw_invalid_boxes_before_production_cross_check(
    tmp_path: Path,
) -> None:
    """The audit must handle raw invalid boxes without strict Pydantic aborting it."""

    coco_path = tmp_path / "invalid_box_coco.json"
    coco_path.write_text(
        json.dumps(
            {
                "images": [
                    {"id": 1, "file_name": "one.jpg", "width": 100, "height": 100},
                    {"id": 2, "file_name": "two.jpg", "width": 100, "height": 100},
                ],
                "categories": [
                    {"id": 1, "name": "person"},
                    {"id": 2, "name": "car"},
                ],
                "annotations": [
                    {"id": 1, "image_id": 1, "category_id": 1, "bbox": [10, 10, 20, 20]},
                    {"id": 2, "image_id": 1, "category_id": 1, "bbox": [10, 10, -1, 20]},
                    {"id": 3, "image_id": 2, "category_id": 2, "bbox": [20, 20, 20, 20]},
                ],
            }
        ),
        encoding="utf-8",
    )

    report = run_independent_audit(
        source_path=coco_path,
        target_classes=["person", "car"],
        min_images_per_class=1,
    )

    assert report.invalid_boxes_count == 1
    assert [item.valid_boxes for item in report.classes] == [1, 1]
    assert report.discrepancies == []


def test_image_references_from_coco_requires_every_referenced_file(tmp_path: Path) -> None:
    """A pHash audit must fail closed instead of silently skipping a COCO image."""
    raw_coco = {
        "images": [
            {"id": 1, "file_name": "present.png"},
            {"id": 2, "file_name": "missing.png"},
        ]
    }
    (tmp_path / "present.png").touch()

    with pytest.raises(ValueError, match="Missing 1 COCO image files"):
        image_references_from_coco(raw_coco, tmp_path)


def test_run_independent_audit_calculates_phash_pairs_from_image_root(tmp_path: Path) -> None:
    """The real-image path creates pHash pairs and feeds them to M3 collapse."""
    image_root = tmp_path / "images"
    image_root.mkdir()
    first = Image.new("RGB", (64, 64), color=(20, 80, 200))
    first.save(image_root / "first.png")
    first.save(image_root / "second.png")

    coco_path = tmp_path / "sample_coco.json"
    coco_path.write_text(
        json.dumps(
            {
                "images": [
                    {"id": 1, "file_name": "first.png", "width": 64, "height": 64},
                    {"id": 2, "file_name": "second.png", "width": 64, "height": 64},
                ],
                "categories": [
                    {"id": 1, "name": "person"},
                    {"id": 2, "name": "car"},
                ],
                "annotations": [
                    {"id": 1, "image_id": 1, "category_id": 1, "bbox": [1, 1, 20, 20]},
                    {"id": 2, "image_id": 1, "category_id": 2, "bbox": [1, 1, 20, 20]},
                    {"id": 3, "image_id": 2, "category_id": 1, "bbox": [1, 1, 20, 20]},
                    {"id": 4, "image_id": 2, "category_id": 2, "bbox": [1, 1, 20, 20]},
                ],
            }
        ),
        encoding="utf-8",
    )

    report = run_independent_audit(
        source_path=coco_path,
        target_classes=["person", "car"],
        image_root=image_root,
        min_images_per_class=1,
    )

    assert report.duplicate_pairs_count == 1
    assert [(pair.image_id_a, pair.image_id_b) for pair in report.duplicate_pairs] == [(1, 2)]
    assert report.collapsed_redundant_images_count == 1
    assert report.classes[0].distinct_images_valid_after_collapse == 1
