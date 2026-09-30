"""Loading the 70/20/10 manifest into train/val/test datasets (rubric 2.3, M3).

Two rules this module enforces rather than documents:

* **The test split is sealed.** ``split_records(..., "test")`` raises unless the caller
  passes ``allow_test=True``, and only ``evaluation.py`` does, after a candidate has been
  selected. Training, early stopping and selection can never read a test label.
* **Augmentation is train-only.** Random transforms are built only for ``train``;
  validation, test and inference all share ``eval_transform``, which is deterministic.

Before any dataset is built the manifest itself is re-checked for leakage: no annotation id
or source image may appear in two splits, and the manifest's own duplicate-group check must
be ``pass``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import torch
from PIL import Image
from torch.utils.data import Dataset, Sampler
from torchvision import transforms

from dataset_quality.classifier_splits.models import (
    ClassifierSplitCrop,
    ClassifierSplitManifest,
)

# ImageNet statistics: the pretrained ResNet backbone expects inputs normalised this way,
# and the from-scratch CNN uses the same values so both share one preprocessing contract.
NORMALIZE_MEAN: tuple[float, float, float] = (0.485, 0.456, 0.406)
NORMALIZE_STD: tuple[float, float, float] = (0.229, 0.224, 0.225)

SplitName = str


class ManifestIntegrityError(ValueError):
    """The manifest is not safe to train on (leakage, missing split or unknown class)."""


class SealedTestSplitError(PermissionError):
    """Something other than the final evaluation tried to read the test split."""


@dataclass(frozen=True)
class LoadedManifest:
    manifest: ClassifierSplitManifest
    sha256: str
    path: Path


def load_manifest(path: Path) -> LoadedManifest:
    raw = path.read_bytes()
    manifest = ClassifierSplitManifest.model_validate_json(raw)
    verify_manifest_isolation(manifest)
    return LoadedManifest(manifest=manifest, sha256=hashlib.sha256(raw).hexdigest(), path=path)


def verify_manifest_isolation(manifest: ClassifierSplitManifest) -> None:
    """Refuse a manifest whose splits share a crop, an original image or a duplicate group."""

    names = [section.name for section in manifest.splits]
    if sorted(names) != ["test", "train", "val"]:
        raise ManifestIntegrityError(f"manifest must have train/val/test, got {names}")

    if manifest.leakage_check.status != "pass" or manifest.leakage_check.leaked_pairs:
        raise ManifestIntegrityError(
            "manifest leakage_check is not 'pass' "
            f"({manifest.leakage_check.leaked_pairs} leaked duplicate pairs)"
        )

    seen_crops: dict[int, str] = {}
    seen_images: dict[int, str] = {}
    for section in manifest.splits:
        for image_id in section.image_ids:
            other = seen_images.setdefault(image_id, section.name)
            if other != section.name:
                raise ManifestIntegrityError(
                    f"source image {image_id} is in both {other} and {section.name}"
                )
        for crop in section.crops:
            other = seen_crops.setdefault(crop.annotation_id, section.name)
            if other != section.name:
                raise ManifestIntegrityError(
                    f"crop {crop.annotation_id} is in both {other} and {section.name}"
                )
            if seen_images.get(crop.source_image_id) != section.name:
                raise ManifestIntegrityError(
                    f"crop {crop.annotation_id} is in {section.name} but its source image "
                    f"{crop.source_image_id} is not"
                )


def class_names_from_manifest(manifest: ClassifierSplitManifest) -> list[str]:
    """The class map: sorted category names found in the manifest (index = label)."""

    names = {crop.category_name for section in manifest.splits for crop in section.crops}
    if len(names) < 2:
        raise ManifestIntegrityError(f"need at least two classes, found {sorted(names)}")
    return sorted(names)


def split_records(
    manifest: ClassifierSplitManifest,
    split: SplitName,
    *,
    allow_test: bool = False,
) -> list[ClassifierSplitCrop]:
    if split == "test" and not allow_test:
        raise SealedTestSplitError(
            "the test split is sealed: only the final evaluation of a selected candidate "
            "may read it"
        )
    for section in manifest.splits:
        if section.name == split:
            return sorted(section.crops, key=lambda crop: crop.annotation_id)
    raise ManifestIntegrityError(f"unknown split {split!r}")


def eval_transform(image_size: int) -> Callable[[Image.Image], torch.Tensor]:
    """Deterministic preprocessing shared by validation, test and inference."""

    return transforms.Compose(
        [
            transforms.Resize((image_size, image_size)),
            transforms.ToTensor(),
            transforms.Normalize(NORMALIZE_MEAN, NORMALIZE_STD),
        ]
    )


def train_transform(image_size: int, *, augment: bool) -> Callable[[Image.Image], torch.Tensor]:
    """Train-only preprocessing; random ops draw from torch's global RNG (seeded per run)."""

    if not augment:
        return eval_transform(image_size)
    return transforms.Compose(
        [
            transforms.RandomResizedCrop((image_size, image_size), scale=(0.8, 1.0)),
            transforms.RandomHorizontalFlip(),
            transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2),
            transforms.ToTensor(),
            transforms.Normalize(NORMALIZE_MEAN, NORMALIZE_STD),
        ]
    )


