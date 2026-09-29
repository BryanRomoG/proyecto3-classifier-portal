"""Exception hierarchy for the T3-1.2 leak-free classifier split manifest.

The manifest is only ever written from inputs that provably describe each other, so any
inconsistency (a crops manifest built for another dataset version, a COCO file whose
SHA-256 does not match the one the crops were cropped from, a crop pointing at an image
the COCO file does not declare, a repeated crop identity) aborts the run instead of
producing a manifest nobody can trust.

Unknown duplicate pairs are deliberately *not* pre-validated here: the inherited
``dataset_quality.splits.generate_splits`` already raises its own ``ValueError`` for a
pair that references an image id outside the COCO document, and that failure is left to
propagate unchanged.
"""

from __future__ import annotations


class ClassifierSplitError(RuntimeError):
    """A run-level failure that must abort the classifier split manifest."""
