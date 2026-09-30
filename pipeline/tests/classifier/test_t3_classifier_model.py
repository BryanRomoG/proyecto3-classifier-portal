"""T3-1.3: the CNN is ours to train — right outputs, declared weights, weights change."""

from __future__ import annotations

import torch
from tests_classifier_helpers import tiny_config
from torch import nn

from dataset_quality.classifier.model import (
    PRETRAINED_WEIGHTS_ID,
    build_model,
    describe_weights,
)
from dataset_quality.classifier.training import build_optimizer, state_dict_sha256


def _linear_widths(module: nn.Module) -> list[int]:
    return [layer.out_features for layer in module.modules() if isinstance(layer, nn.Linear)]


def test_outputs_one_logit_per_class_for_both_architectures() -> None:
    for config in (
        tiny_config(),
        tiny_config(architecture="resnet18", pretrained=False, image_size=64),
    ):
        model = build_model(config, n_classes=2).eval()
        with torch.no_grad():
            logits = model(torch.zeros(3, 3, config.image_size, config.image_size))
        assert logits.shape == (3, 2)


def test_hidden_layers_are_real_layers_of_the_head() -> None:
    config = tiny_config(architecture="resnet18", pretrained=False, hidden_layers=[512, 128])
    model = build_model(config, n_classes=2)

    assert _linear_widths(model.fc) == [512, 128, 2]
    assert _linear_widths(build_model(tiny_config(hidden_layers=[]), 2).head) == [2]


def test_frozen_backbone_trains_only_the_head() -> None:
    config = tiny_config(architecture="resnet18", pretrained=False, freeze_backbone=True)
    model = build_model(config, n_classes=2)

    trainable = {name.split(".")[0] for name, p in model.named_parameters() if p.requires_grad}
    assert trainable == {"fc"}
    assert describe_weights(config, model)["trainable_layers"] == "head only (fc)"


def test_weight_origin_is_declared() -> None:
    pretrained = tiny_config(architecture="resnet18", pretrained=True)
    scratch = tiny_config()
    model = build_model(scratch, 2)

    assert PRETRAINED_WEIGHTS_ID in describe_weights(pretrained, model)["initial_weights"]
    assert describe_weights(scratch, model)["initial_weights"].startswith("from scratch")


def test_a_short_training_changes_weights_and_predictions() -> None:
    torch.manual_seed(0)
    config = tiny_config()
    model = build_model(config, 2)
    inputs = torch.randn(16, 3, 32, 32)
    targets = torch.tensor([0, 1] * 8)
    model.eval()
    with torch.no_grad():
        before_logits = model(inputs)
    before = state_dict_sha256(model)

    optimizer = build_optimizer(config, model)
    model.train()
    for _ in range(5):
        optimizer.zero_grad()
        nn.functional.cross_entropy(model(inputs), targets).backward()
        optimizer.step()

    model.eval()
    with torch.no_grad():
        after_logits = model(inputs)
    assert state_dict_sha256(model) != before
    assert not torch.allclose(before_logits, after_logits)
