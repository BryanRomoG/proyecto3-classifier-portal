import pytest
from pydantic import ValidationError

from dataset_quality.ingestion.models import CocoAnnotation, CocoCategory, CocoDataset, CocoImage


def valid_image() -> CocoImage:
    return CocoImage(id=1, file_name="images/street.jpg", width=1280, height=720)


def valid_category() -> CocoCategory:
    return CocoCategory(id=1, name="car")


def test_annotation_rejects_bbox_with_only_three_values() -> None:
    with pytest.raises(ValidationError) as error:
        CocoAnnotation(id=1, image_id=1, category_id=1, bbox=[10, 20, 30])

    assert "bbox" in str(error.value)


def test_dataset_rejects_annotation_with_unknown_category_id() -> None:
    with pytest.raises(ValidationError) as error:
        CocoDataset(
            images=[valid_image()],
            categories=[valid_category()],
            annotations=[CocoAnnotation(id=1, image_id=1, category_id=999, bbox=[10, 20, 30, 40])],
        )

    assert "category_id" in str(error.value)


def test_dataset_rejects_annotation_with_orphan_image_id() -> None:
    with pytest.raises(ValidationError) as error:
        CocoDataset(
            images=[valid_image()],
            categories=[valid_category()],
            annotations=[CocoAnnotation(id=1, image_id=999, category_id=1, bbox=[10, 20, 30, 40])],
        )

    assert "image_id" in str(error.value)
