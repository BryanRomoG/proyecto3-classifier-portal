"""Crop generation: plan → fetch each image once → write deterministic PNGs and JSON.

Order of operations, and why:

1. Plan from the raw COCO document (pure; see ``planning``), so a bad box is recorded
   instead of aborting the run.
2. Resolve every needed ``storage_key`` in one query, then decode each image exactly
   once and render all of its crops from that single decode. Nothing is fetched for an
   image whose target-class boxes were all rejected beforehand.
3. Write the PNGs, then the manifest and the exclusions report. ``crops/`` is wiped
   first so the directory can never disagree with the manifest that describes it, and
   the JSON is written last so a failed run leaves no artifact claiming success.

No timestamp is recorded anywhere: T3-1.1 requires two runs over equal inputs to be
byte-identical, which a ``generated_at`` field would break.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from dataset_quality.crops.errors import (
    CropCocoStructureError,
    CropError,
    CropSourceDecodeError,
    CropSourceUnavailableError,
)
from dataset_quality.crops.geometry import CropBounds, fits_observed_bounds, integer_crop_bounds
from dataset_quality.crops.models import (
    UNRESOLVABLE_REASONS,
    CropExclusion,
    CropExclusionsReport,
    CropManifest,
    CropRecord,
    CropRunSummary,
    DimensionMismatch,
    ExclusionReason,
)
from dataset_quality.crops.planning import (
    CropPlan,
    PlannedCrop,
    PlannedImage,
    exclusion_sort_key,
    plan_crops,
)
from dataset_quality.crops.sources import SourceImageStore


@dataclass(frozen=True)
class CropRunResult:
    """What one crop run produced: both artifacts plus the PNGs it wrote."""

    manifest: CropManifest
    exclusions: CropExclusionsReport
    written: tuple[Path, ...]


def generate_crops(
    *,
    coco_path: Path,
    crops_root: Path,
    manifest_path: Path,
    exclusions_path: Path,
    dataset_version: str,
    target_categories: Sequence[str],
    source_store: SourceImageStore,
) -> CropRunResult:
    """Write traceable crops for every valid target-class box in ``coco_path``.

    Raises ``CropCocoStructureError`` / ``CropConfigurationError`` for a document that
    cannot be planned at all, ``CropSourceUnavailableError`` when a source image's row
    or object is missing, and ``CropSourceDecodeError`` when its bytes are not an image.
    None of those leave a manifest behind.
    """

    coco_bytes = coco_path.read_bytes()
    coco_sha256 = hashlib.sha256(coco_bytes).hexdigest()
    plan = plan_crops(_load_raw_coco(coco_bytes, coco_path), target_categories)

    crops_by_image = plan.eligible_by_image()
    storage_keys = source_store.storage_keys(sorted(crops_by_image)) if crops_by_image else {}
    missing_keys = [image_id for image_id in sorted(crops_by_image) if image_id not in storage_keys]
    if missing_keys:
        raise CropSourceUnavailableError(
            f"no storage_key was returned for {len(missing_keys)} referenced image id(s) "
            f"(e.g. {missing_keys[:5]})"
        )

    _reset_crops_root(crops_root)
    crops: list[CropRecord] = []
    exclusions: list[CropExclusion] = list(plan.exclusions)
    mismatches: list[DimensionMismatch] = []
    written: list[Path] = []

    for image_id in sorted(crops_by_image):
        image = plan.images[image_id]
        data = source_store.read_bytes(storage_keys[image_id])
        with _open_source_image(data, image_id) as observed:
            mismatch = (observed.width, observed.height) != (image.width, image.height)
            if mismatch:
                mismatches.append(
                    DimensionMismatch(
                        image_id=image_id,
                        declared_width=image.width,
                        declared_height=image.height,
                        observed_width=observed.width,
                        observed_height=observed.height,
                    )
                )
            for crop in crops_by_image[image_id]:
                if mismatch and not fits_observed_bounds(
                    crop.bbox, width=observed.width, height=observed.height
                ):
                    exclusions.append(
                        _excluded_target_crop(
                            crop, image, ["real_dimension_mismatch", "exceeds_real_image_bounds"]
                        )
                    )
                    continue

                bounds = integer_crop_bounds(crop.bbox)
                _require_bounds_within_grid(bounds, observed.width, observed.height)
                png = _png_for_region(observed, bounds)
                crop_path = crops_root / crop.category_name / f"{crop.annotation_id}.png"
                crop_path.parent.mkdir(parents=True, exist_ok=True)
                crop_path.write_bytes(png)
                written.append(crop_path)
                crops.append(
                    CropRecord(
                        annotation_id=crop.annotation_id,
                        source_image_id=crop.image_id,
                        source_file_name=image.file_name,
                        category_id=crop.category_id,
                        category_name=crop.category_name,
                        bbox=crop.bbox,
                        x_min=bounds.x_min,
                        y_min=bounds.y_min,
                        x_max=bounds.x_max,
                        y_max=bounds.y_max,
                        crop_width=bounds.width,
                        crop_height=bounds.height,
                        source_image_width=image.width,
                        source_image_height=image.height,
                        observed_image_width=observed.width,
                        observed_image_height=observed.height,
                        relative_path=crop_path.as_posix(),
                        png_sha256=hashlib.sha256(png).hexdigest(),
                    )
                )

    crops.sort(key=lambda record: (record.category_id, record.annotation_id))
    exclusions.sort(key=exclusion_sort_key)
    mismatches.sort(key=lambda mismatch: mismatch.image_id)
    summary = _summarise(plan, crops, exclusions, mismatches)

    manifest = CropManifest(
        dataset_version=dataset_version,
        coco_file_name=coco_path.name,
        coco_sha256=coco_sha256,
        target_categories=list(plan.target_categories),
        summary=summary,
        dimension_mismatches=mismatches,
        crops=crops,
    )
    exclusions_report = CropExclusionsReport(
        dataset_version=dataset_version,
        coco_file_name=coco_path.name,
        coco_sha256=coco_sha256,
        target_categories=list(plan.target_categories),
        summary=summary,
        exclusions=exclusions,
    )
    _write_json(manifest_path, manifest.model_dump_json(indent=2))
    _write_json(exclusions_path, exclusions_report.model_dump_json(indent=2))
    return CropRunResult(manifest=manifest, exclusions=exclusions_report, written=tuple(written))


def _load_raw_coco(coco_bytes: bytes, coco_path: Path) -> Any:
    """Parse the canonical COCO document without validating it into strict models.

    Strict validation is exactly what the crop stage must *not* do here: an invalid
    box has to become an audit record, not an abort. Structural damage is still fatal.
    """

    try:
        payload = json.loads(coco_bytes)
    except json.JSONDecodeError as error:
        raise CropCocoStructureError(f"{coco_path} is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise CropCocoStructureError(f"{coco_path} must contain a top-level JSON object")
    return payload


def _reset_crops_root(crops_root: Path) -> None:
    """Recreate ``crops_root`` empty, so the tree always matches the manifest."""

    if crops_root.exists():
        shutil.rmtree(crops_root)
    crops_root.mkdir(parents=True, exist_ok=True)


@contextmanager
def _open_source_image(data: bytes, image_id: int) -> Iterator[Image.Image]:
    """Decode one source image fully, mapping every decode failure to a loud error."""

    try:
        image = Image.open(io.BytesIO(data))
    except UnidentifiedImageError as error:
        raise CropSourceDecodeError(f"image id={image_id} is not a decodable image file") from error
    try:
        image.load()
    except OSError as error:
        raise CropSourceDecodeError(f"image id={image_id} could not be decoded: {error}") from error
    try:
        yield image
    finally:
        image.close()


def _png_for_region(image: Image.Image, bounds: CropBounds) -> bytes:
    """Crop one region and encode it as a deterministic RGB PNG."""

    region = image.crop(bounds.as_pil_box()).convert("RGB")
    try:
        buffer = io.BytesIO()
        region.save(buffer, format="PNG")
        return buffer.getvalue()
    finally:
        region.close()


def _require_bounds_within_grid(bounds: CropBounds, width: int, height: int) -> None:
    """Guard the floor/ceil rasterization against ever leaving the real pixel grid."""

    if bounds.x_min < 0 or bounds.y_min < 0 or bounds.x_max > width or bounds.y_max > height:
        raise CropError(
            f"internal error: rasterized bounds {bounds.as_pil_box()} fall outside the observed "
            f"{width}x{height} pixel grid"
        )


def _excluded_target_crop(
    crop: PlannedCrop, image: PlannedImage, reasons: list[ExclusionReason]
) -> CropExclusion:
    """An exclusion for a target-class box that only failed against real pixels."""

    return CropExclusion(
        annotation_id=crop.annotation_id,
        image_id=crop.image_id,
        image_file_name=image.file_name,
        category_id=crop.category_id,
        category_name=crop.category_name,
        bbox=list(crop.bbox),
        reasons=reasons,
    )


def _summarise(
    plan: CropPlan,
    crops: list[CropRecord],
    exclusions: list[CropExclusion],
    mismatches: list[DimensionMismatch],
) -> CropRunSummary:
    """Count one run, then refuse to hand back counts that do not add up."""

    crops_by_category = Counter(record.category_name for record in crops)
    exclusions_by_reason: Counter[str] = Counter()
    for exclusion in exclusions:
        exclusions_by_reason.update(exclusion.reasons)
    unresolvable = sum(1 for row in exclusions if set(row.reasons) <= UNRESOLVABLE_REASONS)

    summary = CropRunSummary(
        total_annotations=plan.total_annotations,
        target_annotations=plan.target_annotations,
        ignored_non_target=plan.ignored_non_target,
        crops=len(crops),
        excluded=len(exclusions),
        excluded_target_boxes=len(exclusions) - unresolvable,
        unresolvable_annotations=unresolvable,
        images_with_crops=len({record.source_image_id for record in crops}),
        images_with_dimension_mismatch=len(mismatches),
        crops_by_category={name: crops_by_category.get(name, 0) for name in plan.target_categories},
        exclusions_by_reason=dict(sorted(exclusions_by_reason.items())),
    )
    _verify_summary(summary)
    return summary


def _verify_summary(summary: CropRunSummary) -> None:
    """Fail loudly when the counts stop adding up.

    These are invariants of the planning step, so a mismatch means the run would be
    reporting a story its own artifacts do not support.
    """

    if summary.crops + summary.excluded_target_boxes != summary.target_annotations:
        raise CropError(
            "crop summary is inconsistent: crops + excluded target boxes != target annotations"
        )
    if summary.excluded != summary.excluded_target_boxes + summary.unresolvable_annotations:
        raise CropError(
            "crop summary is inconsistent: excluded != target boxes + unresolvable annotations"
        )
    resolvable_total = (
        summary.target_annotations + summary.ignored_non_target + summary.unresolvable_annotations
    )
    if summary.total_annotations != resolvable_total:
        raise CropError(
            "crop summary is inconsistent: total != target + ignored non-target + unresolvable"
        )


def _write_json(path: Path, payload: str) -> None:
    """Write one artifact, creating its directory first."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
