"""DQ-07: Independent audit of M3 dataset metrics and quality analyzers (issue #32).

Provides an independent verification engine that:
1. Re-calculates invalid boxes, distinct valid images per class, small objects,
   and class imbalance from raw COCO JSON without delegating to production analyzers.
2. Implements transitive connected-component collapse for duplicate pairs (A-B, B-C -> {A, B, C}),
   preserving class membership evidence within collapsed image groups.
3. Audits M3 compliance before and after duplicate collapse.
4. Cross-checks independent calculations against production analyzers to detect discrepancies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from math import isclose
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from dataset_quality.analyzers.dq04 import (
    ClassImbalanceConfig,
    SmallObjectsConfig,
    analyze_class_imbalance,
    analyze_small_objects,
)
from dataset_quality.analyzers.dq05 import (
    DuplicateImagePair,
    ImageReference,
    PerceptualHashConfig,
    detect_invalid_boxes,
    find_near_duplicate_images,
)
from dataset_quality.ingestion.models import CocoDataset

# ---------------------------------------------------------------------------
# Audit Data Models
# ---------------------------------------------------------------------------


class ClassAuditMetrics(BaseModel):
    """Independent audit breakdown for a single category."""

    category_id: int
    category_name: str
    total_boxes: int
    valid_boxes: int
    invalid_boxes: int
    distinct_images_raw: int
    distinct_images_valid_before_collapse: int
    distinct_images_valid_after_collapse: int
    m3_threshold: int = 300
    meets_m3_before_collapse: bool
    meets_m3_after_collapse: bool
    deficit_after_collapse: int = 0


class OverallAuditReport(BaseModel):
    """Complete independent audit summary and production cross-check."""

    dataset_source: str
    dataset_sha256: str
    total_images: int
    total_annotations: int
    total_categories: int
    classes: list[ClassAuditMetrics]
    target_classes: list[str]
    small_objects_count: int
    small_objects_percentage: float
    class_imbalance_ratio: float
    majority_class: str
    minority_class: str
    invalid_boxes_count: int
    duplicate_pairs_count: int
    duplicate_pairs: list[DuplicateImagePair] = Field(default_factory=list)
    duplicate_groups_count: int
    collapsed_redundant_images_count: int
    m3_passes_before_collapse: bool
    m3_passes_after_collapse: bool
    discrepancies: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Independent Computation Engine
# ---------------------------------------------------------------------------


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 digest of a file in 64 KiB chunks."""
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def audit_invalid_boxes(raw_coco: dict[str, Any]) -> tuple[set[int], list[dict[str, Any]]]:
    """Independently detect degenerate and out-of-bounds bounding boxes.

    Returns:
        tuple of (set of invalid annotation ids, list of detailed issues)
    """
    image_sizes: dict[int, tuple[float, float]] = {}
    for img in raw_coco.get("images", []):
        if isinstance(img, dict) and "id" in img and "width" in img and "height" in img:
            image_sizes[int(img["id"])] = (float(img["width"]), float(img["height"]))

    invalid_ids: set[int] = set()
    issues: list[dict[str, Any]] = []

    for ann in raw_coco.get("annotations", []):
        if not isinstance(ann, dict):
            continue
        ann_id = int(ann.get("id", -1))
        box = ann.get("bbox")
        if not isinstance(box, list) or len(box) != 4:
            invalid_ids.add(ann_id)
            issues.append({"id": ann_id, "reason": "malformed_bbox"})
            continue

        try:
            x, y, w, h = (float(v) for v in box)
        except (ValueError, TypeError):
            invalid_ids.add(ann_id)
            issues.append({"id": ann_id, "reason": "non_numeric_bbox"})
            continue

        reasons: list[str] = []
        if w <= 0:
            reasons.append("nonpositive_width")
        if h <= 0:
            reasons.append("nonpositive_height")

        img_size = image_sizes.get(int(ann.get("image_id", -1)))
        if img_size is not None:
            img_w, img_h = img_size
            if x < 0 or y < 0 or x >= img_w or y >= img_h:
                reasons.append("coordinate_outside_image")
            if w > 0 and h > 0 and (x + w > img_w or y + h > img_h):
                reasons.append("exceeds_image_bounds")

        area = ann.get("area")
        if (
            isinstance(area, (int, float))
            and not isinstance(area, bool)
            and not isclose(float(area), w * h, rel_tol=1e-9, abs_tol=1e-9)
        ):
            reasons.append("area_mismatch")

        if reasons:
            invalid_ids.add(ann_id)
            issues.append({"id": ann_id, "reasons": reasons})

    return invalid_ids, issues


