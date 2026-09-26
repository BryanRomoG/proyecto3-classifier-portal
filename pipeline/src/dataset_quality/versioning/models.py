"""Internal bookkeeping models for the `release` stage's version history ledger.

Not part of the public contracts (`copilot/contracts.py`) — these exist purely so one
release can compute a real `VersionDiff` against the previous one without re-reading old
dataset files. See `pipeline/README.md`'s "Dataset release & versioning" section for the
human-readable explanation of what gets stored here and why.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from dataset_quality.copilot.contracts import DatasetVersionEntry


class VersionSnapshot(BaseModel):
    """Numeric counts for one release, cheap to store and diff against later."""

    model_config = ConfigDict(extra="forbid")

    image_count: int = Field(ge=0)
    box_count: int = Field(ge=0)
    per_class_counts: dict[str, int]
    small_object_percentage: float = Field(ge=0, le=100)


class VersionHistoryEntry(BaseModel):
    """One past release: its public record plus the numeric snapshot behind it."""

    model_config = ConfigDict(extra="forbid")

    entry: DatasetVersionEntry
    snapshot: VersionSnapshot


class VersionHistory(BaseModel):
    """The full release ledger, oldest first. Persisted to a git-tracked JSON file
    (`pipeline/data/version_history.json`) — deliberately NOT wired into `dvc.yaml`'s
    deps/outs, since this stage appends to it on every run; declaring it as a DVC dep
    would make the `release` stage perpetually "dirty" against its own side effect and
    break `dvc repro`'s rerun-avoidance for everything downstream of it.
    """

    model_config = ConfigDict(extra="forbid")

    entries: list[VersionHistoryEntry] = Field(default_factory=list)
