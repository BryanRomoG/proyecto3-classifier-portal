"""Pydantic models for the configurable Quality Gate policy and report contract."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

Severity = Literal["warn", "fail"]
CheckStatus = Literal["pass", "warn", "fail"]
Comparison = Literal["min", "max"]


class QualityPolicyCheck(BaseModel):
    """One threshold rule read from ``quality.yaml``."""

    model_config = {"extra": "forbid"}

    label: str = Field(min_length=1)
    threshold: float
    severity: Severity
    comparison: Comparison
    unit: str = Field(min_length=1)


class QualityPolicy(BaseModel):
    """Validated policy mapping whose keys are stable quality-check identifiers."""

    model_config = {"extra": "forbid"}

    checks: dict[str, QualityPolicyCheck] = Field(min_length=1)

    @classmethod
    def from_mapping(cls, checks: Mapping[str, Any]) -> QualityPolicy:
        """Validate the top-level mapping used directly by ``quality.yaml``."""

        return cls.model_validate({"checks": dict(checks)})

    @model_validator(mode="after")
    def require_minimum_images_policy(self) -> QualityPolicy:
        minimum_images = self.checks.get("min_images_per_class")
        if minimum_images is None:
            raise ValueError("quality policy must define min_images_per_class")
        if minimum_images.threshold < 300:
            raise ValueError("min_images_per_class threshold must be at least 300")
        if minimum_images.severity != "fail":
            raise ValueError("min_images_per_class severity must be fail")
        return self


class QualityCheckResult(BaseModel):
    """One Quality Gate result, compatible with the APP-01 contract proposal."""

    model_config = {"extra": "forbid"}

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    severity: Severity
    status: CheckStatus
    threshold: float
    observed: float
    unit: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)
    offending_samples: list[dict[str, Any]] = Field(default_factory=list)


class QualityDatasetSummary(BaseModel):
    """Dataset-level totals shown on the Overview screen (APP-05).

    None of these are derivable from a single ``QualityCheckResult`` — they
    describe the dataset as a whole, not one check's observation — so they
    live as their own optional block on ``QualityReport`` rather than being
    bolted onto an existing check.
    """

    model_config = {"extra": "forbid"}

    total_images: int = Field(ge=0)
    total_bounding_boxes: int = Field(ge=0)
    total_categories: int = Field(ge=0)


class QualityReport(BaseModel):
    """Serialized Quality Gate output consumed by downstream services."""

    model_config = {"extra": "forbid"}

    dataset_version: str = Field(min_length=1)
    generated_at: datetime
    overall_status: CheckStatus
    checks: list[QualityCheckResult] = Field(min_length=1)
    # Optional and defaulted so existing callers of `evaluate_policy()` that
    # don't pass a `CocoDataset` (and any report built before APP-05) keep
    # validating unchanged — see `evaluate_policy`'s `dataset` parameter.
    dataset_summary: QualityDatasetSummary | None = None
