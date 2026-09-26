"""Execution and downstream-stage guards for the YAML-driven Quality Gate."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from dataset_quality.quality_gate.models import QualityCheckResult, QualityReport
from dataset_quality.quality_gate.policy import evaluate_policy, load_policy

DownstreamStage = Literal["split", "export", "promotion"]


class QualityGateBlockedError(RuntimeError):
    """Raised when a failed quality report tries to enter a protected stage."""


class QualityGateDecision(BaseModel):
    """Report plus the executable outcome used by downstream pipeline stages."""

    report: QualityReport
    exit_code: int = Field(ge=0, le=1)

    def allows(self, stage: DownstreamStage) -> bool:
        """Return whether this quality result permits one protected stage."""

        del stage
        return self.report.overall_status != "fail"

    def require(self, stage: DownstreamStage) -> None:
        """Fail closed before a protected stage executes."""

        if not self.allows(stage):
            raise QualityGateBlockedError(f"Quality Gate failed; {stage} is blocked.")


def execute_quality_gate(
    *,
    policy_path: Path,
    observations: Mapping[str, float | int],
    dataset_version: str,
    report_path: Path,
    evidence_by_check: Mapping[str, Mapping[str, Any]] | None = None,
) -> QualityGateDecision:
    """Evaluate policy, persist ``quality.json``, and provide an executable decision."""

    report = evaluate_policy(load_policy(policy_path), observations, dataset_version)
    enriched_checks = [_with_evidence(check, evidence_by_check or {}) for check in report.checks]
    report = report.model_copy(update={"checks": enriched_checks})
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return QualityGateDecision(
        report=report,
        exit_code=1 if report.overall_status == "fail" else 0,
    )


def _with_evidence(
    check: QualityCheckResult, evidence_by_check: Mapping[str, Mapping[str, Any]]
) -> QualityCheckResult:
    evidence = evidence_by_check.get(check.id, {})
    details = evidence.get("details", {})
    offending_samples = evidence.get("offending_samples", [])
    if not isinstance(details, dict) or not isinstance(offending_samples, list):
        raise ValueError(f"evidence for quality check {check.id!r} has an invalid shape")
    return check.model_copy(update={"details": details, "offending_samples": offending_samples})


def main() -> int:
    """Run the Quality Gate from JSON observations and return its process exit code."""

    parser = argparse.ArgumentParser(description="Run the dataset Quality Gate")
    parser.add_argument("--policy", type=Path, default=Path("quality.yaml"))
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--report", type=Path, default=Path("quality.json"))
    args = parser.parse_args()
    payload = json.loads(args.observations.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("observations JSON must contain an object")
    decision = execute_quality_gate(
        policy_path=args.policy,
        observations=payload,
        dataset_version=args.dataset_version,
        report_path=args.report,
    )
    return decision.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
