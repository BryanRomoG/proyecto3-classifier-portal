"""HTTP service the portal uses to train for real (rubric 2.2, 6.1).

Runs in the ``trainer`` Compose service, on the same torch image as ``classifier-inference``
(``pipeline/Dockerfile.inference``). Routes:

* ``GET  /health``
* ``GET  /provenance`` -- the release, quality gate and 70/20/10 manifest a portal job
  trains on, with per-split and per-class counts.
* ``POST /jobs`` -- body ``{"config": {...TrainingConfig...}}``. Validated with the same
  ``TrainingConfig`` the trainer reads (422 with one ``{field, message}`` per problem), then
  refused (409) unless the quality gate is ``pass`` and the manifest keeps the test isolated.
  Only then is a job created: ``python -m dataset_quality.classifier train`` runs as a child
  process, outside the HTTP request, logging to the ``t3-portal`` MLflow experiment -- never
  to ``t3-classifier``, whose 10 official runs must not change.
* ``GET  /jobs/{job_id}`` -- state, epoch, progress, last metrics, MLflow run ID, error and
  log tail, rebuilt from files (``job.json`` and the trainer's own ``status.json``), so it
  survives a page reload and a service restart.

Prediction is not here: ``inference_http.py`` (``classifier-inference``) serves it.

Paths and the MLflow destination come from the environment (``CLASSIFIER_PIPELINE_ROOT``,
``CLASSIFIER_JOBS_DIR``, ``MLFLOW_TRACKING_URI``), defaulting to the pipeline layout.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from dataset_quality.classifier.config import TrainingConfig, validation_issues

PORTAL_EXPERIMENT = "t3-portal"
LOG_TAIL_LINES = 80
# Identifies this service process. A job without an exit code that belongs to another
# instance was interrupted: restarting the service (its container) also ends its children.
INSTANCE_ID = uuid.uuid4().hex


def _now() -> str:
    return datetime.now(UTC).isoformat()


class JobStore:
    """Jobs as folders: ``<root>/<job_id>/job.json``, ``train.log`` and ``runs/``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, job_id: str) -> Path:
        return self.root / job_id

    def read(self, job_id: str) -> dict[str, Any] | None:
        record = self.path(job_id) / "job.json"
        if not record.is_file():
            return None
        return json.loads(record.read_text(encoding="utf-8"))

    def write(self, job_id: str, job: dict[str, Any]) -> None:
        target = self.path(job_id) / "job.json"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(target)

    def update(self, job_id: str, **changes: Any) -> None:
        job = self.read(job_id) or {}
        job.update(changes)
        self.write(job_id, job)


class Settings:
    def __init__(self) -> None:
        self.pipeline_root = Path(os.environ.get("CLASSIFIER_PIPELINE_ROOT", ".")).resolve()
        self.manifest = self.pipeline_root / os.environ.get(
            "CLASSIFIER_MANIFEST", "data/processed/classifier_split_manifest.json"
        )
        self.data_root = self.pipeline_root / os.environ.get("CLASSIFIER_DATA_ROOT", ".")
        self.jobs_dir = Path(
            os.environ.get(
                "CLASSIFIER_JOBS_DIR", str(self.pipeline_root / "artifacts/classifier/portal-jobs")
            )
        )
        self.device = os.environ.get("CLASSIFIER_DEVICE", "auto")


def provenance(settings: Settings) -> dict[str, Any]:
    """Release -> gate -> manifest a portal job trains on. Raises if the manifest is unsafe."""

    from dataset_quality.classifier.data import class_names_from_manifest, load_manifest
    from dataset_quality.classifier.lineage import dataset_lineage

    loaded = load_manifest(settings.manifest)  # re-checks crop/image/duplicate isolation
    lineage = dataset_lineage(loaded, settings.pipeline_root)
    counts = {
        section.name: dict(sorted(Counter(c.category_name for c in section.crops).items()))
        for section in loaded.manifest.splits
    }
    return {
        **lineage,
        "classes": class_names_from_manifest(loaded.manifest),
        "split_counts": counts,
        "test_isolated": True,
    }


def preflight_errors(settings: Settings) -> list[str]:
    """Why a job must not start: unsafe manifest or a quality gate that is not ``pass``."""

    try:
        info = provenance(settings)
    except Exception as error:  # missing file, leakage, unreadable manifest
        return [f"manifest no utilizable: {error}"]
    if info["quality_gate_status"] != "pass":
        return [
            f"la compuerta de calidad del release {info['dataset_version']} es "
            f"{info['quality_gate_status']!r}, no 'pass'"
        ]
    return []


def _find_status(job_dir: Path) -> dict[str, Any] | None:
    for status in sorted((job_dir / "runs").glob("*/status.json")):
        return json.loads(status.read_text(encoding="utf-8"))
    return None


