"""Stable, machine-readable exclusion reasons and the two crop artifacts.

Neither artifact carries a timestamp, a host path or any other run-dependent field:
T3-1.1 requires a second run over equal inputs to produce byte-identical JSON, so the
only provenance recorded is content-addressed (the COCO SHA-256) plus the configured
``dataset_version``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt

# Naming follows the DQ-05 analyzer's vocabulary (`nonpositive_width`,
# `exceeds_image_bounds`, ...) wherever the meaning is the same, so the two reports
# can be read side by side; the rest are crop-specific.
ExclusionReason = Literal[
    "malformed_annotation",
    "malformed_bbox",
    "non_numeric_bbox",
    "non_finite_bbox",
    "nonpositive_width",
    "nonpositive_height",
    "negative_origin",
    "origin_outside_image",
    "exceeds_image_bounds",
    "unknown_category",
    "unknown_image",
    "real_dimension_mismatch",
    "exceeds_real_image_bounds",
]

# Reasons that mean "this annotation could not be attributed to a target class at
# all", as opposed to "a target-class box was dropped". They are counted separately
# in `CropRunSummary` so the summary's arithmetic stays auditable.
UNRESOLVABLE_REASONS: frozenset[str] = frozenset({"malformed_annotation", "unknown_category"})


class CropRecord(BaseModel):
    """One written crop: what it came from and exactly which pixels it covers."""

    model_config = ConfigDict(extra="forbid")

    annotation_id: PositiveInt
    source_image_id: PositiveInt
    source_file_name: str = Field(min_length=1)
    category_id: PositiveInt
    category_name: str = Field(min_length=1)
    bbox: tuple[float, float, float, float]
    x_min: int = Field(ge=0)
    y_min: int = Field(ge=0)
    x_max: int = Field(gt=0)
    y_max: int = Field(gt=0)
    crop_width: PositiveInt
    crop_height: PositiveInt
    source_image_width: PositiveInt
    source_image_height: PositiveInt
    observed_image_width: PositiveInt
    observed_image_height: PositiveInt
    relative_path: str = Field(min_length=1)
    png_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class CropExclusion(BaseModel):
    """One rejected annotation, kept verbatim so the drop can be audited.

    ``bbox`` holds the *original* JSON value (a list, a string, ``null``, ...), not a
    normalized box: for a malformed box the raw value is the evidence. Non-finite
    coordinates are serialized as ``null`` here because JSON has no NaN — the
    ``non_finite_bbox`` reason records what actually happened.
    """

    model_config = ConfigDict(extra="forbid")

    annotation_id: int | None = None
    image_id: int | None = None
    image_file_name: str | None = None
    category_id: int | None = None
    category_name: str | None = None
    bbox: Any = None
    reasons: list[ExclusionReason] = Field(min_length=1)


class DimensionMismatch(BaseModel):
    """A source image whose real pixel size differs from the size COCO declares."""

    model_config = ConfigDict(extra="forbid")

    image_id: PositiveInt
    declared_width: PositiveInt
    declared_height: PositiveInt
    observed_width: PositiveInt
    observed_height: PositiveInt


class CropRunSummary(BaseModel):
    """Counts for one crop run, including the non-error ``ignored_non_target``.

    Annotations of non-target categories are *not* errors: they are only counted in
    ``ignored_non_target``, never written as exclusions.
    """

    model_config = ConfigDict(extra="forbid")

    total_annotations: int = Field(ge=0)
    target_annotations: int = Field(ge=0)
    ignored_non_target: int = Field(ge=0)
    crops: int = Field(ge=0)
    excluded: int = Field(ge=0)
    excluded_target_boxes: int = Field(ge=0)
    unresolvable_annotations: int = Field(ge=0)
    images_with_crops: int = Field(ge=0)
    images_with_dimension_mismatch: int = Field(ge=0)
    crops_by_category: dict[str, int]
    exclusions_by_reason: dict[str, int]


class CropManifest(BaseModel):
    """``crops_manifest.json``: every crop plus the provenance it must be readable from."""

    model_config = ConfigDict(extra="forbid")

    dataset_version: str = Field(min_length=1)
    coco_file_name: str = Field(min_length=1)
    coco_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    target_categories: list[str] = Field(min_length=1)
    summary: CropRunSummary
    dimension_mismatches: list[DimensionMismatch]
    crops: list[CropRecord]


class CropExclusionsReport(BaseModel):
    """``crop_exclusions.json``: every rejected annotation with its stable reasons."""

    model_config = ConfigDict(extra="forbid")

    dataset_version: str = Field(min_length=1)
    coco_file_name: str = Field(min_length=1)
    coco_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    target_categories: list[str] = Field(min_length=1)
    summary: CropRunSummary
    exclusions: list[CropExclusion]
