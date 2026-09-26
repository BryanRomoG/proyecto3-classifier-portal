"""Small-object and class-imbalance analyzers for validated COCO datasets."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from dataset_quality.ingestion.models import CocoCategory, CocoDataset


class SmallObjectsConfig(BaseModel):
    """Geometry and sample limits used by the small-object analyzer."""

    model_config = ConfigDict(extra="forbid")

    max_width: float = Field(default=32, gt=0)
    max_height: float = Field(default=32, gt=0)
    sample_limit: int = Field(default=10, ge=0)


class SmallObjectSample(BaseModel):
    """One valid annotation that is within the configured small-object limits."""

    annotation_id: int
    image_id: int
    category: str = Field(min_length=1)
    bbox: list[float] = Field(min_length=4, max_length=4)


class SmallObjectsResult(BaseModel):
    """Metrics and representative annotations for objects considered small."""

    valid_annotations: int = Field(ge=0)
    small_objects: int = Field(ge=0)
    percentage: float = Field(ge=0, le=100)
    most_affected_class: str | None = None
    offending_samples: list[SmallObjectSample]


class ClassImbalanceConfig(BaseModel):
    """Minimum number of distinct annotated images required per category."""

    model_config = ConfigDict(extra="forbid")

    min_images_per_class: int = Field(default=300, ge=1)


class ClassImbalanceResult(BaseModel):
    """Distinct-image coverage and class-imbalance metrics."""

    images_per_class: dict[str, int]
    majority_class: str | None = None
    majority_count: int | None = Field(default=None, ge=0)
    minority_class: str | None = None
    minority_count: int | None = Field(default=None, ge=0)
    imbalance_ratio: float | None = Field(default=None, ge=1)
    classes_below_minimum: list[str]


def analyze_small_objects(
    dataset: CocoDataset, config: SmallObjectsConfig | None = None
) -> SmallObjectsResult:
    """Measure valid COCO boxes whose width and height fit the configured geometry."""

    policy = config or SmallObjectsConfig()
    images_by_id = {image.id: image for image in dataset.images}
    categories_by_id = {category.id: category.name for category in dataset.categories}
    valid_annotations = 0
    small_by_category = {category.id: 0 for category in dataset.categories}
    samples: list[SmallObjectSample] = []

    for annotation in dataset.annotations:
        image = images_by_id[annotation.image_id]
        box = annotation.bbox.root
        if not _is_box_inside_image(box, image.width, image.height):
            continue

        valid_annotations += 1
        _, _, width, height = box
        if width > policy.max_width or height > policy.max_height:
            continue

        small_by_category[annotation.category_id] += 1
        if len(samples) < policy.sample_limit:
            samples.append(
                SmallObjectSample(
                    annotation_id=annotation.id,
                    image_id=annotation.image_id,
                    category=categories_by_id[annotation.category_id],
                    bbox=list(box),
                )
            )

    small_objects = sum(small_by_category.values())
    percentage = 0.0 if valid_annotations == 0 else small_objects / valid_annotations * 100
    most_affected_class = _most_affected_class(dataset, small_by_category)
    return SmallObjectsResult(
        valid_annotations=valid_annotations,
        small_objects=small_objects,
        percentage=percentage,
        most_affected_class=most_affected_class,
        offending_samples=samples,
    )


def analyze_class_imbalance(
    dataset: CocoDataset, config: ClassImbalanceConfig | None = None
) -> ClassImbalanceResult:
    """Count distinct valid-image coverage by category and calculate its active-class ratio."""

    policy = config or ClassImbalanceConfig()
    images_by_id = {image.id: image for image in dataset.images}
    image_ids_by_category = {category.id: set[int]() for category in dataset.categories}

    for annotation in dataset.annotations:
        image = images_by_id[annotation.image_id]
        if _is_box_inside_image(annotation.bbox.root, image.width, image.height):
            image_ids_by_category[annotation.category_id].add(annotation.image_id)

    images_per_class = {
        category.name: len(image_ids_by_category[category.id]) for category in dataset.categories
    }
    image_counts_by_category = {
        category.id: len(image_ids_by_category[category.id]) for category in dataset.categories
    }
    active_categories = [
        category for category in dataset.categories if image_ids_by_category[category.id]
    ]
    majority = _category_with_extreme_count(
        active_categories, image_counts_by_category, largest=True
    )
    minority = (
        _category_with_extreme_count(active_categories, image_counts_by_category, largest=False)
        if len(active_categories) >= 2
        else None
    )
    majority_count = len(image_ids_by_category[majority.id]) if majority is not None else None
    minority_count = len(image_ids_by_category[minority.id]) if minority is not None else None
    ratio = (
        majority_count / minority_count
        if majority_count is not None and minority_count is not None
        else None
    )
    below_minimum = [
        category.name
        for category in dataset.categories
        if len(image_ids_by_category[category.id]) < policy.min_images_per_class
    ]
    return ClassImbalanceResult(
        images_per_class=images_per_class,
        majority_class=majority.name if majority is not None else None,
        majority_count=majority_count,
        minority_class=minority.name if minority is not None else None,
        minority_count=minority_count,
        imbalance_ratio=ratio,
        classes_below_minimum=below_minimum,
    )


def _most_affected_class(dataset: CocoDataset, small_by_category: dict[int, int]) -> str | None:
    """Return the first category in COCO order with the largest nonzero small-box count."""

    affected = [category for category in dataset.categories if small_by_category[category.id] > 0]
    if not affected:
        return None
    return _category_with_extreme_count(affected, small_by_category, largest=True).name


def _category_with_extreme_count(
    categories: list[CocoCategory], counts: dict[int, int], *, largest: bool
) -> CocoCategory:
    """Choose a category deterministically, keeping COCO order when counts tie."""

    selected = categories[0]
    for category in categories[1:]:
        if largest and counts[category.id] > counts[selected.id]:
            selected = category
        if not largest and counts[category.id] < counts[selected.id]:
            selected = category
    return selected


def _is_box_inside_image(box: Iterable[float], image_width: int, image_height: int) -> bool:
    """Return whether a valid COCO box remains within its referenced image."""

    x, y, width, height = box
    return x + width <= image_width and y + height <= image_height
