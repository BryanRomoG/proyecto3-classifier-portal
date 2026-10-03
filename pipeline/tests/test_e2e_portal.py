"""Rubric 7.2: end-to-end run through the live portal (release -> job -> run -> evaluation ->
test publication -> inference). Needs the docker compose stack up; skipped otherwise.

    E2E_PORTAL_URL=http://localhost:8080/api python -m pytest tests/test_e2e_portal.py
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

PORTAL = os.environ.get("E2E_PORTAL_URL")
pytestmark = pytest.mark.skipif(not PORTAL, reason="set E2E_PORTAL_URL to a running portal")


def test_release_to_inference_through_the_portal() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "e2e_portal_smoke.py"
    spec = importlib.util.spec_from_file_location("e2e_portal_smoke", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    report = module.run(
        module.Portal(PORTAL),
        minio=os.environ.get("E2E_MINIO_URL", "http://localhost:9000"),
        bucket="t3-classifier-e2e",
        timeout=float(os.environ.get("E2E_JOB_TIMEOUT", "900")),
    )

    assert report["passes"], report["checks"]
