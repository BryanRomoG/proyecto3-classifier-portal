"""Tier 4: stratified, reproducible train/val/test splits. Owner: Application & AI Engineer."""

from dataset_quality.splits.generator import SplitGenerationResult, generate_splits
from dataset_quality.splits.models import (
    SplitClassDistribution,
    SplitLeakageCheck,
    SplitProportions,
    SplitReproducibilityCheck,
    SplitResult,
    SplitTotals,
)

__all__ = [
    "SplitClassDistribution",
    "SplitGenerationResult",
    "SplitLeakageCheck",
    "SplitProportions",
    "SplitReproducibilityCheck",
    "SplitResult",
    "SplitTotals",
    "generate_splits",
]
