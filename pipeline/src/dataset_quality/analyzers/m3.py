"""Reproducible M3 baseline counts for selected COCO categories."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable, Sequence
from pathlib import Path

from pydantic import BaseModel, Field

from dataset_quality.ingestion.models import CocoDataset


class M3ClassCount(BaseModel):
    """Distinct images with at least one valid box for one target category."""

    category_id: int
    category: str = Field(min_length=1)
    distinct_images_with_valid_box: int = Field(ge=0)


class M3BaselineReport(BaseModel):
    """Portable result of an M3 baseline calculation without source dataset contents."""

    source_name: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    total_images: int = Field(ge=0)
    total_annotations: int = Field(ge=0)
    valid_target_annotations: int = Field(ge=0)
    excluded_invalid_boxes: int = Field(ge=0)
    images_without_valid_target_box: int = Field(ge=0)
    classes: list[M3ClassCount] = Field(min_length=2)


def load_coco_dataset(path: Path) -> CocoDataset:
    """Load and validate a COCO JSON document with the project's Pydantic models."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("COCO source must contain a top-level JSON object")
    return CocoDataset.model_validate(payload)


def source_sha256(path: Path) -> str:
    """Return the SHA-256 digest of a source file without loading it all into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def calculate_m3_baseline(
    dataset: CocoDataset,
    target_category_names: Sequence[str],
    source_name: str,
    source_sha256_value: str,
) -> M3BaselineReport:
    """Count distinct images per selected category, excluding invalid boxes."""

    target_categories = _resolve_target_categories(dataset, target_category_names)
    target_ids = {category.id for category in target_categories}
    image_by_id = {image.id: image for image in dataset.images}
    image_ids_by_category = {category.id: set[int]() for category in target_categories}
    valid_target_annotations = 0
    excluded_invalid_boxes = 0

    for annotation in dataset.annotations:
        if annotation.category_id not in target_ids:
            continue
        image = image_by_id[annotation.image_id]
        if not _is_box_inside_image(annotation.bbox.root, image.width, image.height):
            excluded_invalid_boxes += 1
            continue
        valid_target_annotations += 1
        image_ids_by_category[annotation.category_id].add(annotation.image_id)

    images_with_valid_target_box = set().union(*image_ids_by_category.values())
    counts = [
        M3ClassCount(
            category_id=category.id,
            category=category.name,
            distinct_images_with_valid_box=len(image_ids_by_category[category.id]),
        )
        for category in target_categories
    ]
    return M3BaselineReport(
        source_name=source_name,
        source_sha256=source_sha256_value,
        total_images=len(dataset.images),
        total_annotations=len(dataset.annotations),
        valid_target_annotations=valid_target_annotations,
        excluded_invalid_boxes=excluded_invalid_boxes,
        images_without_valid_target_box=len(dataset.images) - len(images_with_valid_target_box),
        classes=counts,
    )


def _resolve_target_categories(
    dataset: CocoDataset, target_category_names: Sequence[str]
) -> list[object]:
    requested = list(target_category_names)
    if len(requested) < 2 or len(set(requested)) != len(requested):
        raise ValueError("at least two distinct target categories are required")

    categories_by_name = {category.name: category for category in dataset.categories}
    missing = [name for name in requested if name not in categories_by_name]
    if missing:
        raise ValueError(f"target categories not found: {', '.join(missing)}")
    return [categories_by_name[name] for name in requested]


def _is_box_inside_image(box: Iterable[float], image_width: int, image_height: int) -> bool:
    x, y, width, height = box
    return x + width <= image_width and y + height <= image_height


def main() -> None:
    """Print an M3 report from a COCO export for the requested target categories."""

    parser = argparse.ArgumentParser(description="Generate an M3 baseline from a COCO JSON file.")
    parser.add_argument("source", type=Path, help="Path to the COCO JSON export")
    parser.add_argument(
        "--category",
        action="append",
        dest="categories",
        required=True,
        help="Target category name; provide at least twice",
    )
    args = parser.parse_args()

    dataset = load_coco_dataset(args.source)
    report = calculate_m3_baseline(
        dataset,
        target_category_names=args.categories,
        source_name=args.source.name,
        source_sha256_value=source_sha256(args.source),
    )
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
