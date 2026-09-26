"""Spatial object-center distribution analysis for DQ-06."""

from __future__ import annotations

from math import floor
from statistics import fmean, median

from pydantic import BaseModel, Field

from dataset_quality.ingestion.models import CocoDataset


class AxisStatistics(BaseModel):
    """Summary statistics for one normalized object-center axis."""

    mean: float = Field(ge=0, le=1)
    median: float = Field(ge=0, le=1)
    p10: float = Field(ge=0, le=1)
    p90: float = Field(ge=0, le=1)


class SpatialBiasResult(BaseModel):
    """Spatial distribution of valid COCO object centers on a fixed grid."""

    valid_boxes: int = Field(ge=0)
    excluded_invalid_boxes: int = Field(ge=0)
    x: AxisStatistics | None = None
    y: AxisStatistics | None = None
    grid_counts: dict[str, int]
    most_populated_cell: str | None = None
    max_cell_percentage: float = Field(ge=0, le=100)


def analyze_spatial_bias(dataset: CocoDataset, grid_size: int = 3) -> SpatialBiasResult:
    """Calculate center statistics and a normalized object-center grid distribution."""

    if grid_size < 1:
        raise ValueError("grid_size must be at least 1")

    images_by_id = {image.id: image for image in dataset.images}
    x_centers: list[float] = []
    y_centers: list[float] = []
    grid_counts: dict[str, int] = {}
    excluded_invalid_boxes = 0

    for annotation in dataset.annotations:
        image = images_by_id[annotation.image_id]
        x, y, width, height = annotation.bbox.root
        if not _is_box_inside_image(x, y, width, height, image.width, image.height):
            excluded_invalid_boxes += 1
            continue

        center_x = (x + width / 2) / image.width
        center_y = (y + height / 2) / image.height
        x_centers.append(center_x)
        y_centers.append(center_y)
        cell = _grid_cell(center_x, center_y, grid_size)
        grid_counts[cell] = grid_counts.get(cell, 0) + 1

    valid_boxes = len(x_centers)
    most_populated_cell = _most_populated_cell(grid_counts)
    max_cell_percentage = (
        grid_counts[most_populated_cell] / valid_boxes * 100
        if most_populated_cell is not None
        else 0.0
    )
    return SpatialBiasResult(
        valid_boxes=valid_boxes,
        excluded_invalid_boxes=excluded_invalid_boxes,
        x=_axis_statistics(x_centers),
        y=_axis_statistics(y_centers),
        grid_counts=grid_counts,
        most_populated_cell=most_populated_cell,
        max_cell_percentage=max_cell_percentage,
    )


def _is_box_inside_image(
    x: float, y: float, width: float, height: float, image_width: int, image_height: int
) -> bool:
    return x >= 0 and y >= 0 and x + width <= image_width and y + height <= image_height


def _axis_statistics(values: list[float]) -> AxisStatistics | None:
    if not values:
        return None
    return AxisStatistics(
        mean=fmean(values),
        median=median(values),
        p10=_percentile(values, 10),
        p90=_percentile(values, 90),
    )


def _percentile(values: list[float], percentile: float) -> float:
    """Use linear interpolation between ordered observations, matching common tooling."""

    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100
    lower = floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _grid_cell(center_x: float, center_y: float, grid_size: int) -> str:
    column = min(floor(center_x * grid_size), grid_size - 1)
    row = min(floor(center_y * grid_size), grid_size - 1)
    return f"{column},{row}"


def _most_populated_cell(grid_counts: dict[str, int]) -> str | None:
    if not grid_counts:
        return None
    return max(grid_counts, key=lambda cell: (grid_counts[cell], cell))
