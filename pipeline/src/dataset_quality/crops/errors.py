"""Exception hierarchy for the T3-1.1 COCO crop stage.

Two failure modes are deliberately kept apart:

- A *per-annotation* problem (malformed, non-numeric, degenerate or out-of-image
  box) is data, not a crash: it is recorded in ``crop_exclusions.json`` so the run
  still covers every other annotation. The same applies to a box that only fits the
  size COCO declares but not the size the image really has.
- A *run-level* problem (broken COCO structure, unusable target configuration, a
  missing ``images`` row, an unreachable object, an undecodable image) aborts the
  stage with one of these errors, because carrying on would mean fabricating a
  partial dataset behind a green exit code.
"""

from __future__ import annotations


class CropError(RuntimeError):
    """Base class for every run-level crop failure."""


class CropCocoStructureError(CropError):
    """The canonical COCO document is not shaped like a COCO document."""


class CropConfigurationError(CropError):
    """The configured target categories cannot be turned into crop directories."""


class CropSourceUnavailableError(CropError):
    """A source image's ``storage_key`` row or stored object could not be resolved."""


class CropSourceDecodeError(CropError):
    """A source image's bytes are not a decodable image."""
