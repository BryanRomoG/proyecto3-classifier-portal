"""Crop generation: plan → fetch each image once → write deterministic PNGs and JSON.

Order of operations, and why:

1. Plan from the raw COCO document (pure; see ``planning``), so a bad box is recorded
   instead of aborting the run.
2. Resolve every needed ``storage_key`` in one query, then decode each image exactly
   once and render all of its crops from that single decode. Nothing is fetched for an
   image whose target-class boxes were all rejected beforehand.
3. Build the entire run -- PNGs, count invariants, JSON serialization -- under temporary
   sibling paths on the same filesystem as the final outputs, and publish the three
   outputs only once all of that has succeeded. ``crops/`` is therefore never a partial
   tree: a run that dies before publication (a missing object, an undecodable image, a
   failed invariant, a broken serialization) leaves the previously published artifacts
   byte-for-byte as they were, and removes its own temporaries.

No timestamp is recorded anywhere: T3-1.1 requires two runs over equal inputs to be
byte-identical, which a ``generated_at`` field would break.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import uuid
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
    Everything is built under temporary siblings and published only once the whole run
    has succeeded, so such a failure leaves whatever was published before untouched --
    and on a first run publishes nothing at all.
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

    token = uuid.uuid4().hex
    staged_crops = _staging_sibling(crops_root, token)
    staged_manifest = _staging_sibling(manifest_path, token)
    staged_exclusions = _staging_sibling(exclusions_path, token)

    try:
        staged_crops.mkdir(parents=True, exist_ok=True)
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
                                crop,
                                image,
                                ["real_dimension_mismatch", "exceeds_real_image_bounds"],
                            )
                        )
                        continue

                    bounds = integer_crop_bounds(crop.bbox)
                    _require_bounds_within_grid(bounds, observed.width, observed.height)
                    png = _png_for_region(observed, bounds)
                    # The published path is what the manifest names, never the staging
                    # path: the staging names are an implementation detail of this run.
                    crop_path = crops_root / crop.category_name / f"{crop.annotation_id}.png"
                    staged_path = staged_crops / crop.category_name / f"{crop.annotation_id}.png"
                    staged_path.parent.mkdir(parents=True, exist_ok=True)
                    staged_path.write_bytes(png)
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
        # Both artifacts are serialized into the staging paths as well: a run only
        # becomes "written" once every count adds up and every byte is serialized.
        _write_json(staged_manifest, manifest.model_dump_json(indent=2))
        _write_json(staged_exclusions, exclusions_report.model_dump_json(indent=2))
    except BaseException:
        # Nothing was published yet, so the previous release is still intact on disk:
        # drop this run's temporaries and let the failure surface unchanged.
        _discard(staged_crops, staged_manifest, staged_exclusions)
        raise

    _publish(
        token=token,
        crops_root=crops_root,
        manifest_path=manifest_path,
        exclusions_path=exclusions_path,
    )
    return CropRunResult(manifest=manifest, exclusions=exclusions_report, written=tuple(written))


def _staging_sibling(target: Path, token: str) -> Path:
    """The temporary sibling of ``target``, on its own filesystem so publishing is a move."""

    return target.with_name(f".{target.name}.staging-{token}")


def _discard(*paths: Path) -> None:
    """Remove staged paths that were never published -- trees, files or nothing at all."""

    for path in paths:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)


def _publish(*, token: str, crops_root: Path, manifest_path: Path, exclusions_path: Path) -> None:
    """Replace the three published outputs with this run's fully built staged copies.

    ``crops/`` is swapped first and the JSON last, so the manifest is never newer than
    the tree it describes: a run interrupted between the two steps keeps the previous
    release's manifest -- a true statement about a release that is still on disk --
    instead of one claiming crops that were never published.
    """

    staged_crops = _staging_sibling(crops_root, token)
    staged_manifest = _staging_sibling(manifest_path, token)
    staged_exclusions = _staging_sibling(exclusions_path, token)
    try:
        _swap_directory(staged_crops, crops_root, token)
        os.replace(staged_manifest, manifest_path)
        os.replace(staged_exclusions, exclusions_path)
    finally:
        _discard(staged_crops, staged_manifest, staged_exclusions)


def _swap_directory(staged: Path, target: Path, token: str) -> None:
    """Move ``staged`` onto ``target``, keeping the old tree until the move succeeded."""

    previous: Path | None = None
    if target.exists():
        previous = target.with_name(f".{target.name}.previous-{token}")
        os.rename(target, previous)
    try:
        os.rename(staged, target)
    except OSError:
        if previous is not None:
            os.rename(previous, target)
        raise
    if previous is not None:
        shutil.rmtree(previous, ignore_errors=True)


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
    # LF on every OS: these files are hashed downstream; CRLF on Windows would change it.
    path.write_text(payload, encoding="utf-8", newline="\n")
