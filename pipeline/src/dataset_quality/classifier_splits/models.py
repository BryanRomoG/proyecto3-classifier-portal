"""Pydantic v2 models for the T3-1.2 classifier split manifest.

The manifest is a *new* artifact for the classifier crops: it maps every
``crops_manifest.json`` record onto the 70/20/10 split of its original image, while the
inherited image-level split stays 70/15/15. Like the rest of the pipeline's artifacts it
is strict (``extra="forbid"``) and deterministic: no timestamps, no host paths and no
run-dependent ordering. Provenance is content-addressed by SHA-256 only.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from dataset_quality.quality_gate.models import CheckStatus

_SHA256_PATTERN = r"^[a-f0-9]{64}$"
SplitName = Literal["train", "val", "test"]


class ClassifierSplitProportions(BaseModel):
    """Configured classifier train/validation/test proportions, echoed back."""

    model_config = ConfigDict(extra="forbid")

    train: float
    val: float
    test: float


class ClassifierSplitProvenance(BaseModel):
    """SHA-256 provenance of every input the manifest was built from.

    Only file *names* are recorded, never absolute paths, so the artifact is portable
    across hosts and checkouts.
    """

    model_config = ConfigDict(extra="forbid")

    coco_file_name: str = Field(min_length=1)
    coco_sha256: str = Field(pattern=_SHA256_PATTERN)
    crops_manifest_file_name: str = Field(min_length=1)
    crops_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    duplicate_pairs_file_name: str = Field(min_length=1)
    duplicate_pairs_sha256: str = Field(pattern=_SHA256_PATTERN)


class ClassifierSplitCrop(BaseModel):
    """One classifier crop placed in a split, identified by its COCO annotation id."""

    model_config = ConfigDict(extra="forbid")

    annotation_id: PositiveInt
    source_image_id: PositiveInt
    category_name: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)


class ClassifierSplitSection(BaseModel):
    """One split's ordered image ids and crops plus their per-category counts."""

    model_config = ConfigDict(extra="forbid")

    name: SplitName
    image_ids: list[int]
    image_count: int = Field(ge=0)
    crop_count: int = Field(ge=0)
    crops: list[ClassifierSplitCrop]
    crops_by_category: dict[str, int]
    images_by_category: dict[str, int]


class ClassifierSplitTotals(BaseModel):
    """Image and crop counts across every split of the manifest."""

    model_config = ConfigDict(extra="forbid")

    images: int = Field(ge=0)
    crops: int = Field(ge=0)


class ClassifierSplitLeakageCheck(BaseModel):
    """Result of checking that no duplicate pair (or transitive chain) crosses splits."""

    model_config = ConfigDict(extra="forbid")

    status: CheckStatus
    duplicate_pairs_checked: int = Field(ge=0)
    duplicate_pairs_same_split: int = Field(ge=0)
    leaked_pairs: int = Field(ge=0)


class ClassifierSplitManifest(BaseModel):
    """The serialized ``data/processed/classifier_split_manifest.json`` artifact."""

    model_config = ConfigDict(extra="forbid")

    dataset_version: str = Field(min_length=1)
    seed: int
    proportions: ClassifierSplitProportions
    provenance: ClassifierSplitProvenance
    totals: ClassifierSplitTotals
    splits: list[ClassifierSplitSection] = Field(min_length=3, max_length=3)
    leakage_check: ClassifierSplitLeakageCheck
