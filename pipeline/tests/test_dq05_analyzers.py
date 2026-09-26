from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError

from dataset_quality.analyzers.dq05 import (
    ImageReference,
    PerceptualHashConfig,
    detect_invalid_boxes,
    find_near_duplicate_images,
)


def write_pattern(path: Path) -> None:
    image = Image.new("RGB", (240, 160), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((15, 20, 100, 120), fill="navy")
    draw.ellipse((115, 25, 210, 125), fill="gold")
    draw.line((0, 159, 239, 0), fill="crimson", width=7)
    image.save(path, format="PNG")


def test_phash_detects_exact_renamed_recompressed_and_rescaled_images(tmp_path: Path) -> None:
    original = tmp_path / "original.png"
    renamed = tmp_path / "renamed-copy.png"
    recompressed = tmp_path / "recompressed.jpg"
    rescaled = tmp_path / "rescaled.png"
    write_pattern(original)
    shutil.copyfile(original, renamed)
    with Image.open(original) as image:
        image.convert("RGB").save(recompressed, format="JPEG", quality=35)
        image.resize((120, 80), Image.Resampling.LANCZOS).save(rescaled, format="PNG")

    result = find_near_duplicate_images(
        [
            ImageReference(image_id=1, path=original),
            ImageReference(image_id=2, path=renamed),
            ImageReference(image_id=3, path=recompressed),
            ImageReference(image_id=4, path=rescaled),
        ],
        PerceptualHashConfig(max_distance=16),
    )

    pairs = {(pair.image_id_a, pair.image_id_b) for pair in result.pairs}
    assert {(1, 2), (1, 3), (1, 4)} <= pairs
    assert result.max_distance == 16
    assert all(pair.distance <= 16 for pair in result.pairs)
    assert all(0 <= pair.similarity <= 1 for pair in result.pairs)


def test_phash_threshold_is_configurable_and_bounded(tmp_path: Path) -> None:
    original = tmp_path / "original.png"
    renamed = tmp_path / "renamed-copy.png"
    write_pattern(original)
    shutil.copyfile(original, renamed)

    result = find_near_duplicate_images(
        [ImageReference(image_id=1, path=original), ImageReference(image_id=2, path=renamed)],
        PerceptualHashConfig(max_distance=0),
    )

    assert [(pair.image_id_a, pair.image_id_b, pair.distance) for pair in result.pairs] == [
        (1, 2, 0)
    ]
    with pytest.raises(ValidationError):
        PerceptualHashConfig(max_distance=65)


def test_invalid_box_detector_reports_every_required_geometry_problem() -> None:
    raw_coco = {
        "images": [{"id": 1, "file_name": "one.png", "width": 100, "height": 100}],
        "annotations": [
            {"id": 1, "image_id": 1, "category_id": 1, "bbox": [10, 10, -5, 10]},
            {"id": 2, "image_id": 1, "category_id": 1, "bbox": [10, 10, 5, -2]},
            {"id": 3, "image_id": 1, "category_id": 1, "bbox": [-1, 10, 5, 5]},
            {"id": 4, "image_id": 1, "category_id": 1, "bbox": [95, 10, 10, 10]},
            {
                "id": 5,
                "image_id": 1,
                "category_id": 1,
                "bbox": [10, 10, 10, 10],
                "area": 80,
            },
            {
                "id": 6,
                "image_id": 1,
                "category_id": 1,
                "bbox": [10, 10, 10, 10],
                "area": 100,
            },
        ],
    }

    result = detect_invalid_boxes(raw_coco)

    reasons_by_annotation = {
        issue.annotation_id: set(issue.reasons) for issue in result.invalid_boxes
    }
    assert reasons_by_annotation[1] == {"nonpositive_width"}
    assert reasons_by_annotation[2] == {"nonpositive_height"}
    assert reasons_by_annotation[3] == {"coordinate_outside_image"}
    assert reasons_by_annotation[4] == {"exceeds_image_bounds"}
    assert reasons_by_annotation[5] == {"area_mismatch"}
    assert 6 not in reasons_by_annotation
