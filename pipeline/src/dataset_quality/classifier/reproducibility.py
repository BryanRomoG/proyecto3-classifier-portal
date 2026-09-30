"""T3-2.1: seeding and environment capture (rubric 2.3).

Seeds are applied in a fixed order so each one governs a known part of the run:

1. ``seeds.init`` is set on ``random``/``numpy``/``torch`` right before the model is built:
   it decides the head's (and, from scratch, every layer's) initial weights.
2. ``seeds.augmentation`` is set on the same generators right after the model is built:
   it drives the random train transforms and dropout masks for the rest of the run.
3. ``seeds.shuffle`` feeds only ``SeededEpochSampler``'s private generator: the minibatch
   order depends on nothing else.
4. The partition seed is the manifest's own ``seed`` (read-only, recorded for traceability).

Known non-determinism: with ``num_workers=0`` on CPU, repeated runs are bit-identical in
practice; on GPU, some cuDNN kernels are not, which is why deterministic algorithms are
requested in ``warn_only`` mode and the flag is recorded in the environment.
"""

from __future__ import annotations

import os
import platform
import random
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import numpy as np
import torch

TRACKED_PACKAGES = (
    "torch",
    "torchvision",
    "numpy",
    "pillow",
    "pydantic",
    "mlflow",
    "mlflow-skinny",
)


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed % 2**32)
    torch.manual_seed(seed)


def enable_determinism() -> None:
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    torch.use_deterministic_algorithms(True, warn_only=True)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True


def environment_snapshot(device: torch.device | None = None) -> dict[str, object]:
    versions: dict[str, str] = {}
    for package in TRACKED_PACKAGES:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            continue
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "device": (device or torch.device("cpu")).type,
        "cuda_device_name": (
            torch.cuda.get_device_name(device)
            if device is not None and device.type == "cuda"
            else None
        ),
        "torch_cuda_version": torch.version.cuda,
        "cudnn_version": torch.backends.cudnn.version() if torch.cuda.is_available() else None,
        "torch_num_threads": torch.get_num_threads(),
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        "packages": versions,
    }


def git_state(repo_dir: Path) -> dict[str, str]:
    """Commit SHA and whether the tree had uncommitted changes when the run started."""

    def _git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=repo_dir, capture_output=True, text=True, check=True
        ).stdout.strip()

    try:
        commit = _git("rev-parse", "HEAD")
        dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    except (OSError, subprocess.CalledProcessError):
        return {"git_commit": os.environ.get("GIT_COMMIT", "unknown"), "git_dirty": "unknown"}
    return {"git_commit": commit, "git_dirty": str(dirty).lower()}
