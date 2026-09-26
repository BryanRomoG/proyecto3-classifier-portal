"""CLI for the DVC `split` stage: generate train/val/test splits, blocked by a failed gate.

Reads the persisted quality.json (from the separate quality_gate stage/process) and checks
its overall_status directly, rather than reconstructing an in-memory QualityGateDecision —
there's no shared process state across two separate DVC stage invocations to reconstruct it
from, and the report's own status field is exactly what `.require()` would check anyway.
"""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path

from dataset_quality.analyzers.m3 import load_coco_dataset
from dataset_quality.config.models import SplitConfig
from dataset_quality.splits.generator import generate_splits


def main() -> None:
    parser = ArgumentParser(description="Generate train/val/test splits, gated on quality.json.")
    parser.add_argument("source", type=Path, help="Path to the canonicalized COCO JSON")
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--duplicate-pairs", type=Path, required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--train", type=float, required=True)
    parser.add_argument("--val", type=float, required=True)
    parser.add_argument("--test", type=float, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    parser.add_argument("--assignment-output", type=Path, required=True)
    args = parser.parse_args()

    quality_report = json.loads(args.quality_report.read_text(encoding="utf-8"))
    if quality_report["overall_status"] == "fail":
        print(
            "[split] Quality Gate failed; split is blocked (matches "
            "QualityGateDecision.require('split') semantics).",
            file=sys.stderr,
        )
        raise SystemExit(1)

    dataset = load_coco_dataset(args.source)
    duplicate_pairs = [
        (a, b) for a, b in json.loads(args.duplicate_pairs.read_text(encoding="utf-8"))
    ]
    config = SplitConfig(train=args.train, val=args.val, test=args.test, seed=args.seed)

    result = generate_splits(
        dataset,
        config,
        dataset_version=args.dataset_version,
        duplicate_pairs=duplicate_pairs,
    )

    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(result.report.model_dump_json(indent=2), encoding="utf-8")
    args.assignment_output.parent.mkdir(parents=True, exist_ok=True)
    args.assignment_output.write_text(json.dumps(result.assignment, indent=2), encoding="utf-8")

    print(result.report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
