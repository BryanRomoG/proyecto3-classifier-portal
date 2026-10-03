"""CLI for the DVC `classifier_split` stage: the new leak-free 70/20/10 manifest.

Reads the canonical COCO file, the T3-1.1 ``crops_manifest.json`` and the analyze stage's
``duplicate_pairs.json``, then writes ``classifier_split_manifest.json``. The inherited
image-level 70/15/15 ``split`` stage is not touched by this command.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dataset_quality.classifier_splits.errors import ClassifierSplitError
from dataset_quality.classifier_splits.generator import generate_classifier_split
from dataset_quality.config.models import SplitConfig


def main() -> None:
    args = _parse_args()
    config = SplitConfig(train=args.train, val=args.val, test=args.test, seed=args.seed)
    try:
        result = generate_classifier_split(
            coco_path=args.source,
            crops_manifest_path=args.crops_manifest,
            duplicate_pairs_path=args.duplicate_pairs,
            dataset_version=args.dataset_version,
            config=config,
        )
    except ClassifierSplitError as error:
        print(f"[classifier_split] {error}", file=sys.stderr)
        raise SystemExit(1) from error

    payload = result.manifest.model_dump_json(indent=2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # LF on every OS: the manifest is identified by its SHA-256, which must not depend on it.
    args.output.write_text(payload, encoding="utf-8", newline="\n")
    print(payload)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the leak-free classifier split manifest from the COCO crops."
    )
    parser.add_argument("source", type=Path, help="Path to the canonicalized COCO JSON")
    parser.add_argument("--crops-manifest", type=Path, required=True)
    parser.add_argument("--duplicate-pairs", type=Path, required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--train", type=float, required=True)
    parser.add_argument("--val", type=float, required=True)
    parser.add_argument("--test", type=float, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    main()
