"""T3-1.2: leak-free 70/20/10 classifier split manifest (owner: AI Engineer).

The manifest maps every ``crops_manifest.json`` record onto a train/val/test split by its
original image, using the inherited ``dataset_quality.splits.generate_splits`` (grouped by
the transitive components of ``duplicate_pairs.json``) so no group can cross a split. The
inherited image-level 70/15/15 ``split`` stage is untouched: this is a *new* artifact for
the classifier. The DVC stage and the runbook live in ``pipeline/README.md``.
"""

from dataset_quality.classifier_splits.errors import ClassifierSplitError
from dataset_quality.classifier_splits.generator import (
    ClassifierSplitResult,
    generate_classifier_split,
)
from dataset_quality.classifier_splits.models import (
    ClassifierSplitCrop,
    ClassifierSplitLeakageCheck,
    ClassifierSplitManifest,
    ClassifierSplitProportions,
    ClassifierSplitProvenance,
    ClassifierSplitSection,
    ClassifierSplitTotals,
)

__all__ = [
    "ClassifierSplitCrop",
    "ClassifierSplitError",
    "ClassifierSplitLeakageCheck",
    "ClassifierSplitManifest",
    "ClassifierSplitProportions",
    "ClassifierSplitProvenance",
    "ClassifierSplitResult",
    "ClassifierSplitSection",
    "ClassifierSplitTotals",
    "generate_classifier_split",
]
