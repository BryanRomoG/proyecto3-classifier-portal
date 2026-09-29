"""Build the T3-1.2 leak-free classifier split manifest from the COCO crops.

The grouping algorithm is **not** reimplemented here: the COCO document, the configured
70/20/10 proportions and ``duplicate_pairs.json`` are handed to the inherited
``dataset_quality.splits.generate_splits``, which already groups images by their
transitive duplicate components (union-find) and keeps each group inside a single split.
This module only:

1. checks that the three inputs provably describe each other (dataset version, COCO
   SHA-256, known source images, unique crop identities) before anything is generated;
2. maps every ``crops_manifest.json`` record onto the split of its ``source_image_id``,
   so each image and each crop appears exactly once, and
3. records the result deterministically, with SHA-256 provenance and no timestamps.

The classifier's *evaluation* crops are just crops: no model prediction or metric is read
or exposed anywhere in this artifact.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from dataset_quality.analyzers.m3 import load_coco_dataset
from dataset_quality.classifier_splits.errors import ClassifierSplitError
from dataset_quality.classifier_splits.models import (
    ClassifierSplitCrop,
    ClassifierSplitLeakageCheck,
    ClassifierSplitManifest,
    ClassifierSplitProportions,
    ClassifierSplitProvenance,
    ClassifierSplitSection,
    ClassifierSplitTotals,
)
from dataset_quality.config.models import SplitConfig
from dataset_quality.crops.models import CropManifest, CropRecord
from dataset_quality.splits.generator import generate_splits
from dataset_quality.splits.models import SplitLeakageCheck

SPLIT_NAMES: tuple[str, ...] = ("train", "val", "test")


@dataclass(frozen=True)
class ClassifierSplitResult:
    """What one run produced: the serializable, leak-free classifier manifest."""

    manifest: ClassifierSplitManifest


def generate_classifier_split(
    *,
    coco_path: Path,
    crops_manifest_path: Path,
    duplicate_pairs_path: Path,
    dataset_version: str,
    config: SplitConfig,
) -> ClassifierSplitResult:
    """Build the leak-free classifier manifest for the crops of ``coco_path``.

    Raises ``ClassifierSplitError`` when the crops manifest and the COCO file disagree,
    when a crop references an image the COCO file does not declare, when a crop identity
    is repeated, or when the resulting assignment is not an exact partition. A duplicate
    pair referencing an unknown image id raises the inherited generator's ``ValueError``.
    """

    coco_bytes = coco_path.read_bytes()
    crops_manifest_bytes = crops_manifest_path.read_bytes()
    duplicate_pairs_bytes = duplicate_pairs_path.read_bytes()
    coco_sha256 = hashlib.sha256(coco_bytes).hexdigest()

    dataset = load_coco_dataset(coco_path)
    crops_manifest = CropManifest.model_validate_json(crops_manifest_bytes)
    _require_matching_provenance(
        crops_manifest=crops_manifest,
        coco_sha256=coco_sha256,
        dataset_version=dataset_version,
    )
    _require_unique_crop_identities(crops_manifest.crops)

    known_image_ids = {image.id for image in dataset.images}
    for crop in crops_manifest.crops:
        if crop.source_image_id not in known_image_ids:
            raise ClassifierSplitError(
                f"crop annotation_id={crop.annotation_id} references "
                f"source_image_id={crop.source_image_id}, which is not declared in "
                f"{coco_path.name}"
            )

    generated = generate_splits(
        dataset,
        config,
        dataset_version=dataset_version,
        duplicate_pairs=_load_duplicate_pairs(duplicate_pairs_bytes),
    )
    _require_exact_partition(generated.assignment, known_image_ids)
    _require_no_leakage(generated.report.leakage_check)

    sections, totals = _build_sections(generated.assignment, crops_manifest.crops)

    manifest = ClassifierSplitManifest(
        dataset_version=dataset_version,
        seed=config.seed,
        proportions=ClassifierSplitProportions(
            train=config.train, val=config.val, test=config.test
        ),
        provenance=ClassifierSplitProvenance(
            coco_file_name=coco_path.name,
            coco_sha256=coco_sha256,
            crops_manifest_file_name=crops_manifest_path.name,
            crops_manifest_sha256=hashlib.sha256(crops_manifest_bytes).hexdigest(),
            duplicate_pairs_file_name=duplicate_pairs_path.name,
            duplicate_pairs_sha256=hashlib.sha256(duplicate_pairs_bytes).hexdigest(),
        ),
        totals=totals,
        splits=sections,
        leakage_check=ClassifierSplitLeakageCheck(
            status=generated.report.leakage_check.status,
            duplicate_pairs_checked=generated.report.leakage_check.near_duplicate_pairs_checked,
            duplicate_pairs_same_split=(
                generated.report.leakage_check.near_duplicate_pairs_same_split
            ),
            leaked_pairs=generated.report.leakage_check.leaked_pairs,
        ),
    )
    return ClassifierSplitResult(manifest=manifest)


def _require_matching_provenance(
    *,
    crops_manifest: CropManifest,
    coco_sha256: str,
    dataset_version: str,
) -> None:
    """Refuse a crops manifest that was not built from this version of this COCO file."""

    if crops_manifest.dataset_version != dataset_version:
        raise ClassifierSplitError(
            f"crops manifest was built for dataset_version="
            f"{crops_manifest.dataset_version!r}, not {dataset_version!r}"
        )
    if crops_manifest.coco_sha256 != coco_sha256:
        raise ClassifierSplitError(
            "crops manifest coco_sha256 does not match the COCO file it is split against: "
            f"manifest={crops_manifest.coco_sha256} file={coco_sha256}"
        )


def _require_unique_crop_identities(crops: Sequence[CropRecord]) -> None:
    """Each crop must be identifiable by exactly one annotation id and one path."""

    annotation_ids = [crop.annotation_id for crop in crops]
    if len(annotation_ids) != len(set(annotation_ids)):
        raise ClassifierSplitError("crops manifest contains duplicate annotation_id values")
    relative_paths = [crop.relative_path for crop in crops]
    if len(relative_paths) != len(set(relative_paths)):
        raise ClassifierSplitError("crops manifest contains duplicate relative_path values")


def _load_duplicate_pairs(payload_bytes: bytes) -> list[tuple[int, int]]:
    """Parse ``duplicate_pairs.json`` into the pairs the inherited generator expects."""

    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError as error:
        raise ClassifierSplitError(f"duplicate pairs file is not valid JSON: {error}") from error
    if not isinstance(payload, list):
        raise ClassifierSplitError("duplicate pairs file must contain a top-level JSON array")

    pairs: list[tuple[int, int]] = []
    for entry in payload:
        if not isinstance(entry, list) or len(entry) != 2:
            raise ClassifierSplitError(
                f"duplicate pair {entry!r} must be a two-element array of image ids"
            )
        image_a, image_b = entry
        if not isinstance(image_a, int) or not isinstance(image_b, int):
            raise ClassifierSplitError(f"duplicate pair {entry!r} must contain integer image ids")
        pairs.append((image_a, image_b))
    return pairs


def _require_exact_partition(assignment: dict[str, list[int]], known_image_ids: set[int]) -> None:
    """Every COCO image must land in exactly one split, and nothing else may appear."""

    split_of_image: dict[int, str] = {}
    for name in SPLIT_NAMES:
        for image_id in assignment[name]:
            if image_id in split_of_image:
                raise ClassifierSplitError(
                    f"image_id={image_id} is assigned to both "
                    f"{split_of_image[image_id]!r} and {name!r}"
                )
            split_of_image[image_id] = name

    missing = sorted(known_image_ids - split_of_image.keys())
    if missing:
        raise ClassifierSplitError(
            f"{len(missing)} COCO image(s) are missing from the split assignment: {missing[:5]}"
        )
    unknown = sorted(split_of_image.keys() - known_image_ids)
    if unknown:
        raise ClassifierSplitError(
            f"the split assignment contains {len(unknown)} image id(s) that are not in "
            f"the COCO file: {unknown[:5]}"
        )


def _require_no_leakage(leakage: SplitLeakageCheck) -> None:
    """A duplicate pair split across train/val/test would poison the classifier."""

    if leakage.leaked_pairs:
        raise ClassifierSplitError(
            f"{leakage.leaked_pairs} near-duplicate pair(s) were split across "
            "train/val/test; refusing to write a leaky manifest"
        )


def _build_sections(
    assignment: dict[str, list[int]], crops: Sequence[CropRecord]
) -> tuple[list[ClassifierSplitSection], ClassifierSplitTotals]:
    """Place every crop in the split of its source image, exactly once."""

    split_of_image = {image_id: name for name in SPLIT_NAMES for image_id in assignment[name]}
    crops_by_split: dict[str, list[ClassifierSplitCrop]] = {name: [] for name in SPLIT_NAMES}
    for crop in sorted(crops, key=lambda record: record.annotation_id):
        split_name = split_of_image.get(crop.source_image_id)
        if split_name is None:
            raise ClassifierSplitError(
                f"crop annotation_id={crop.annotation_id} references source_image_id="
                f"{crop.source_image_id}, which has no split assignment"
            )
        crops_by_split[split_name].append(
            ClassifierSplitCrop(
                annotation_id=crop.annotation_id,
                source_image_id=crop.source_image_id,
                category_name=crop.category_name,
                relative_path=crop.relative_path,
            )
        )

    sections: list[ClassifierSplitSection] = []
    for name in SPLIT_NAMES:
        image_ids = sorted(assignment[name])
        split_crops = crops_by_split[name]
        sections.append(
            ClassifierSplitSection(
                name=name,
                image_ids=image_ids,
                image_count=len(image_ids),
                crop_count=len(split_crops),
                crops=split_crops,
                crops_by_category=_category_counts(split_crops),
                images_by_category=_image_counts_by_category(split_crops),
            )
        )

    totals = ClassifierSplitTotals(
        images=sum(section.image_count for section in sections),
        crops=sum(section.crop_count for section in sections),
    )
    return sections, totals


def _category_counts(crops: Sequence[ClassifierSplitCrop]) -> dict[str, int]:
    """Crops per category, sorted by name so the JSON is deterministic."""

    counter: Counter[str] = Counter(crop.category_name for crop in crops)
    return dict(sorted(counter.items()))


def _image_counts_by_category(crops: Sequence[ClassifierSplitCrop]) -> dict[str, int]:
    """Distinct source images carrying each category, sorted by name."""

    images_by_category: dict[str, set[int]] = defaultdict(set)
    for crop in crops:
        images_by_category[crop.category_name].add(crop.source_image_id)
    return {name: len(ids) for name, ids in sorted(images_by_category.items())}
