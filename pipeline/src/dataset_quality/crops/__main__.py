"""CLI for the DVC `crop` stage: T3-1.1 crops for the classifier.

Like the `split` stage, this reads the persisted `quality.json` (produced by the
separate `quality_gate` stage) instead of reconstructing an in-process decision, and it
refuses to write anything when the gate failed: a failed gate means the dataset is not
fit to train on, so an "almost complete" crop set derived from it would be worse than
stopping.

The stage needs a populated backend — `images` rows in MariaDB plus the matching
objects in MinIO/S3 — and fails loudly if either is missing. See `pipeline/README.md`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dataset_quality.crops.generator import generate_crops
from dataset_quality.crops.sources import BackendImageStore, SourceImageStore


def main(source_store: SourceImageStore | None = None) -> None:
    """Run one crop pass; ``source_store`` is a test seam, the stage builds its own."""

    args = _parse_args()

    quality_report = json.loads(args.quality_report.read_text(encoding="utf-8"))
    if quality_report["overall_status"] == "fail":
        print(
            "[crop] Quality Gate failed; cropping is blocked (same fail-closed rule as "
            "the split stage).",
            file=sys.stderr,
        )
        raise SystemExit(1)

    store = source_store if source_store is not None else BackendImageStore.from_settings()
    result = generate_crops(
        coco_path=args.source,
        crops_root=args.crops_root,
        manifest_path=args.manifest_output,
        exclusions_path=args.exclusions_output,
        dataset_version=args.dataset_version,
        target_categories=args.categories,
        source_store=store,
    )
    print(result.manifest.summary.model_dump_json(indent=2))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate traceable COCO crops for the configured target classes."
    )
    parser.add_argument("source", type=Path, help="Path to the canonicalized COCO JSON")
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument(
        "--category",
        action="append",
        dest="categories",
        required=True,
        help="Target category name; repeat the flag for each target class",
    )
    parser.add_argument("--crops-root", type=Path, default=Path("data/processed/crops"))
    parser.add_argument(
        "--manifest-output",
        type=Path,
        default=Path("data/processed/crops_manifest.json"),
    )
    parser.add_argument(
        "--exclusions-output",
        type=Path,
        default=Path("data/processed/crop_exclusions.json"),
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