def preprocessing_spec(image_size: int) -> dict[str, object]:
    """The eval preprocessing, serialised into the checkpoint and the model package."""

    return {
        "resize": [image_size, image_size],
        "color_mode": "RGB",
        "to_tensor": "scale to [0, 1]",
        "normalize_mean": list(NORMALIZE_MEAN),
        "normalize_std": list(NORMALIZE_STD),
    }


class CropDataset(Dataset[tuple[torch.Tensor, int]]):
    """Crops of one split, labelled by the manifest's category name."""

    def __init__(
        self,
        records: Sequence[ClassifierSplitCrop],
        class_names: Sequence[str],
        data_root: Path,
        transform: Callable[[Image.Image], torch.Tensor],
        *,
        split: SplitName,
        augmented: bool,
    ) -> None:
        self.records = list(records)
        self.class_to_index = {name: index for index, name in enumerate(class_names)}
        self.data_root = data_root
        self.transform = transform
        self.split = split
        self.augmented = augmented
        unknown = {r.category_name for r in self.records} - set(self.class_to_index)
        if unknown:
            raise ManifestIntegrityError(f"{split} has classes outside the class map: {unknown}")

    def __len__(self) -> int:
        return len(self.records)

    def label(self, index: int) -> int:
        return self.class_to_index[self.records[index].category_name]

    def __getitem__(self, index: int) -> tuple[torch.Tensor, int]:
        record = self.records[index]
        with Image.open(self.data_root / record.relative_path) as image:
            tensor = self.transform(image.convert("RGB"))
        return tensor, self.label(index)


def build_datasets(
    loaded: LoadedManifest,
    class_names: Sequence[str],
    data_root: Path,
    *,
    image_size: int,
    augment: bool,
) -> tuple[CropDataset, CropDataset]:
    """Train and validation datasets only; the test split is not reachable from here."""

    manifest = loaded.manifest
    train = CropDataset(
        split_records(manifest, "train"),
        class_names,
        data_root,
        train_transform(image_size, augment=augment),
        split="train",
        augmented=augment,
    )
    val = CropDataset(
        split_records(manifest, "val"),
        class_names,
        data_root,
        eval_transform(image_size),
        split="val",
        augmented=False,
    )
    return train, val


class SeededEpochSampler(Sampler[int]):
    """Shuffles with its own generator, reseeded per epoch from ``(seed, epoch)``.

    The order of epoch *e* depends only on the shuffle seed and *e*, never on how many
    random numbers the model or the augmentation consumed before it, so two runs with the
    same seed see exactly the same sample order. ``order_digest`` exposes that order so it
    can be logged and compared.
    """

    def __init__(self, size: int, seed: int) -> None:
        self.size = size
        self.seed = seed
        self.epoch = 0

    def set_epoch(self, epoch: int) -> None:
        self.epoch = epoch

    def order(self, epoch: int | None = None) -> list[int]:
        generator = torch.Generator()
        generator.manual_seed(self.seed * 1_000_003 + (self.epoch if epoch is None else epoch))
        return torch.randperm(self.size, generator=generator).tolist()

    def order_digest(self, epoch: int) -> str:
        return hashlib.sha256(",".join(map(str, self.order(epoch))).encode()).hexdigest()

    def __iter__(self) -> Iterator[int]:
        return iter(self.order())

    def __len__(self) -> int:
        return self.size
