"""Synthetic manifest over real PNG crops, and a tiny training config, for classifier tests.

Two visually separable classes (``car``: blue with horizontal bars, ``person``: red with
vertical bars, plus noise) so a few epochs of a small CNN really learn something. Every
third source image yields two crops of different classes, like a real multi-object photo,
and all crops of an image land in the same split.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from dataset_quality.classifier_splits.models import ClassifierSplitManifest

CLASSES = ("car", "person")


def _draw(label: str, rng: random.Random, size: int = 40) -> Image.Image:
    image = Image.new("RGB", (size, size))
    pixels = image.load()
    for x in range(size):
        for y in range(size):
            stripe = (y if label == "car" else x) // 5 % 2
            base = 200 if stripe else 60
            noise = rng.randint(-25, 25)
            if label == "car":
                pixels[x, y] = (40 + noise, 60 + noise, base + noise)
            else:
                pixels[x, y] = (base + noise, 50 + noise, 40 + noise)
    return image


@dataclass
class SyntheticDataset:
    root: Path
    manifest_path: Path
    manifest: ClassifierSplitManifest


def _split_of(image_id: int) -> str:
    bucket = image_id % 10
    return "train" if bucket < 7 else ("val" if bucket < 9 else "test")


def build_synthetic(root: Path, n_images: int = 60, seed: int = 0) -> SyntheticDataset:
    rng = random.Random(seed)
    sections: dict[str, dict[str, list]] = {
        name: {"image_ids": [], "crops": []} for name in ("train", "val", "test")
    }
    annotation_id = 1000
    for image_id in range(1, n_images + 1):
        split = _split_of(image_id)
        sections[split]["image_ids"].append(image_id)
        labels = [CLASSES[image_id % 2]]
        if image_id % 3 == 0:
            labels.append(CLASSES[(image_id + 1) % 2])
        for label in labels:
            annotation_id += 1
            relative = f"data/processed/crops/{label}/{annotation_id}.png"
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            _draw(label, rng).save(path)
            sections[split]["crops"].append(
                {
                    "annotation_id": annotation_id,
                    "source_image_id": image_id,
                    "category_name": label,
                    "relative_path": relative,
                }
            )

    splits = []
    for name, section in sections.items():
        crops = section["crops"]
        by_image: dict[str, set[int]] = {}
        for crop in crops:
            by_image.setdefault(crop["category_name"], set()).add(crop["source_image_id"])
        splits.append(
            {
                "name": name,
                "image_ids": section["image_ids"],
                "image_count": len(section["image_ids"]),
                "crop_count": len(crops),
                "crops": crops,
                "crops_by_category": dict(Counter(c["category_name"] for c in crops)),
                "images_by_category": {k: len(v) for k, v in by_image.items()},
            }
        )
    manifest = ClassifierSplitManifest.model_validate(
        {
            "dataset_version": "v-test",
            "seed": 42,
            "proportions": {"train": 0.7, "val": 0.2, "test": 0.1},
            "provenance": {
                "coco_file_name": "coco.json",
                "coco_sha256": "a" * 64,
                "crops_manifest_file_name": "crops_manifest.json",
                "crops_manifest_sha256": "b" * 64,
                "duplicate_pairs_file_name": "duplicate_pairs.json",
                "duplicate_pairs_sha256": "c" * 64,
            },
            "totals": {
                "images": n_images,
                "crops": sum(len(s["crops"]) for s in sections.values()),
            },
            "splits": splits,
            "leakage_check": {
                "status": "pass",
                "duplicate_pairs_checked": 0,
                "duplicate_pairs_same_split": 0,
                "leaked_pairs": 0,
            },
        }
    )
    manifest_path = root / "data/processed/classifier_split_manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return SyntheticDataset(root=root, manifest_path=manifest_path, manifest=manifest)


def tiny_config(**overrides):
    from dataset_quality.classifier.config import TrainingConfig

    values = {
        "architecture": "simple_cnn",
        "pretrained": False,
        "optimizer": "adam",
        "batch_size": 8,
        "max_epochs": 3,
        "learning_rate": 0.01,
        "image_size": 32,
        "hidden_layers": [16],
        "dropout": 0.1,
        "early_stopping": {"monitor": "val_loss", "patience": 5, "min_delta": 0.0},
    }
    values.update(overrides)
    return TrainingConfig.model_validate(values)
