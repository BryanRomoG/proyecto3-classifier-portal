"""T3 image classifier (owner: ML Engineer): model, training, MLflow runs, selection, test.

Consumes the leak-free 70/20/10 ``classifier_split_manifest.json`` (T3-1.2) and never reads
its test split except through ``evaluation.evaluate_test`` after a candidate has been
selected by validation. Only ``config`` is imported here so that validating a training
config (what the API and the portal do before creating a job) does not import torch.
"""

from dataset_quality.classifier.config import (
    SEARCHED_HYPERPARAMETERS,
    EarlyStoppingConfig,
    SeedConfig,
    TrainingConfig,
    json_schema,
    validation_errors,
)

__all__ = [
    "SEARCHED_HYPERPARAMETERS",
    "EarlyStoppingConfig",
    "SeedConfig",
    "TrainingConfig",
    "json_schema",
    "validation_errors",
]
