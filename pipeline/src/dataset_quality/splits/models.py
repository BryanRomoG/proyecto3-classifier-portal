"""Pydantic v2 models for the Tier 4 splits output contract.

Mirrors ``contracts/splits.json`` / ``frontend/src/lib/contracts/schemas.ts``
(``splitsReportSchema``) field for field — see ``contracts/README.md``. Like
the Tier 3 contract in ``quality_gate.models``, every model here uses
``extra="forbid"`` so a shape drift between the pipeline, the mock contract
and the frontend Zod schema fails loudly instead of silently.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from dataset_quality.quality_gate.models import CheckStatus


class SplitProportions(BaseModel):
    """Configured train/validation/test proportions, echoed back in the report."""

    model_config = ConfigDict(extra="forbid")

    train: float
    val: float
    test: float


class SplitTotals(BaseModel):
    """Image counts per split plus the dataset total they must sum to."""

    model_config = ConfigDict(extra="forbid")

    images: int
    train: int
    val: int
    test: int


class SplitClassDistribution(BaseModel):
    """Number of images containing each class, per split."""

    model_config = ConfigDict(extra="forbid")

    train: dict[str, int]
    val: dict[str, int]
    test: dict[str, int]


class SplitLeakageCheck(BaseModel):
    """Result of checking that near-duplicate pairs never land in different splits."""

    model_config = ConfigDict(extra="forbid")

    status: CheckStatus
    leaked_pairs: int
    near_duplicate_pairs_checked: int
    near_duplicate_pairs_same_split: int


class SplitReproducibilityCheck(BaseModel):
    """Result of re-running generation with the same seed and comparing assignments."""

    model_config = ConfigDict(extra="forbid")

    status: CheckStatus
    note: str = Field(min_length=1)


class SplitResult(BaseModel):
    """Serialized Tier 4 output, compatible with the APP-01 splits.json contract."""

    model_config = ConfigDict(extra="forbid")

    dataset_version: str = Field(min_length=1)
    generated_at: datetime
    seed: int
    proportions: SplitProportions
    tolerance: float
    totals: SplitTotals
    class_distribution: SplitClassDistribution
    leakage_check: SplitLeakageCheck
    reproducibility_check: SplitReproducibilityCheck
