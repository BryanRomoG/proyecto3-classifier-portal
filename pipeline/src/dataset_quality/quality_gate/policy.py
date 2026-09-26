"""Load and evaluate the YAML-driven Quality Gate policy."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import yaml

from dataset_quality.ingestion.models import CocoDataset
from dataset_quality.quality_gate.models import (
    QualityCheckResult,
    QualityDatasetSummary,
    QualityPolicy,
    QualityReport,
)


def load_policy(path: Path) -> QualityPolicy:
    """Load a top-level check mapping from a YAML policy file."""

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("quality policy YAML must contain a top-level mapping")
    return QualityPolicy.from_mapping(payload)


def evaluate_policy(
    policy: QualityPolicy,
    observations: Mapping[str, float | int],
    dataset_version: str,
    generated_at: datetime | None = None,
    dataset: CocoDataset | None = None,
) -> QualityReport:
    """Turn analyzer observations into a report using policy thresholds and severities.

    ``dataset`` is optional and additive: when passed, the returned report's
    ``dataset_summary`` (APP-05, total images/bounding boxes/categories) is
    computed from it. Existing callers that only have per-check observations
    and no full ``CocoDataset`` in hand keep working unchanged, with
    ``dataset_summary`` left as ``None``.
    """

    results: list[QualityCheckResult] = []
    for check_id, check in policy.checks.items():
        if check_id not in observations:
            raise ValueError(f"missing observation for quality check: {check_id}")

        observed = float(observations[check_id])
        passed = (
            observed >= check.threshold
            if check.comparison == "min"
            else observed <= check.threshold
        )
        status = "pass" if passed else check.severity
        results.append(
            QualityCheckResult(
                id=check_id,
                label=check.label,
                severity=check.severity,
                status=status,
                threshold=check.threshold,
                observed=observed,
                unit=check.unit,
            )
        )

    overall_status = _worst_status(result.status for result in results)
    dataset_summary = (
        QualityDatasetSummary(
            total_images=len(dataset.images),
            total_bounding_boxes=len(dataset.annotations),
            total_categories=len(dataset.categories),
        )
        if dataset is not None
        else None
    )
    return QualityReport(
        dataset_version=dataset_version,
        generated_at=generated_at or datetime.now(UTC),
        overall_status=overall_status,
        checks=results,
        dataset_summary=dataset_summary,
    )


def _worst_status(statuses: list[str] | object) -> str:
    priority = {"pass": 0, "warn": 1, "fail": 2}
    return max(statuses, key=lambda status: priority[str(status)])
