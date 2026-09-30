"""T3-1.4 / T3-2.x: one training run, minibatch by minibatch, logged to MLflow.

A run reads only the train and validation splits of the 70/20/10 manifest, trains with
one optimizer step per minibatch, evaluates validation once per epoch, stops early on the
configured metric and saves the **best** epoch's weights. Everything needed to audit it —
effective parameters, the four seeds, git commit, DVC release, manifest hash, class map,
per-epoch curves, the checkpoint and the environment — goes to the MLflow run.

A ``status.json`` next to the run's artifacts is rewritten after every epoch so a caller
running this outside the HTTP request (the portal's Training page) can show state,
progress and errors, and still see them after a reload.
"""

from __future__ import annotations

import hashlib
import json
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import mlflow
import torch
from torch import nn
from torch.utils.data import DataLoader

from dataset_quality.classifier.config import TrainingConfig
from dataset_quality.classifier.data import (
    CropDataset,
    SeededEpochSampler,
    build_datasets,
    class_names_from_manifest,
    load_manifest,
    preprocessing_spec,
)
from dataset_quality.classifier.early_stopping import EarlyStopping, FitResult, fit
from dataset_quality.classifier.lineage import dataset_lineage
from dataset_quality.classifier.model import build_model, describe_weights
from dataset_quality.classifier.reproducibility import (
    enable_determinism,
    environment_snapshot,
    git_state,
    seed_everything,
)

CHECKPOINT_FORMAT = "t3-classifier-checkpoint/v1"
CHECKPOINT_NAME = "model.pt"
DEFAULT_EXPERIMENT = "t3-classifier"


@dataclass(frozen=True)
class TrainingOutcome:
    run_id: str
    output_dir: Path
    checkpoint_path: Path
    checkpoint_sha256: str
    best_epoch: int
    stopped_epoch: int
    best_val_accuracy: float
    best_val_loss: float
    optimizer_steps: int


def build_optimizer(config: TrainingConfig, model: nn.Module) -> torch.optim.Optimizer:
    params = [p for p in model.parameters() if p.requires_grad]
    if config.optimizer == "sgd":
        return torch.optim.SGD(
            params,
            lr=config.learning_rate,
            momentum=config.momentum,
            weight_decay=config.weight_decay,
        )
    if config.optimizer == "adamw":
        return torch.optim.AdamW(params, lr=config.learning_rate, weight_decay=config.weight_decay)
    return torch.optim.Adam(params, lr=config.learning_rate, weight_decay=config.weight_decay)


def state_dict_sha256(model: nn.Module) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        digest.update(name.encode())
        digest.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


class MinibatchTrainer:
    """The minibatch loop: one ``optimizer.step()`` per batch, counted."""

    def __init__(
        self,
        model: nn.Module,
        optimizer: torch.optim.Optimizer,
        train_set: CropDataset,
        val_set: CropDataset,
        config: TrainingConfig,
        device: torch.device | None = None,
    ) -> None:
        self.model = model
        self.optimizer = optimizer
        self.device = device or torch.device("cpu")
        self.criterion = nn.CrossEntropyLoss()
        self.sampler = SeededEpochSampler(len(train_set), config.seeds.shuffle)
        self.train_loader = DataLoader(
            train_set,
            batch_size=config.batch_size,
            sampler=self.sampler,
            num_workers=config.num_workers,
            drop_last=False,
        )
        self.val_loader = DataLoader(
            val_set, batch_size=config.batch_size, shuffle=False, num_workers=config.num_workers
        )
        self.optimizer_steps = 0
        self.steps_per_epoch = len(self.train_loader)
        self.order_digests: dict[int, str] = {}

    def train_epoch(self, epoch: int) -> dict[str, float]:
        self.sampler.set_epoch(epoch)
        self.order_digests[epoch] = self.sampler.order_digest(epoch)
        self.model.train()
        total_loss, correct, seen = 0.0, 0, 0
        for inputs, targets in self.train_loader:
            inputs, targets = inputs.to(self.device), targets.to(self.device)
            self.optimizer.zero_grad(set_to_none=True)
            logits = self.model(inputs)
            loss = self.criterion(logits, targets)
            loss.backward()
            self.optimizer.step()
            self.optimizer_steps += 1
            total_loss += loss.item() * targets.size(0)
            correct += (logits.argmax(dim=1) == targets).sum().item()
            seen += targets.size(0)
        return {"train_loss": total_loss / seen, "train_accuracy": correct / seen}

    @torch.no_grad()
    def validate(self, epoch: int) -> dict[str, float]:
        self.model.eval()
        total_loss, correct, seen = 0.0, 0, 0
        for inputs, targets in self.val_loader:
            inputs, targets = inputs.to(self.device), targets.to(self.device)
            logits = self.model(inputs)
            total_loss += self.criterion(logits, targets).item() * targets.size(0)
            correct += (logits.argmax(dim=1) == targets).sum().item()
            seen += targets.size(0)
        return {"val_loss": total_loss / seen, "val_accuracy": correct / seen}