def audit_transitive_duplicate_groups(duplicate_pairs: list[tuple[int, int]]) -> list[set[int]]:
    """Cluster duplicate pairs into transitive equivalence groups via Disjoint Set Union."""
    parent: dict[int, int] = {}

    def find(i: int) -> int:
        if parent[i] != i:
            parent[i] = find(parent[i])
        return parent[i]

    def union(i: int, j: int) -> None:
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            parent[root_i] = root_j

    for a, b in duplicate_pairs:
        if a not in parent:
            parent[a] = a
        if b not in parent:
            parent[b] = b
        union(a, b)

    groups_map: dict[int, set[int]] = defaultdict(set)
    for node in parent:
        groups_map[find(node)].add(node)

    return list(groups_map.values())


def collapse_duplicates_per_class(
    valid_images_by_class: dict[str, set[int]],
    duplicate_groups: list[set[int]],
) -> tuple[dict[str, int], int]:
    """Collapse duplicate image clusters into single representatives per class.

    Preserves class presence evidence: if any image in a cluster has annotations for a class,
    the collapsed representative counts once for that class.

    Returns:
        tuple of (distinct counts per class after collapse, total redundant images removed)
    """
    # Map each image id to its canonical cluster representative (min id in cluster)
    canonical_repr: dict[int, int] = {}
    redundant_count = 0
    for group in duplicate_groups:
        rep = min(group)
        for img_id in group:
            canonical_repr[img_id] = rep
        redundant_count += len(group) - 1

    collapsed_counts: dict[str, int] = {}
    for class_name, img_ids in valid_images_by_class.items():
        collapsed_set: set[int] = set()
        for img_id in img_ids:
            # If part of a cluster, map to cluster representative; otherwise keep self
            collapsed_set.add(canonical_repr.get(img_id, img_id))
        collapsed_counts[class_name] = len(collapsed_set)

    return collapsed_counts, redundant_count


def audit_small_objects(
    raw_coco: dict[str, Any],
    excluded_ann_ids: set[int],
    max_width: float = 32.0,
    max_height: float = 32.0,
) -> tuple[int, float]:
    """Independently calculate small object count and percentage among valid annotations."""
    total_valid = 0
    small_count = 0

    for ann in raw_coco.get("annotations", []):
        if not isinstance(ann, dict):
            continue
        ann_id = int(ann.get("id", -1))
        if ann_id in excluded_ann_ids:
            continue

        box = ann.get("bbox")
        if not isinstance(box, list) or len(box) != 4:
            continue

        w, h = float(box[2]), float(box[3])
        total_valid += 1
        if w <= max_width and h <= max_height:
            small_count += 1

    percentage = (small_count / total_valid * 100.0) if total_valid > 0 else 0.0
    return small_count, percentage


def audit_class_imbalance(image_counts: dict[str, int]) -> tuple[float, str, str]:
    """Calculate ratio of majority to minority class among active target categories."""
    active = {k: v for k, v in image_counts.items() if v > 0}
    if len(active) < 2:
        return 1.0, next(iter(active.keys()), "none"), next(iter(active.keys()), "none")

    sorted_classes = sorted(active.items(), key=lambda item: (-item[1], item[0]))
    majority_class, max_count = sorted_classes[0]
    minority_class, min_count = sorted_classes[-1]
    ratio = max_count / min_count if min_count > 0 else float("inf")
    return ratio, majority_class, minority_class


def image_references_from_coco(raw_coco: dict[str, Any], image_root: Path) -> list[ImageReference]:
    """Resolve every COCO ``file_name`` below ``image_root`` for pHash analysis.

    A missing file is an audit error rather than a silently skipped sample: skipping it
    would make the duplicate and post-collapse M3 result incomplete.
    """
    root = image_root.resolve()
    references: list[ImageReference] = []
    missing: list[str] = []

    for image in raw_coco.get("images", []):
        if not isinstance(image, dict):
            continue
        image_id = image.get("id")
        file_name = image.get("file_name")
        if not isinstance(image_id, int) or not isinstance(file_name, str):
            raise ValueError(
                "Each COCO image needs integer id and string file_name for pHash audit."
            )

        resolved_path = (root / file_name).resolve()
        if not resolved_path.is_relative_to(root):
            raise ValueError(f"COCO file_name escapes image root: {file_name}")
        if not resolved_path.is_file():
            missing.append(file_name)
            continue
        references.append(ImageReference(image_id=image_id, path=resolved_path))

    if missing:
        shown = ", ".join(sorted(missing)[:5])
        suffix = "..." if len(missing) > 5 else ""
        raise ValueError(f"Missing {len(missing)} COCO image files below {root}: {shown}{suffix}")
    return references


