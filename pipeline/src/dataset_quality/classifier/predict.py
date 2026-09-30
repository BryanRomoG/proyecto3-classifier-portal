"""Reloading a checkpoint for inference in a clean process (M4).

The checkpoint is self-describing: architecture config, class map and the exact eval
preprocessing travel with the weights, so inference can never drift from how the model was
validated and tested. Loading uses ``weights_only=True`` (no pickled code is executed) and
``strict=True`` (every tensor must match the rebuilt architecture).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import torch
from PIL import Image
from torch import nn

from dataset_quality.classifier.config import TrainingConfig
from dataset_quality.classifier.data import eval_transform
from dataset_quality.classifier.model import build_model
from dataset_quality.classifier.training import CHECKPOINT_FORMAT


class CheckpointError(ValueError):
    """The file is not a classifier checkpoint this code can load."""


@dataclass
class LoadedClassifier:
    model: nn.Module
    class_names: list[str]
    config: TrainingConfig
    transform: Callable[[Image.Image], torch.Tensor]
    checkpoint: dict


@dataclass(frozen=True)
class Prediction:
    label: str
    index: int
    confidence: float
    probabilities: dict[str, float]


def load_checkpoint(path: Path) -> LoadedClassifier:
    if not path.is_file() or path.stat().st_size == 0:
        raise CheckpointError(f"checkpoint {path} is missing or empty")
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(checkpoint, dict) or checkpoint.get("format") != CHECKPOINT_FORMAT:
        raise CheckpointError(f"{path} is not a {CHECKPOINT_FORMAT} checkpoint")
    config = TrainingConfig.model_validate(checkpoint["config"])
    class_names = list(checkpoint["class_names"])
    model = build_model(config, len(class_names), load_pretrained=False)
    model.load_state_dict(checkpoint["state_dict"], strict=True)
    model.eval()
    return LoadedClassifier(
        model=model,
        class_names=class_names,
        config=config,
        transform=eval_transform(config.image_size),
        checkpoint=checkpoint,
    )


@torch.no_grad()
def predict_tensors(classifier: LoadedClassifier, batch: torch.Tensor) -> list[Prediction]:
    probabilities = torch.softmax(classifier.model(batch), dim=1)
    predictions = []
    for row in probabilities.tolist():
        index = max(range(len(row)), key=row.__getitem__)
        predictions.append(
            Prediction(
                label=classifier.class_names[index],
                index=index,
                confidence=row[index],
                probabilities=dict(zip(classifier.class_names, row, strict=True)),
            )
        )
    return predictions


def predict_images(
    classifier: LoadedClassifier, images: Sequence[Image.Image], batch_size: int = 64
) -> list[Prediction]:
    predictions: list[Prediction] = []
    for start in range(0, len(images), batch_size):
        chunk = images[start : start + batch_size]
        batch = torch.stack([classifier.transform(image.convert("RGB")) for image in chunk])
        predictions.extend(predict_tensors(classifier, batch))
    return predictions


def predict_paths(classifier: LoadedClassifier, paths: Sequence[Path]) -> list[Prediction]:
    images = []
    for path in paths:
        with Image.open(path) as image:
            images.append(image.convert("RGB"))
    return predict_images(classifier, images)
