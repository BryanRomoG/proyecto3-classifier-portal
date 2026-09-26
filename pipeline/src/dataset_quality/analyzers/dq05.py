"""Duplicate-image and raw-geometry analyzers used by DQ-05."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import combinations
from math import isclose
from pathlib import Path
from typing import Any, Literal

import imagehash
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, PositiveInt


class ImageReference(BaseModel):
    """A dataset image with an explicit local path available to the analyzer."""

    model_config = ConfigDict(extra="forbid")

    image_id: PositiveInt
    path: Path


class PerceptualHashConfig(BaseModel):
    """Policy controlling the pHash representation and near-duplicate threshold."""

    model_config = ConfigDict(extra="forbid")

    hash_size: PositiveInt = Field(default=8, le=8)
    max_distance: int = Field(default=8, ge=0, le=64)


class DuplicateImagePair(BaseModel):
    """One deterministic pair whose Hamming distance meets the active threshold."""

    image_id_a: PositiveInt
    image_id_b: PositiveInt
    distance: int = Field(ge=0, le=64)
    similarity: float = Field(ge=0, le=1)


class NearDuplicateImagesResult(BaseModel):
    """All pHash pairs that match the selected near-duplicate policy."""

    max_distance: int = Field(ge=0, le=64)
    pairs: list[DuplicateImagePair]


InvalidBoxReason = Literal[
    "nonpositive_width",
    "nonpositive_height",
    "coordinate_outside_image",
    "exceeds_image_bounds",
    "area_mismatch",
]


class InvalidBoxIssue(BaseModel):
    """A raw COCO annotation that violates one or more geometry invariants."""

    annotation_id: int
    reasons: list[InvalidBoxReason]


class InvalidBoxesResult(BaseModel):
    """All raw annotations whose boxes cannot be safely used downstream."""

    invalid_boxes: list[InvalidBoxIssue]


def find_near_duplicate_images(
    images: Sequence[ImageReference], config: PerceptualHashConfig | None = None
) -> NearDuplicateImagesResult:
    """Find exact and near duplicates using pHash and a Hamming-distance threshold."""

    policy = config or PerceptualHashConfig()
    ordered_images = sorted(images, key=lambda image: image.image_id)
    _ensure_unique_image_ids(ordered_images)
    image_hashes = {
        image.image_id: _perceptual_hash(image.path, policy.hash_size) for image in ordered_images
    }
    total_bits = policy.hash_size**2
    pairs: list[DuplicateImagePair] = []

    for first, second in combinations(ordered_images, 2):
        distance = int(image_hashes[first.image_id] - image_hashes[second.image_id])
        if distance > policy.max_distance:
            continue
        pairs.append(
            DuplicateImagePair(
                image_id_a=first.image_id,
                image_id_b=second.image_id,
                distance=distance,
                similarity=1 - distance / total_bits,
            )
        )

    return NearDuplicateImagesResult(max_distance=policy.max_distance, pairs=pairs)


def detect_invalid_boxes(raw_coco: Mapping[str, Any]) -> InvalidBoxesResult:
    """Inspect raw COCO geometry before strict DQ-01 validation can reject it."""

    image_sizes = _image_sizes(raw_coco.get("images", []))
    invalid_boxes: list[InvalidBoxIssue] = []
    annotations = raw_coco.get("annotations", [])
    if not isinstance(annotations, list):
        return InvalidBoxesResult(invalid_boxes=[])

    for annotation in annotations:
        if not isinstance(annotation, Mapping):
            continue
        box = annotation.get("bbox")
        if not _is_numeric_box(box):
            continue

        x, y, width, height = (float(value) for value in box)
        reasons: list[InvalidBoxReason] = []
        if width <= 0:
            reasons.append("nonpositive_width")
        if height <= 0:
            reasons.append("nonpositive_height")

        image_size = image_sizes.get(annotation.get("image_id"))
        if image_size is not None:
            image_width, image_height = image_size
            if x < 0 or y < 0 or x >= image_width or y >= image_height:
                reasons.append("coordinate_outside_image")
            if width > 0 and height > 0 and (x + width > image_width or y + height > image_height):
                reasons.append("exceeds_image_bounds")

        area = annotation.get("area")
        if (
            isinstance(area, (int, float))
            and not isinstance(area, bool)
            and not isclose(float(area), width * height, rel_tol=1e-9, abs_tol=1e-9)
        ):
            reasons.append("area_mismatch")

        if reasons:
            invalid_boxes.append(
                InvalidBoxIssue(annotation_id=int(annotation.get("id", -1)), reasons=reasons)
            )

    return InvalidBoxesResult(invalid_boxes=invalid_boxes)


def _perceptual_hash(path: Path, hash_size: int) -> imagehash.ImageHash:
    """Open one image safely and calculate its perceptual hash."""

    with Image.open(path) as image:
        return imagehash.phash(image.convert("RGB"), hash_size=hash_size)


def _ensure_unique_image_ids(images: Sequence[ImageReference]) -> None:
    """Reject ambiguous duplicate IDs before creating pair results."""

    image_ids = [image.image_id for image in images]
    if len(image_ids) != len(set(image_ids)):
        message = "Each image reference must use a unique image_id."
        raise ValueError(message)


def _image_sizes(images: object) -> dict[object, tuple[float, float]]:
    """Index usable raw COCO image dimensions by image identifier."""

    if not isinstance(images, list):
        return {}
    sizes: dict[object, tuple[float, float]] = {}
    for image in images:
        if not isinstance(image, Mapping):
            continue
        width = image.get("width")
        height = image.get("height")
        if _is_number(width) and _is_number(height):
            sizes[image.get("id")] = (float(width), float(height))
    return sizes


def _is_numeric_box(box: object) -> bool:
    """Return whether a raw value is a four-coordinate numeric COCO box."""

    return isinstance(box, list) and len(box) == 4 and all(_is_number(value) for value in box)


def _is_number(value: object) -> bool:
    """Exclude booleans, which are Python integers but invalid COCO geometry."""

    return isinstance(value, (int, float)) and not isinstance(value, bool)