# ---------------------------------------------------------------------------
# Comprehensive Audit Runner
# ---------------------------------------------------------------------------


def run_independent_audit(
    source_path: Path,
    target_classes: list[str],
    duplicate_pairs: list[tuple[int, int]] | None = None,
    image_root: Path | None = None,
    phash_config: PerceptualHashConfig | None = None,
    min_images_per_class: int = 300,
) -> OverallAuditReport:
    """Execute complete independent audit and compare with system analyzers."""
    if duplicate_pairs is not None and image_root is not None:
        raise ValueError("Provide duplicate pairs or image_root for pHash, not both.")

    raw_coco = json.loads(source_path.read_text(encoding="utf-8"))
    sha256_hash = compute_sha256(source_path)

    # 1. Categories
    category_id_to_name: dict[int, str] = {}
    category_name_to_id: dict[str, int] = {}
    for cat in raw_coco.get("categories", []):
        if isinstance(cat, dict) and "id" in cat and "name" in cat:
            category_id_to_name[int(cat["id"])] = str(cat["name"])
            category_name_to_id[str(cat["name"])] = int(cat["id"])

    # 2. Independent invalid box detection
    invalid_ann_ids, invalid_issues = audit_invalid_boxes(raw_coco)

    # 3. Independent per-class image sets (before collapse)
    raw_images_by_class: dict[str, set[int]] = defaultdict(set)
    valid_images_by_class: dict[str, set[int]] = defaultdict(set)
    valid_boxes_by_class: dict[str, int] = defaultdict(int)
    invalid_boxes_by_class: dict[str, int] = defaultdict(int)
    total_boxes_by_class: dict[str, int] = defaultdict(int)

    for ann in raw_coco.get("annotations", []):
        if not isinstance(ann, dict):
            continue
        ann_id = int(ann.get("id", -1))
        img_id = int(ann.get("image_id", -1))
        cat_id = int(ann.get("category_id", -1))
        cat_name = category_id_to_name.get(cat_id)
        if not cat_name:
            continue

        total_boxes_by_class[cat_name] += 1
        raw_images_by_class[cat_name].add(img_id)

        if ann_id in invalid_ann_ids:
            invalid_boxes_by_class[cat_name] += 1
        else:
            valid_boxes_by_class[cat_name] += 1
            valid_images_by_class[cat_name].add(img_id)

    # 4. Transitive duplicate collapse
    duplicate_details: list[DuplicateImagePair] = []
    if image_root is not None:
        duplicate_result = find_near_duplicate_images(
            image_references_from_coco(raw_coco, image_root), config=phash_config
        )
        duplicate_details = duplicate_result.pairs
        pairs = [(pair.image_id_a, pair.image_id_b) for pair in duplicate_details]
    else:
        pairs = duplicate_pairs or []
    duplicate_groups = audit_transitive_duplicate_groups(pairs)
    collapsed_counts, redundant_removed = collapse_duplicates_per_class(
        valid_images_by_class, duplicate_groups
    )

    # 5. Build ClassAuditMetrics
    class_metrics_list: list[ClassAuditMetrics] = []
    m3_all_pass_before = True
    m3_all_pass_after = True

    for cname in target_classes:
        cid = category_name_to_id.get(cname, -1)
        valid_before = len(valid_images_by_class.get(cname, set()))
        valid_after = collapsed_counts.get(cname, 0)
        meets_before = valid_before >= min_images_per_class
        meets_after = valid_after >= min_images_per_class

        if not meets_before:
            m3_all_pass_before = False
        if not meets_after:
            m3_all_pass_after = False

        deficit = max(0, min_images_per_class - valid_after)

        class_metrics_list.append(
            ClassAuditMetrics(
                category_id=cid,
                category_name=cname,
                total_boxes=total_boxes_by_class.get(cname, 0),
                valid_boxes=valid_boxes_by_class.get(cname, 0),
                invalid_boxes=invalid_boxes_by_class.get(cname, 0),
                distinct_images_raw=len(raw_images_by_class.get(cname, set())),
                distinct_images_valid_before_collapse=valid_before,
                distinct_images_valid_after_collapse=valid_after,
                m3_threshold=min_images_per_class,
                meets_m3_before_collapse=meets_before,
                meets_m3_after_collapse=meets_after,
                deficit_after_collapse=deficit,
            )
        )

    # 6. Small objects and imbalance
    small_count, small_pct = audit_small_objects(raw_coco, invalid_ann_ids, 32.0, 32.0)
    imbalance_ratio, majority, minority = audit_class_imbalance(
        {c: len(valid_images_by_class.get(c, set())) for c in target_classes}
    )

    # 7. Cross-check with production analyzers
    discrepancies: list[str] = []

    # Cross-check invalid boxes with DQ-05
    prod_invalid = detect_invalid_boxes(raw_coco)
    if len(prod_invalid.invalid_boxes) != len(invalid_ann_ids):
        discrepancies.append(
            f"Invalid box count mismatch: audit={len(invalid_ann_ids)}, "
            f"prod={len(prod_invalid.invalid_boxes)}"
        )

    # Cross-check small objects with DQ-04
    dataset = CocoDataset.model_validate(
        {
            **raw_coco,
            "annotations": [
                annotation
                for annotation in raw_coco.get("annotations", [])
                if isinstance(annotation, dict)
                and int(annotation.get("id", -1)) not in invalid_ann_ids
            ],
        }
    )
    prod_small = analyze_small_objects(
        dataset, SmallObjectsConfig(max_width=32, max_height=32, sample_limit=10)
    )
    if not isclose(prod_small.percentage, small_pct, rel_tol=1e-4, abs_tol=1e-4):
        discrepancies.append(
            f"Small objects percentage mismatch: audit={small_pct:.4f}, "
            f"prod={prod_small.percentage:.4f}"
        )

    # Cross-check class imbalance with DQ-04
    prod_imbalance = analyze_class_imbalance(
        dataset, ClassImbalanceConfig(min_images_per_class=min_images_per_class)
    )
    if not isclose(prod_imbalance.imbalance_ratio, imbalance_ratio, rel_tol=1e-4, abs_tol=1e-4):
        discrepancies.append(
            f"Imbalance ratio mismatch: audit={imbalance_ratio:.4f}, "
            f"prod={prod_imbalance.imbalance_ratio:.4f}"
        )

    return OverallAuditReport(
        dataset_source=str(source_path),
        dataset_sha256=sha256_hash,
        total_images=len(raw_coco.get("images", [])),
        total_annotations=len(raw_coco.get("annotations", [])),
        total_categories=len(raw_coco.get("categories", [])),
        classes=class_metrics_list,
        target_classes=target_classes,
        small_objects_count=small_count,
        small_objects_percentage=round(small_pct, 4),
        class_imbalance_ratio=round(imbalance_ratio, 4),
        majority_class=majority,
        minority_class=minority,
        invalid_boxes_count=len(invalid_ann_ids),
        duplicate_pairs_count=len(pairs),
        duplicate_pairs=duplicate_details,
        duplicate_groups_count=len(duplicate_groups),
        collapsed_redundant_images_count=redundant_removed,
        m3_passes_before_collapse=m3_all_pass_before,
        m3_passes_after_collapse=m3_all_pass_after,
        discrepancies=discrepancies,
    )


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="DQ-07: Independent Quality and M3 Dataset Audit")
    parser.add_argument("source", type=Path, help="Path to raw COCO dataset JSON")
    parser.add_argument(
        "--target-classes",
        nargs="+",
        default=["person", "car"],
        help="Target category names (default: person car)",
    )
    parser.add_argument(
        "--min-images",
        type=int,
        default=300,
        help="Minimum distinct images threshold per class (default: 300)",
    )
    parser.add_argument(
        "--duplicate-pairs",
        type=Path,
        default=None,
        help="Optional JSON file with list of [id_a, id_b] duplicate pairs",
    )
    parser.add_argument(
        "--image-root",
        type=Path,
        default=None,
        help="Directory containing every COCO file_name; calculates pHash duplicate pairs",
    )
    parser.add_argument(
        "--phash-max-distance",
        type=int,
        default=8,
        help="Maximum pHash Hamming distance for near duplicates (default: 8)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional destination path to write audit JSON report",
    )
    args = parser.parse_args()

    if args.duplicate_pairs and args.image_root:
        parser.error("--duplicate-pairs and --image-root are mutually exclusive")

    pairs: list[tuple[int, int]] | None = None
    if args.duplicate_pairs and args.duplicate_pairs.exists():
        raw_pairs = json.loads(args.duplicate_pairs.read_text(encoding="utf-8"))
        pairs = [(p[0], p[1]) for p in raw_pairs]

    report = run_independent_audit(
        source_path=args.source,
        target_classes=args.target_classes,
        duplicate_pairs=pairs,
        image_root=args.image_root,
        phash_config=PerceptualHashConfig(max_distance=args.phash_max_distance),
        min_images_per_class=args.min_images,
    )

    report_json = report.model_dump_json(indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report_json, encoding="utf-8")

    print(report_json)


if __name__ == "__main__":
    main()
