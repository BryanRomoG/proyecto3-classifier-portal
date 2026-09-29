"""Pure COCO box geometry: shape validation, bounds checks, pixel rasterization.

Nothing here touches the filesystem, the database or Pillow, so every rule below is
unit-testable on its own. Evaluation order is fixed, which is what makes the reason
lists in ``crop_exclusions.json`` stable across runs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from dataset_quality.crops.models import ExclusionReason

Number = int | float
Bbox = tuple[float, float, float, float]


@dataclass(frozen=True)
class CropBounds:
    """Integer pixel limits of a crop, half-open on the far corner.

    ``x_min``/``y_min`` are ``floor`` of the COCO origin, and ``x_max``/``y_max`` are
    ``ceil`` of ``x + width`` / ``y + height``, so the crop covers every pixel the
    fractional COCO box touches without ever inventing a pixel outside it.
    """

    x_min: int
    y_min: int
    x_max: int
    y_max: int

    @property
    def width(self) -> int:
        return self.x_max - self.x_min

    @property
    def height(self) -> int:
        return self.y_max - self.y_min

    def as_pil_box(self) -> tuple[int, int, int, int]:
        """The same limits in Pillow's ``(left, upper, right, lower)`` order."""

        return (self.x_min, self.y_min, self.x_max, self.y_max)


def integer_crop_bounds(bbox: Bbox) -> CropBounds:
    """Rasterize a validated COCO ``[x, y, width, height]`` box to integer pixels."""

    x, y, width, height = bbox
    return CropBounds(
        x_min=math.floor(x),
        y_min=math.floor(y),
        x_max=math.ceil(x + width),
        y_max=math.ceil(y + height),
    )


def shape_reasons(raw_bbox: object) -> list[ExclusionReason]:
    """Reasons why a raw value is not four finite numbers, or ``[]`` when it is."""

    if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) != 4:
        return ["malformed_bbox"]
    if not all(_is_number(value) for value in raw_bbox):
        return ["non_numeric_bbox"]
    if not all(math.isfinite(float(value)) for value in raw_bbox):
        return ["non_finite_bbox"]
    return []


def numeric_bbox(raw_bbox: object) -> Bbox | None:
    """The four coordinates of a raw COCO box, or ``None`` if it is unusable."""

    if not isinstance(raw_bbox, (list, tuple)) or shape_reasons(raw_bbox):
        return None
    x, y, width, height = (float(value) for value in raw_bbox)
    return (x, y, width, height)


def declared_bounds_reasons(bbox: Bbox, *, width: int, height: int) -> list[ExclusionReason]:
    """Geometry reasons evaluated against the image size the COCO file declares.

    A degenerate box can make ``x + width`` smaller than ``x``, so the far-corner
    check only runs for a box with a positive area — otherwise a negative width would
    spuriously "fit" and hide the real defect. Same rule as DQ-05's
    ``detect_invalid_boxes``.
    """

    x, y, box_width, box_height = bbox
    reasons: list[ExclusionReason] = []
    if box_width <= 0:
        reasons.append("nonpositive_width")
    if box_height <= 0:
        reasons.append("nonpositive_height")
    if x < 0 or y < 0:
        reasons.append("negative_origin")
    if x >= width or y >= height:
        reasons.append("origin_outside_image")
    if box_width > 0 and box_height > 0 and (x + box_width > width or y + box_height > height):
        reasons.append("exceeds_image_bounds")
    return reasons


def fits_observed_bounds(bbox: Bbox, *, width: int, height: int) -> bool:
    """Whether a box that passed the declared checks also fits the real pixel grid."""

    x, y, box_width, box_height = bbox
    if x < 0 or y < 0 or x >= width or y >= height:
        return False
    return x + box_width <= width and y + box_height <= height


def _is_number(value: object) -> bool:
    """Exclude booleans, which are Python integers but invalid COCO geometry."""

    return isinstance(value, (int, float)) and not isinstance(value, bool)