def _log_tail(job_dir: Path) -> str:
    log = job_dir / "train.log"
    if not log.is_file():
        return ""
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-LOG_TAIL_LINES:])


def job_view(store: JobStore, job_id: str) -> dict[str, Any] | None:
    job = store.read(job_id)
    if job is None:
        return None
    job_dir = store.path(job_id)
    status = _find_status(job_dir) or {}
    exit_code = job.get("exit_code")

    if status.get("state") == "finished" and exit_code in (None, 0):
        state = "finished"
    elif status.get("state") == "failed" or (exit_code is not None and exit_code != 0):
        state = "failed"
    elif exit_code is None and job.get("instance") != INSTANCE_ID:
        state = "failed"  # started by a previous run of this service, which has since restarted
    else:
        state = "running" if status else job.get("state", "queued")

    error = status.get("error") or job.get("error")
    if state == "failed" and not error:
        error = (
            f"el entrenamiento terminó con código {exit_code}"
            if exit_code is not None
            else "el proceso de entrenamiento se interrumpió"
        )
    max_epochs = job["config"]["max_epochs"]
    epoch = int(status.get("epoch", 0) or 0)
    return {
        "job_id": job_id,
        "state": state,
        "created_at": job["created_at"],
        "started_at": status.get("started_at"),
        "finished_at": job.get("ended_at") if state in ("finished", "failed") else None,
        "config": job["config"],
        "experiment": job["experiment"],
        "provenance": job.get("provenance"),
        "run_id": status.get("run_id"),
        "epoch": epoch,
        "max_epochs": max_epochs,
        "progress": 100.0 if state == "finished" else round(100.0 * epoch / max_epochs, 1),
        "last_metrics": status.get("last_metrics"),
        "best_epoch": status.get("best_epoch"),
        "best_val_accuracy": status.get("best_val_accuracy"),
        "stopped_early": status.get("stopped_early"),
        "error": error if state == "failed" else None,
        "log_tail": _log_tail(job_dir),
    }


def start_job(settings: Settings, store: JobStore, config: TrainingConfig) -> str:
    job_id = uuid.uuid4().hex[:12]
    job_dir = store.path(job_id)
    (job_dir / "runs").mkdir(parents=True)
    store.write(
        job_id,
        {
            "job_id": job_id,
            "state": "queued",
            "created_at": _now(),
            "config": config.model_dump(mode="json"),
            "experiment": PORTAL_EXPERIMENT,
            "provenance": provenance(settings),
            "instance": INSTANCE_ID,
        },
    )
    command = [
        sys.executable,
        "-m",
        "dataset_quality.classifier",
        "train",
        "--json",
        json.dumps(config.model_dump(mode="json")),
        "--manifest",
        str(settings.manifest),
        "--data-root",
        str(settings.data_root),
        "--experiment",
        PORTAL_EXPERIMENT,
        "--runs-dir",
        str(job_dir / "runs"),
        "--run-name",
        f"portal-{job_id}",
        "--device",
        settings.device,
    ]
    log = (job_dir / "train.log").open("w", encoding="utf-8")
    process = subprocess.Popen(  # noqa: S603 -- fixed argv, config already validated
        command,
        cwd=settings.pipeline_root,
        stdout=log,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    store.update(job_id, state="running", pid=process.pid, instance=INSTANCE_ID)

    def wait() -> None:
        code = process.wait()
        log.close()
        store.update(job_id, exit_code=code, ended_at=_now())

    threading.Thread(target=wait, daemon=True).start()
    return job_id


def _json_error(status: int, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status)


def build_app(settings: Settings | None = None) -> Starlette:
    settings = settings or Settings()
    store = JobStore(settings.jobs_dir)

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def get_provenance(_request: Request) -> JSONResponse:
        try:
            return JSONResponse(provenance(settings))
        except Exception as error:
            return _json_error(409, f"manifest no utilizable: {error}")

    async def create_job(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return _json_error(400, "El cuerpo debe ser JSON válido.")
        payload = body.get("config") if isinstance(body, dict) else None
        if not isinstance(payload, dict):
            return _json_error(422, "Falta 'config' (objeto).", errors=[])
        issues = validation_issues(payload)
        if issues:
            return _json_error(422, "Configuración de entrenamiento inválida.", errors=issues)
        problems = preflight_errors(settings)
        if problems:
            return _json_error(409, "; ".join(problems))
        job_id = start_job(settings, store, TrainingConfig.model_validate(payload))
        return JSONResponse(job_view(store, job_id), status_code=202)

    async def get_job(request: Request) -> JSONResponse:
        view = job_view(store, request.path_params["job_id"])
        if view is None:
            return _json_error(404, "Trabajo no encontrado.")
        return JSONResponse(view)

    return Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/provenance", get_provenance, methods=["GET"]),
            Route("/jobs", create_job, methods=["POST"]),
            Route("/jobs/{job_id}", get_job, methods=["GET"]),
        ]
    )
