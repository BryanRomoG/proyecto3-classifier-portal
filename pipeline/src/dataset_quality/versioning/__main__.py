"""CLI for the DVC `release` stage: assemble the dataset version record.

Computes a real semantic-version diff against the previous release (OPS-07) using a
small git-tracked ledger, `pipeline/data/version_history.json` (`VersionHistory` in
`versioning/models.py`) — never the dataset itself, just enough numeric state per
release to diff against. Deliberately kept out of `dvc.yaml`'s deps/outs: see
`versioning.models.VersionHistory`'s docstring for why.

The first release in the ledger must be exactly `v1.0.0`; every later stamped version
must be strictly greater (MAJOR.MINOR.PATCH tuple order) than the last recorded one, or
this fails loud rather than silently overwriting history — same "crash you notice beats
a false pass you don't" discipline as OPS-04's `DuplicateBytesUnavailableError`.

Sign convention for `VersionDiff` (`copilot/contracts.py`) — see `pipeline/README.md`'s
"Dataset release & versioning" section for the full human-readable version of this:
`images_added`/`boxes_added` are signed deltas (current minus previous release) —
negative means removed, there is no separate "removed" field. `classes_left_minimum`
lists only categories that *newly* dropped below `min_images_per_class`'s real
threshold (read from `quality.yaml`, not hardcoded) in this release, i.e. they were at
or above it last release and are below it now — a regression signal, not just "currently
below". `small_object_ratio_change_pct` is a percentage-point delta (current percent
minus previous percent), not a ratio-of-ratios.

Reuses APP-06's `VersionsReport`/`VersionDiff`/`DatasetVersionEntry` models
(`copilot/contracts.py`) instead of duplicating them. Still does NOT write to
`contracts/versions.json` — see OPS-04's original docstring for why (established
mock-file boundary between the pipeline and the frontend/Copilot, unchanged here).
"""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from datetime import UTC, datetime
from pathlib import Path

from dataset_quality.analyzers.m3 import source_sha256
from dataset_quality.copilot.contracts import (
    DatasetVersionEntry,
    EnvironmentStatus,
    VersionDiff,
    VersionEnvironments,
    VersionsReport,
)
from dataset_quality.quality_gate.policy import load_policy
from dataset_quality.versioning.models import VersionHistory, VersionHistoryEntry, VersionSnapshot

_SEMVER_PARTS = 3  # MAJOR.MINOR.PATCH — see module docstring; no prerelease suffixes


def _parse_semver(version: str) -> tuple[int, int, int]:
    error = ValueError(f"dataset version {version!r} must be v<MAJOR>.<MINOR>.<PATCH>, e.g. v1.0.0")
    if not version.startswith("v"):
        raise error
    parts = version[1:].split(".")
    if len(parts) != _SEMVER_PARTS or not all(part.isdigit() for part in parts):
        raise error
    major, minor, patch = (int(part) for part in parts)
    return major, minor, patch


def _load_history(path: Path) -> VersionHistory:
    if not path.exists():
        return VersionHistory()
    return VersionHistory.model_validate_json(path.read_text(encoding="utf-8"))


def _snapshot_from(m3_baseline: dict, observations: dict) -> VersionSnapshot:
    return VersionSnapshot(
        image_count=m3_baseline["total_images"],
        box_count=m3_baseline["total_annotations"],
        per_class_counts={
            entry["category"]: entry["distinct_images_with_valid_box"]
            for entry in m3_baseline["classes"]
        },
        small_object_percentage=observations["small_objects"],
    )


def _diff(
    current: VersionSnapshot, previous: VersionSnapshot, min_images_threshold: float
) -> VersionDiff:
    left_minimum = sorted(
        category
        for category, count in current.per_class_counts.items()
        if count < min_images_threshold
        and previous.per_class_counts.get(category, 0) >= min_images_threshold
    )
    return VersionDiff(
        images_added=current.image_count - previous.image_count,
        boxes_added=current.box_count - previous.box_count,
        classes_left_minimum=left_minimum,
        small_object_ratio_change_pct=(
            current.small_object_percentage - previous.small_object_percentage
        ),
    )


def main() -> None:
    parser = ArgumentParser(description="Assemble the dataset version record.")
    parser.add_argument("--coco", type=Path, required=True, help="Canonicalized COCO JSON")
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--m3-baseline", type=Path, required=True, help="validate stage's output")
    parser.add_argument("--observations", type=Path, required=True, help="analyze stage's output")
    parser.add_argument(
        "--policy", type=Path, required=True, help="quality.yaml, for the real threshold"
    )
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument(
        "--history", type=Path, required=True, help="git-tracked version_history.json ledger"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    current_version = _parse_semver(args.dataset_version)
    history = _load_history(args.history)

    if history.entries:
        previous_version = _parse_semver(history.entries[-1].entry.version)
        if current_version <= previous_version:
            raise ValueError(
                f"dataset version {args.dataset_version!r} must be strictly greater than "
                f"the last released version {history.entries[-1].entry.version!r}"
            )
    elif current_version != (1, 0, 0):
        raise ValueError(f"the first dataset release must be v1.0.0, got {args.dataset_version!r}")

    quality_report = json.loads(args.quality_report.read_text(encoding="utf-8"))
    if quality_report["overall_status"] == "fail":
        print(
            "[release] Quality Gate failed; release is blocked (a red gate never "
            "produces a versioned, promotable dataset).",
            file=sys.stderr,
        )
        raise SystemExit(1)

    m3_baseline = json.loads(args.m3_baseline.read_text(encoding="utf-8"))
    observations = json.loads(args.observations.read_text(encoding="utf-8"))
    policy = load_policy(args.policy)
    min_images_threshold = policy.checks["min_images_per_class"].threshold

    snapshot = _snapshot_from(m3_baseline, observations)
    diff = (
        _diff(snapshot, history.entries[-1].snapshot, min_images_threshold)
        if history.entries
        else None
    )

    now = datetime.now(UTC)
    entry = DatasetVersionEntry(
        version=args.dataset_version,
        released_at=now,
        content_hash=source_sha256(args.coco),
        quality_status=quality_report["overall_status"],
        environments=VersionEnvironments(
            dev=EnvironmentStatus(provider="minio", status="available", synced_at=now),
            prod=EnvironmentStatus(provider="s3", status="pending", synced_at=None),
        ),
        diff_from_previous=diff,
    )

    history.entries.append(VersionHistoryEntry(entry=entry, snapshot=snapshot))
    args.history.parent.mkdir(parents=True, exist_ok=True)
    args.history.write_text(history.model_dump_json(indent=2), encoding="utf-8")

    report = VersionsReport(
        current_version=args.dataset_version,
        versions=[history_entry.entry for history_entry in history.entries],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