def plot_curves(result: FitResult, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    epochs = [int(m["epoch"]) for m in result.history]
    figure, (loss_ax, acc_ax) = plt.subplots(1, 2, figsize=(10, 4))
    for axis, metric in ((loss_ax, "loss"), (acc_ax, "accuracy")):
        axis.plot(epochs, [m[f"train_{metric}"] for m in result.history], label="train")
        axis.plot(epochs, [m[f"val_{metric}"] for m in result.history], label="validation")
        axis.axvline(result.best_epoch, color="green", linestyle="--", label="best epoch")
        if result.stopped_early:
            axis.axvline(result.stopped_epoch, color="red", linestyle=":", label="early stop")
        axis.set_xlabel("epoch")
        axis.set_title(metric)
        axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=100)
    plt.close(figure)


def resolve_device(requested: str = "auto") -> torch.device:
    """``auto`` -> CUDA when available, else CPU; ``cuda`` fails loudly if absent."""

    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("device 'cuda' requested but torch.cuda.is_available() is False")
    return torch.device(requested)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def train(
    config: TrainingConfig,
    *,
    manifest_path: Path,
    data_root: Path,
    output_root: Path,
    pipeline_root: Path,
    experiment_name: str = DEFAULT_EXPERIMENT,
    run_name: str | None = None,
    tags: dict[str, str] | None = None,
    on_epoch: Callable[[int, dict[str, float]], None] | None = None,
    device: str = "auto",
) -> TrainingOutcome:
    """Train one model and log it as one MLflow run (tracking URI from the environment).

    Weights are initialised on CPU (so ``initial_state_sha256`` does not depend on the
    device) and then moved to ``device``; the checkpoint is always saved on CPU.
    """

    target_device = resolve_device(device)
    loaded = load_manifest(manifest_path)
    class_names = class_names_from_manifest(loaded.manifest)
    lineage = dataset_lineage(loaded, pipeline_root)

    enable_determinism()
    train_set, val_set = build_datasets(
        loaded, class_names, data_root, image_size=config.image_size, augment=config.augment
    )

    seed_everything(config.seeds.init)
    model = build_model(config, len(class_names))
    initial_sha = state_dict_sha256(model)
    model = model.to(target_device)
    seed_everything(config.seeds.augmentation)
    optimizer = build_optimizer(config, model)
    trainer = MinibatchTrainer(model, optimizer, train_set, val_set, config, target_device)
    weights = describe_weights(config, model)

    mlflow.set_experiment(experiment_name)
    with mlflow.start_run(run_name=run_name) as active:
        run_id = active.info.run_id
        output_dir = output_root / run_id
        output_dir.mkdir(parents=True, exist_ok=True)
        status_path = output_dir / "status.json"
        started = datetime.now(UTC).isoformat()

        def write_status(state: str, **extra: object) -> None:
            _write_json(
                status_path,
                {
                    "run_id": run_id,
                    "state": state,
                    "started_at": started,
                    "updated_at": datetime.now(UTC).isoformat(),
                    "max_epochs": config.max_epochs,
                    **extra,
                },
            )

        mlflow.log_params(config.mlflow_params())
        mlflow.log_params(
            {
                "seed.partition": loaded.manifest.seed,
                "seed.shuffle": config.seeds.shuffle,
                "seed.augmentation": config.seeds.augmentation,
                "seed.init": config.seeds.init,
                "train_crops": len(train_set),
                "val_crops": len(val_set),
                "steps_per_epoch": trainer.steps_per_epoch,
                "device": target_device.type,
            }
        )
        mlflow.set_tags(
            {
                **lineage,
                **git_state(pipeline_root),
                "classes": json.dumps(class_names),
                "n_classes": str(len(class_names)),
                "initial_weights": str(weights["initial_weights"]),
                "trainable_layers": str(weights["trainable_layers"]),
                "initial_state_sha256": initial_sha,
                "test_split_used": "false",
                "device_name": (
                    torch.cuda.get_device_name(target_device)
                    if target_device.type == "cuda"
                    else "cpu"
                ),
                **(tags or {}),
            }
        )
        write_status("running", epoch=0)

        def on_epoch_end(epoch: int, metrics: dict[str, float], improved: bool) -> None:
            logged = {k: v for k, v in metrics.items() if k != "epoch"}
            mlflow.log_metrics(logged, step=epoch)
            mlflow.log_metric("optimizer_steps", trainer.optimizer_steps, step=epoch)
            write_status("running", epoch=epoch, last_metrics=logged, improved=improved)
            if on_epoch is not None:
                on_epoch(epoch, logged)

        try:
            stopper = EarlyStopping(
                config.early_stopping.monitor,
                config.early_stopping.patience,
                config.early_stopping.min_delta,
            )
            result = fit(
                model,
                max_epochs=config.max_epochs,
                stopper=stopper,
                train_epoch=trainer.train_epoch,
                validate=trainer.validate,
                on_epoch_end=on_epoch_end,
            )
        except Exception as error:
            write_status("failed", error=f"{type(error).__name__}: {error}")
            (output_dir / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
            mlflow.log_artifact(str(output_dir / "error.log"))
            raise

        best = result.history[result.best_epoch - 1]
        final_sha = state_dict_sha256(model)
        checkpoint_path = output_dir / CHECKPOINT_NAME
        torch.save(
            {
                "format": CHECKPOINT_FORMAT,
                "run_id": run_id,
                "state_dict": {k: v.detach().cpu() for k, v in model.state_dict().items()},
                "config": config.model_dump(mode="json"),
                "class_names": class_names,
                "preprocessing": preprocessing_spec(config.image_size),
                "best_epoch": result.best_epoch,
                "monitor": result.monitor,
                "best_value": result.best_value,
                "weights": weights,
                "lineage": lineage,
            },
            checkpoint_path,
        )
        checkpoint_sha = _file_sha256(checkpoint_path)

        _write_json(output_dir / "config.json", config.model_dump(mode="json"))
        _write_json(output_dir / "class_map.json", dict(enumerate(class_names)))
        _write_json(output_dir / "history.json", result.history)
        _write_json(output_dir / "environment.json", environment_snapshot(target_device))
        _write_json(output_dir / "weights.json", weights)
        _write_json(output_dir / "lineage.json", lineage)
        _write_json(output_dir / "sample_order.json", trainer.order_digests)
        plot_curves(result, output_dir / "curves.png")

        mlflow.log_metrics(
            {
                "best_epoch": result.best_epoch,
                "stopped_epoch": result.stopped_epoch,
                "best_val_accuracy": best["val_accuracy"],
                "best_val_loss": best["val_loss"],
                "total_optimizer_steps": trainer.optimizer_steps,
            }
        )
        mlflow.set_tags(
            {
                "stopped_early": str(result.stopped_early).lower(),
                "final_state_sha256": final_sha,
                "weights_changed": str(final_sha != initial_sha).lower(),
                "checkpoint_sha256": checkpoint_sha,
                "epoch1_order_sha256": trainer.order_digests.get(1, ""),
            }
        )
        write_status(
            "finished",
            epoch=result.stopped_epoch,
            best_epoch=result.best_epoch,
            stopped_early=result.stopped_early,
            best_val_accuracy=best["val_accuracy"],
            checkpoint_sha256=checkpoint_sha,
        )
        mlflow.log_artifacts(str(output_dir))

    return TrainingOutcome(
        run_id=run_id,
        output_dir=output_dir,
        checkpoint_path=checkpoint_path,
        checkpoint_sha256=checkpoint_sha,
        best_epoch=result.best_epoch,
        stopped_epoch=result.stopped_epoch,
        best_val_accuracy=best["val_accuracy"],
        best_val_loss=best["val_loss"],
        optimizer_steps=trainer.optimizer_steps,
    )
