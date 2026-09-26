"""Pydantic v2 models for quality-policy and split configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QualityCheckConfig(BaseModel):
    """Threshold and release severity for a single quality check."""

    model_config = ConfigDict(extra="forbid")

    threshold: float
    severity: Literal["warn", "fail"]


class QualityConfig(BaseModel):
    """Collection of independently configurable quality checks."""

    model_config = ConfigDict(extra="forbid")

    checks: dict[str, QualityCheckConfig]


class SplitConfig(BaseModel):
    """Reproducible train/validation/test proportions."""

    model_config = ConfigDict(extra="forbid")

    train: float = Field(gt=0, lt=1)
    val: float = Field(gt=0, lt=1)
    test: float = Field(gt=0, lt=1)
    seed: int

    @model_validator(mode="after")
    def proportions_must_sum_to_one(self) -> SplitConfig:
        total = self.train + self.val + self.test
        if abs(total - 1.0) > 1e-9:
            raise ValueError("split proportions must sum to one")
        return self
