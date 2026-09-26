"""CLI for the DVC `ingest` stage: validate a raw COCO export, write a canonical copy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dataset_quality.analyzers.m3 import load_coco_dataset, source_sha256


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a raw COCO export and write a canonicalized copy."
    )
    parser.add_argument("source", type=Path, help="Path to the raw COCO JSON export")
    parser.add_argument(
        "--output", type=Path, required=True, help="Where to write the canonicalized COCO JSON"
    )
    args = parser.parse_args()

    # Raises pydantic.ValidationError (non-zero exit) on a structurally invalid COCO file —
    # this is the "validate" half of ingest; there is no separate parsing step to duplicate.
    dataset = load_coco_dataset(args.source)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(dataset.model_dump_json(indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "source_name": args.source.name,
                "source_sha256": source_sha256(args.source),
                "images": len(dataset.images),
                "annotations": len(dataset.annotations),
                "categories": len(dataset.categories),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
