"""Pydantic models for contracts that don't have a strict model APP-06 can reuse yet.

``quality.json`` already has a strict model owned by DQ-02
(``quality_gate.models.QualityReport``, merged in ``main``) — reused directly.
``versions.json`` (Tier 5 / MLOps output) had no strict model at all yet, so
``VersionsReport`` below is APP-06's own minimal, read-only view of it (and
this ticket reconciles ``contracts/versions.json`` against it the same way
DQ-02 reconciled ``quality.json``).

``splits.json`` DOES have a strict model now (``splits.models.SplitResult``),
but it landed on the still-unmerged ``feat/app-04-stratified-splits`` branch —
APP-06 is only blocked by APP-01/DQ-02, not APP-04, so importing it here would
make this ticket depend on unmerged work it isn't supposed to. ``SplitsSummary``
is a deliberately loose stand-in (``extra="ignore"``, tolerant of the
``_contract``/``_note`` mock fields still on ``main``'s ``splits.json``) so the
Copilot's split tool works against `main` today. Once APP-04 merges, this can
be replaced by importing the real ``SplitResult`` — see the TODO below.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from dataset_quality.quality_gate.models import CheckStatus


class EnvironmentStatus(BaseModel):
    """Sync status of one dataset version in one environment (DEV or PROD)."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    status: str = Field(min_length=1)
    synced_at: datetime | None


class VersionEnvironments(BaseModel):
    """DEV (MinIO) and PROD (S3) sync status for one dataset version."""

    model_config = ConfigDict(extra="forbid")

    dev: EnvironmentStatus
    prod: EnvironmentStatus


class VersionDiff(BaseModel):
    """What changed between one dataset version and the one before it."""

    model_config = ConfigDict(extra="forbid")

    images_added: int
    boxes_added: int
    classes_left_minimum: list[str]
    small_object_ratio_change_pct: float


class DatasetVersionEntry(BaseModel):
    """One entry in the dataset version timeline."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1)
    released_at: datetime
    content_hash: str = Field(min_length=1)
    quality_status: CheckStatus
    environments: VersionEnvironments
    diff_from_previous: VersionDiff | None


class VersionsReport(BaseModel):
    """Serialized Tier 5 output: the dataset version timeline."""

    model_config = ConfigDict(extra="forbid")

    current_version: str = Field(min_length=1)
    versions: list[DatasetVersionEntry] = Field(min_length=1)


class SplitsSummary(BaseModel):
    """Loose read of ``splits.json`` for the Copilot only — see module docstring.

    TODO(APP-04 merge): replace this with
    ``dataset_quality.splits.models.SplitResult`` once
    ``feat/app-04-stratified-splits`` lands in ``main``, and delete this class.
    """

    model_config = ConfigDict(extra="ignore")

    dataset_version: str = Field(min_length=1)
    seed: int
    proportions: dict[str, float]
    totals: dict[str, int]
    class_distribution: dict[str, dict[str, int]]
    leakage_check: dict[str, object]
    reproducibility_check: dict[str, object]
