"""Shared fixtures for the T3 classifier tests.

The classifier needs the ML extras (``requirements-train.txt``: torch, torchvision,
mlflow, matplotlib). Locally, without them, these tests are skipped; in CI the variable
``CLASSIFIER_TESTS_REQUIRED=1`` turns a missing dependency into a hard failure so the suite
can never go green by silently skipping.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REQUIRED = os.environ.get("CLASSIFIER_TESTS_REQUIRED") == "1"
for _module in ("torch", "torchvision", "mlflow", "matplotlib"):
    try:
        __import__(_module)
    except ImportError as _error:
        if REQUIRED:
            raise
        pytest.skip(f"classifier extras not installed ({_error})", allow_module_level=True)

from tests_classifier_helpers import SyntheticDataset, build_synthetic  # noqa: E402


@pytest.fixture
def synthetic(tmp_path: Path) -> SyntheticDataset:
    return build_synthetic(tmp_path)


@pytest.fixture
def mlflow_tracking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """An isolated MLflow store; cwd moves to tmp so default artifacts land there too."""

    import mlflow

    monkeypatch.chdir(tmp_path)
    uri = f"sqlite:///{(tmp_path / 'mlflow.db').as_posix()}"
    mlflow.set_tracking_uri(uri)
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    yield uri
    mlflow.set_tracking_uri(None)
