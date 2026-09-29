"""T3-1.1: traceable, reproducible COCO crops for the classifier (owner: AI Engineer).

``plan_crops`` is pure — raw COCO in, crop plan plus stable exclusion records out.
``generate_crops`` adds the MariaDB/object-store fetch and writes the PNGs and the two
JSON artifacts. ``dataset_quality.crops.__main__`` is the DVC ``crop`` stage that wires
both to ``data/processed/``. The exclusion rules and the runbook live in
``pipeline/README.md``.
"""

from dataset_quality.crops.errors import (
    CropCocoStructureError,
    CropConfigurationError,
    CropError,
    CropSourceDecodeError,
    CropSourceUnavailableError,
)
from dataset_quality.crops.generator import CropRunResult, generate_crops
from dataset_quality.crops.geometry import CropBounds, integer_crop_bounds
from dataset_quality.crops.models import (
    CropExclusion,
    CropExclusionsReport,
    CropManifest,
    CropRecord,
    CropRunSummary,
    DimensionMismatch,
    ExclusionReason,
)
from dataset_quality.crops.planning import CropPlan, PlannedCrop, PlannedImage, plan_crops
from dataset_quality.crops.sources import BackendImageStore, SourceImageStore

__all__ = [
    "BackendImageStore",
    "CropBounds",
    "CropCocoStructureError",
    "CropConfigurationError",
    "CropError",
    "CropExclusion",
    "CropExclusionsReport",
    "CropManifest",
    "CropPlan",
    "CropRecord",
    "CropRunResult",
    "CropRunSummary",
    "CropSourceDecodeError",
    "CropSourceUnavailableError",
    "DimensionMismatch",
    "ExclusionReason",
    "PlannedCrop",
    "PlannedImage",
    "SourceImageStore",
    "generate_crops",
    "integer_crop_bounds",
    "plan_crops",
]
