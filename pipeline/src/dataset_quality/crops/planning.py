"""Pure planning: raw COCO in, crop plan plus exclusion records out.

This module reads the raw JSON document and nothing else — no database, no object
store, no Pillow — so every rejection rule is testable on its own and a bad box in one
annotation never hides the rest of the file.

The boundary between "data" and "abort" is deliberate:

- Structural damage (a missing ``images``/``categories``/``annotations`` array, or an
  image entry without a usable id or a positive size) raises ``CropCocoStructureError``:
  there is no honest way to keep going.
- An unusable target configuration raises ``CropConfigurationError``.
- Every other per-annotation problem becomes a ``CropExclusion`` with stable reasons.
- An annotation whose category is not a configured target is neither cropped nor
  reported as an error: it only increments ``ignored_non_target``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from dataset_quality.crops.errors import CropCocoStructureError, CropConfigurationError
from dataset_quality.crops.geometry import (
    Bbox,
    declared_bounds_reasons,
    numeric_bbox,
    shape_reasons,
)
from dataset_quality.crops.models import CropExclusion, ExclusionReason

# A target category name is used verbatim as a directory name, so path separators and
# the Windows-reserved punctuation are rejected up front instead of producing a
# mangled or escaped path.
UNSAFE_PATH_CHARACTERS = frozenset('/\\:*?"<>|')


@dataclass(frozen=True)
class PlannedImage:
    """Declared COCO metadata for one image that contributes at least one crop."""

    image_id: int
    file_name: str
    width: int
    height: int


@dataclass(frozen=True)
class PlannedCrop:
    """A target-class annotation that passed every declared-geometry check."""

    annotation_id: int
    image_id: int
    category_id: int
    category_name: str
    bbox: Bbox


@dataclass(frozen=True)
class CropPlan:
    """Eligible crops, recorded exclusions, and the counts they add up to."""

    target_categories: list[str]
    eligible: list[PlannedCrop]
    exclusions: list[CropExclusion]
    images: dict[int, PlannedImage]
    total_annotations: int
    target_annotations: int
    ignored_non_target: int

    def eligible_by_image(self) -> dict[int, list[PlannedCrop]]:
        """Eligible crops grouped by image id, both in stable id order."""

        grouped: dict[int, list[PlannedCrop]] = {}
        for crop in self.eligible:
            grouped.setdefault(crop.image_id, []).append(crop)
        return grouped


def plan_crops(raw_coco: Any, target_category_names: Sequence[str]) -> CropPlan:
    """Decide which raw COCO annotations become crops, and why the rest do not."""

    if not isinstance(raw_coco, dict):
        raise CropCocoStructureError("COCO source must contain a top-level JSON object")

    annotations_section = _require_array(raw_coco, "annotations")
    images = _index_images(_require_array(raw_coco, "images"))
    declared_categories = _index_categories(_require_array(raw_coco, "categories"))
    resolved_targets = _resolve_targets(declared_categories, target_category_names)
    target_ids = {category_id for _, category_id in resolved_targets}

    eligible: list[PlannedCrop] = []
    exclusions: list[CropExclusion] = []
    ignored_non_target = 0
    target_annotations = 0

    for annotation in annotations_section:
        if not isinstance(annotation, dict):
            exclusions.append(
                _exclusion(
                    annotation_id=None,
                    image_id=None,
                    image=None,
                    category_id=None,
                    category_name=None,
                    bbox=annotation,
                    reasons=["malformed_annotation"],
                )
            )
            continue

        annotation_id = _positive_int(annotation.get("id"))
        image_id = _positive_int(annotation.get("image_id"))
        category_id = _positive_int(annotation.get("category_id"))
        image = images.get(image_id) if image_id is not None else None
        category_name = declared_categories.get(category_id) if category_id is not None else None
        raw_bbox = annotation.get("bbox")

        if annotation_id is None:
            exclusions.append(
                _exclusion(
                    annotation_id=None,
                    image_id=image_id,
                    image=image,
                    category_id=category_id,
                    category_name=category_name,
                    bbox=raw_bbox,
                    reasons=["malformed_annotation"],
                )
            )
            continue
        if category_name is None:
            exclusions.append(
                _exclusion(
                    annotation_id=annotation_id,
                    image_id=image_id,
                    image=image,
                    category_id=category_id,
                    category_name=None,
                    bbox=raw_bbox,
                    reasons=["unknown_category"],
                )
            )
            continue
        if category_id not in target_ids:
            ignored_non_target += 1
            continue

        target_annotations += 1
        if image is None:
            exclusions.append(
                _exclusion(
                    annotation_id=annotation_id,
                    image_id=image_id,
                    image=None,
                    category_id=category_id,
                    category_name=category_name,
                    bbox=raw_bbox,
                    reasons=["unknown_image"],
                )
            )
            continue

        bbox = numeric_bbox(raw_bbox)
        reasons: list[ExclusionReason]
        if bbox is None:
            reasons = shape_reasons(raw_bbox)
        else:
            reasons = declared_bounds_reasons(bbox, width=image.width, height=image.height)
        if reasons:
            exclusions.append(
                _exclusion(
                    annotation_id=annotation_id,
                    image_id=image_id,
                    image=image,
                    category_id=category_id,
                    category_name=category_name,
                    bbox=raw_bbox,
                    reasons=reasons,
                )
            )
            continue

        eligible.append(
            PlannedCrop(
                annotation_id=annotation_id,
                image_id=image_id,
                category_id=category_id,
                category_name=category_name,
                bbox=bbox,
            )
        )

    eligible.sort(key=lambda crop: (crop.category_id, crop.annotation_id))
    exclusions.sort(key=exclusion_sort_key)
    return CropPlan(
        target_categories=[name for name, _ in resolved_targets],
        eligible=eligible,
        exclusions=exclusions,
        images={image_id: images[image_id] for image_id in sorted(_crop_image_ids(eligible))},
        total_annotations=len(annotations_section),
        target_annotations=target_annotations,
        ignored_non_target=ignored_non_target,
    )


def _require_array(raw_coco: dict[str, Any], key: str) -> list[Any]:
    """One required COCO section, or an explicit structural error."""

    section = raw_coco.get(key)
    if not isinstance(section, list):
        raise CropCocoStructureError(f"COCO `{key}` must be a JSON array")
    return section


def _index_images(images_section: list[Any]) -> dict[int, PlannedImage]:
    """Index declared image metadata, rejecting entries that cannot be used at all."""

    indexed: dict[int, PlannedImage] = {}
    for entry in images_section:
        if not isinstance(entry, dict):
            raise CropCocoStructureError("every `images` entry must be a JSON object")
        image_id = _positive_int(entry.get("id"))
        width = _positive_int(entry.get("width"))
        height = _positive_int(entry.get("height"))
        file_name = entry.get("file_name")
        if image_id is None or width is None or height is None:
            raise CropCocoStructureError(
                f"image entry id={entry.get('id')!r} needs a positive integer id, width and height"
            )
        if not isinstance(file_name, str) or not file_name.strip():
            raise CropCocoStructureError(f"image id={image_id} needs a non-blank file_name")
        if image_id in indexed:
            raise CropCocoStructureError(f"image id={image_id} is declared more than once")
        indexed[image_id] = PlannedImage(
            image_id=image_id,
            file_name=file_name.strip(),
            width=width,
            height=height,
        )
    return indexed


def _index_categories(categories_section: list[Any]) -> dict[int, str]:
    """Index declared category names by id.

    Unlike ``images``, an unusable category entry is skipped rather than fatal: this
    index is only a name/id lookup, and an annotation referencing a skipped entry is
    recorded as ``unknown_category`` later.
    """

    indexed: dict[int, str] = {}
    for entry in categories_section:
        if not isinstance(entry, dict):
            continue
        category_id = _positive_int(entry.get("id"))
        name = entry.get("name")
        if category_id is None or not isinstance(name, str) or not name.strip():
            continue
        if category_id in indexed:
            raise CropCocoStructureError(f"category id={category_id} is declared more than once")
        indexed[category_id] = name.strip()
    return indexed


def _resolve_targets(
    declared_categories: dict[int, str], target_category_names: Sequence[str]
) -> list[tuple[str, int]]:
    """Resolve configured target names to declared ids, in the configured order."""

    requested = [name.strip() for name in target_category_names]
    if not requested:
        raise CropConfigurationError("at least one target category must be configured")
    if len(set(requested)) != len(requested):
        raise CropConfigurationError("target categories must be distinct")

    name_to_id = {name: category_id for category_id, name in declared_categories.items()}
    resolved: list[tuple[str, int]] = []
    for name in requested:
        category_id = name_to_id.get(name)
        if category_id is None:
            raise CropConfigurationError(
                f"target category {name!r} is not declared in the COCO file"
            )
        if not _is_safe_directory_name(name):
            raise CropConfigurationError(
                f"target category name {name!r} cannot be used as a directory name"
            )
        resolved.append((name, category_id))
    return resolved


def _is_safe_directory_name(name: str) -> bool:
    """Whether a category name can be used verbatim as a single directory name."""

    if not name or name in {".", ".."}:
        return False
    return not any(character in UNSAFE_PATH_CHARACTERS or ord(character) < 32 for character in name)


def _positive_int(value: Any) -> int | None:
    """A positive integer id, or ``None`` for anything that cannot be one.

    Booleans are rejected explicitly: ``True`` is a Python integer, but it is not a
    COCO id.
    """

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value > 0 and value.is_integer():
        return int(value)
    return None


def _exclusion(
    *,
    annotation_id: int | None,
    image_id: int | None,
    image: PlannedImage | None,
    category_id: int | None,
    category_name: str | None,
    bbox: Any,
    reasons: list[ExclusionReason],
) -> CropExclusion:
    """Assemble an auditable exclusion record from whatever could be resolved."""

    return CropExclusion(
        annotation_id=annotation_id,
        image_id=image_id,
        image_file_name=image.file_name if image is not None else None,
        category_id=category_id,
        category_name=category_name,
        bbox=bbox,
        reasons=reasons,
    )


def exclusion_sort_key(exclusion: CropExclusion) -> tuple[bool, int, bool, int, int]:
    """Stable id ordering for exclusions; records without ids sort last.

    Public because the generator merges its own (dimension-mismatch driven) exclusions
    with the plan's and must keep using exactly this order.
    """

    return (
        exclusion.image_id is None,
        exclusion.image_id or 0,
        exclusion.annotation_id is None,
        exclusion.annotation_id or 0,
        exclusion.category_id or 0,
    )


def _crop_image_ids(crops: list[PlannedCrop]) -> set[int]:
    return {crop.image_id for crop in crops}
