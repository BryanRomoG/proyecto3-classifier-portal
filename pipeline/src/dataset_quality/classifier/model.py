"""T3-1.3: the CNN and its classification head (rubric 2.1).

Two backbones, both adapted to the frozen class list:

* ``resnet18`` — torchvision's ResNet-18. With ``pretrained=True`` the backbone starts from
  torchvision's ``ResNet18_Weights.IMAGENET1K_V1`` (ImageNet-1k, downloaded from
  download.pytorch.org); its 1000-way ``fc`` layer is discarded and replaced by our own
  head, so the output layer is always trained from scratch by the team.
* ``simple_cnn`` — a small LeNet-style network trained entirely from scratch (no external
  weights at all). Used by the fast tests and available as a from-scratch baseline.

The head is ``[Linear -> ReLU -> Dropout] * len(hidden_layers) -> Dropout -> Linear``, so
``hidden_layers`` and ``dropout`` are real architecture parameters, not labels.
``describe_weights`` returns the declaration that goes into MLflow and the model card.
"""

from __future__ import annotations

from collections.abc import Sequence

import torch
from torch import nn
from torchvision import models

from dataset_quality.classifier.config import TrainingConfig

PRETRAINED_WEIGHTS_ID = "torchvision.models.ResNet18_Weights.IMAGENET1K_V1"


def build_head(in_features: int, hidden_layers: Sequence[int], dropout: float, n_classes: int):
    layers: list[nn.Module] = []
    width = in_features
    for hidden in hidden_layers:
        layers += [nn.Linear(width, hidden), nn.ReLU(inplace=True), nn.Dropout(dropout)]
        width = hidden
    if not hidden_layers:
        layers.append(nn.Dropout(dropout))
    layers.append(nn.Linear(width, n_classes))
    return nn.Sequential(*layers)


class SimpleCNN(nn.Module):
    """LeNet-style: three conv blocks, global average pool, then the configurable head."""

    def __init__(self, hidden_layers: Sequence[int], dropout: float, n_classes: int) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 16, kernel_size=3, padding=1),
            nn.BatchNorm2d(16),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(16, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d(1),
        )
        self.head = build_head(64, hidden_layers, dropout, n_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(torch.flatten(self.features(x), 1))


def build_model(config: TrainingConfig, n_classes: int, *, load_pretrained: bool = True):
    """Build the network for ``n_classes``.

    ``load_pretrained=False`` builds the same architecture without downloading anything;
    it is what ``predict.load_checkpoint`` uses, since the checkpoint overwrites every
    weight anyway.
    """

    if config.architecture == "simple_cnn":
        return SimpleCNN(config.hidden_layers, config.dropout, n_classes)

    weights = (
        models.ResNet18_Weights.IMAGENET1K_V1 if config.pretrained and load_pretrained else None
    )
    network = models.resnet18(weights=weights)
    if config.freeze_backbone:
        for parameter in network.parameters():
            parameter.requires_grad = False
    network.fc = build_head(network.fc.in_features, config.hidden_layers, config.dropout, n_classes)
    return network


def describe_weights(config: TrainingConfig, model: nn.Module) -> dict[str, object]:
    """Where the initial weights came from and what is trainable (for MLflow/model card)."""

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    if config.architecture == "resnet18" and config.pretrained:
        origin = f"{PRETRAINED_WEIGHTS_ID} (backbone); head from scratch (seeds.init)"
    else:
        origin = "from scratch (random init, seeds.init)"
    frozen = config.architecture == "resnet18" and config.freeze_backbone
    trainable_layers = "head only (fc)" if frozen else "all layers"
    return {
        "architecture": config.architecture,
        "initial_weights": origin,
        "trainable_layers": trainable_layers,
        "trainable_parameters": trainable,
        "total_parameters": total,
    }
