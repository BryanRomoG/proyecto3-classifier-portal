"""CLI for the DVC `analyze` stage: run the four analyzers and assemble the Quality Gate's
observations.json (matching what quality_gate.runner.execute_quality_gate expects — a flat
{check_id: value} mapping, one entry per check in quality.yaml; evaluate_policy() raises if
any declared check is missing, so every check needs a real value, `duplicates` included).

`min_images_per_class` isn't computed here: it comes from the separate `validate` stage's
M3 baseline (data/interim/m3_baseline.json), folded in as the minimum distinct-image count
across the target categories — that IS what "minimum images per class" means.

Duplicate detection needs actual image pixels (find_near_duplicate_images opens files via
PIL). The COCO export only carries each image's original filename, not its MinIO
storage_key — but COCO image ids are the same as the backend's `images.id` (coco-export
reuses DB ids as-is), so this looks storage_key up by id and downloads each object from the
configured object store.

`duplicates` is a `severity: fail` check in quality.yaml — Data Quality Engineer's own
policy treats it as release-blocking. If the DB/object store isn't reachable, this stage
fails closed (raises, non-zero exit, no quality.json produced) rather than reporting
`duplicates: 0`: a fabricated "0" would let a dataset that was never actually checked for
duplicates sail through a check specifically designed to block on them. A crash you notice
is safer than a false pass you don't.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from sqlalchemy import text

from dataset_quality.analyzers.dq04 import (
    ClassImbalanceConfig,
    SmallObjectsConfig,
    analyze_class_imbalance,
    analyze_small_objects,
)
from dataset_quality.analyzers.dq05 import (
    ImageReference,
    detect_invalid_boxes,
    find_near_duplicate_images,
)
from dataset_quality.analyzers.dq06 import analyze_spatial_bias
from dataset_quality.analyzers.m3 import load_coco_dataset
from dataset_quality.config.clients import get_db_engine
from dataset_quality.storage.object_store import ObjectStore


class DuplicateBytesUnavailableError(RuntimeError):
    """Raised when real image bytes can't be resolved for the duplicates check.

    Deliberately lets this propagate and crash the `analyze` stage rather than being
    caught anywhere — see module docstring for why a crash is the safer failure mode
    here than a fabricated `duplicates: 0`.
    """


def _find_duplicates(image_ids: list[int]) -> list[tuple[int, int]]:
    """Real pHash duplicate pairs, fetched from the configured DB/object store.

    Returned pairs feed both the quality_gate observation (as a count) and the
    split stage's leakage prevention (generate_splits(duplicate_pairs=...)).
    Raises DuplicateBytesUnavailableError if the images can't be resolved — see
    module docstring.
    """

    engine = get_db_engine()
    with engine.connect() as conn, tempfile.TemporaryDirectory() as tmp_dir:
        rows = (
            conn.execute(
                text("SELECT id, storage_key FROM images WHERE id IN :ids"),
                {"ids": tuple(image_ids)},
            ).fetchall()
            if image_ids
            else []
        )
        if len(rows) != len(image_ids):
            missing = sorted(set(image_ids) - {row[0] for row in rows})
            raise DuplicateBytesUnavailableError(
                f"images table is missing {len(missing)} of {len(image_ids)} referenced "
                f"image ids (e.g. {missing[:5]}) — duplicates cannot be measured for real "
                "against this DB."
            )

        store = ObjectStore.from_settings()
        references = []
        for image_id, storage_key in rows:
            local_path = Path(tmp_dir) / f"{image_id}"
            local_path.write_bytes(store.get_bytes(storage_key))
            references.append(ImageReference(image_id=image_id, path=local_path))

        result = find_near_duplicate_images(references)
        return [(pair.image_id_a, pair.image_id_b) for pair in result.pairs]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the quality analyzers against a COCO dataset."
    )
    parser.add_argument("source", type=Path, help="Path to the canonicalized COCO JSON")
    parser.add_argument("--m3-baseline", type=Path, required=True, help="validate stage's output")
    parser.add_argument("--small-object-max-width", type=int, required=True)
    parser.add_argument("--small-object-max-height", type=int, required=True)
    parser.add_argument("--class-imbalance-min-images", type=int, required=True)
    parser.add_argument("--spatial-grid-size", type=int, default=3)
    parser.add_argument(
        "--output", type=Path, required=True, help="Where to write observations.json"
    )
    parser.add_argument(
        "--duplicate-pairs-output",
        type=Path,
        required=True,
        help="Where to write duplicate_pairs.json",
    )
    args = parser.parse_args()

    dataset = load_coco_dataset(args.source)
    raw = json.loads(args.source.read_text(encoding="utf-8"))
    m3_baseline = json.loads(args.m3_baseline.read_text(encoding="utf-8"))

    small_objects = analyze_small_objects(
        dataset,
        SmallObjectsConfig(
            max_width=args.small_object_max_width,
            max_height=args.small_object_max_height,
            sample_limit=10,
        ),
    )
    class_imbalance = analyze_class_imbalance(
        dataset, ClassImbalanceConfig(min_images_per_class=args.class_imbalance_min_images)
    )
    invalid_boxes = detect_invalid_boxes(raw)
    spatial_bias = analyze_spatial_bias(dataset, grid_size=args.spatial_grid_size)
    duplicate_pairs = _find_duplicates([image.id for image in dataset.images])

    min_images_per_class = min(
        entry["distinct_images_with_valid_box"] for entry in m3_baseline["classes"]
    )

    observations = {
        "min_images_per_class": min_images_per_class,
        "small_objects": small_objects.percentage,
        "class_imbalance": class_imbalance.imbalance_ratio,
        "duplicates": len(duplicate_pairs),
        "invalid_boxes": len(invalid_boxes.invalid_boxes),
        "spatial_bias": spatial_bias.max_cell_percentage,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(observations, indent=2), encoding="utf-8")
    args.duplicate_pairs_output.parent.mkdir(parents=True, exist_ok=True)
    args.duplicate_pairs_output.write_text(json.dumps(duplicate_pairs, indent=2), encoding="utf-8")
    print(json.dumps(observations, indent=2))


if __name__ == "__main__":
    main()
