"""Rubric 2.2 / 6.1: portal jobs train for real, outside the request.

Drives the ``trainer`` ASGI app directly on synthetic data. A valid job launches the real
trainer as a child process (``python -m dataset_quality.classifier train``) in the
``t3-portal`` experiment; its state is rebuilt from files, so a new app instance (a service
restart) still reports it. Invalid configs and a failed quality gate are refused before any
job exists.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

import pytest
from mlflow.tracking import MlflowClient
from tests_classifier_helpers import tiny_config

from dataset_quality.classifier import jobs_app


def _call(app, method: str, path: str, body: bytes = b"", content_type="application/json"):
    sent: list[dict] = []
    raw_path, _, query = path.partition("?")

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "path": raw_path,
        "raw_path": raw_path.encode(),
        "query_string": query.encode(),
        "headers": [(b"content-type", content_type.encode())],
        "client": ("test", 0),
        "server": ("test", 80),
    }
    asyncio.run(app(scope, receive, send))
    status = next(m for m in sent if m["type"] == "http.response.start")["status"]
    payload = next(m for m in sent if m["type"] == "http.response.body")["body"]
    return status, json.loads(payload) if payload else None


def _write_gate(root, status: str) -> None:
    interim = root / "data/interim"
    interim.mkdir(parents=True, exist_ok=True)
    (interim / "quality.json").write_text(
        json.dumps({"overall_status": status, "dataset_version": "v-test"}), encoding="utf-8"
    )
    # The Project 2 release history: the approved release the manifest derives from, plus an
    # older one whose quality gate failed.
    (interim / "versions.json").write_text(
        json.dumps(
            {
                "current_version": "v-test",
                "versions": [
                    {"version": "v-old", "quality_status": "fail", "content_hash": "aaa"},
                    {"version": "v-test", "quality_status": status, "content_hash": "bbb"},
                ],
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def service(synthetic, tmp_path, mlflow_tracking, monkeypatch):
    _write_gate(synthetic.root, "pass")
    monkeypatch.setenv("CLASSIFIER_PIPELINE_ROOT", str(synthetic.root))
    monkeypatch.setenv("CLASSIFIER_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("CLASSIFIER_DEVICE", "cpu")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(sys.path))
    return {"app": jobs_app.build_app(), "jobs": tmp_path / "jobs", "root": synthetic.root}


def _config(**overrides) -> bytes:
    payload = tiny_config(max_epochs=2, **overrides).model_dump(mode="json")
    return json.dumps({"config": payload}).encode()


def _wait(app, job_id: str, timeout: float = 180.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, view = _call(app, "GET", f"/jobs/{job_id}")
        if view["state"] in ("finished", "failed"):
            return view
        time.sleep(0.5)
    raise AssertionError(f"job {job_id} did not finish: {view}")


def test_invalid_config_is_refused_before_any_job_exists(service) -> None:
    body = json.dumps({"config": {"batch_size": 0, "hidden_layers": [4]}}).encode()

    status, response = _call(service["app"], "POST", "/jobs", body)

    assert status == 422
    assert {e["field"] for e in response["errors"]} == {"batch_size", "hidden_layers"}
    assert not any(service["jobs"].iterdir())


def test_a_failed_quality_gate_refuses_the_job(service, synthetic) -> None:
    _write_gate(synthetic.root, "fail")

    status, response = _call(service["app"], "POST", "/jobs", _config())

    assert status == 409
    assert "'fail'" in response["error"]
    assert not any(service["jobs"].iterdir())


def test_provenance_reports_release_gate_and_split_counts(service) -> None:
    status, info = _call(service["app"], "GET", "/provenance")

    assert status == 200
    assert info["quality_gate_status"] == "pass"
    assert info["test_isolated"] is True
    assert set(info["split_counts"]) == {"train", "val", "test"}
    assert info["classes"] == ["car", "person"]


def test_a_job_trains_for_real_and_survives_a_restart(service) -> None:
    status, created = _call(service["app"], "POST", "/jobs", _config())
    assert status == 202
    assert created["state"] in ("queued", "running")

    view = _wait(service["app"], created["job_id"])

    assert view["state"] == "finished", view["log_tail"]
    assert view["epoch"] == view["max_epochs"] == 2
    assert view["progress"] == 100.0
    run = MlflowClient().get_run(view["run_id"])
    assert run.info.status == "FINISHED"
    experiment = MlflowClient().get_experiment(run.info.experiment_id)
    assert experiment.name == jobs_app.PORTAL_EXPERIMENT
    assert run.data.tags["weights_changed"] == "true"

    restarted = jobs_app.build_app()  # a new service instance reads the same files
    _, again = _call(restarted, "GET", f"/jobs/{created['job_id']}")
    assert again["state"] == "finished"
    assert again["run_id"] == view["run_id"]


def test_a_job_whose_service_restarted_mid_run_is_reported_as_interrupted(service) -> None:
    job_dir = service["jobs"] / "abc123"
    (job_dir / "runs").mkdir(parents=True)
    store = jobs_app.JobStore(service["jobs"])
    store.write(
        "abc123",
        {
            "job_id": "abc123",
            "state": "running",
            "created_at": "2026-10-02T00:00:00+00:00",
            "config": tiny_config().model_dump(mode="json"),
            "experiment": jobs_app.PORTAL_EXPERIMENT,
            "instance": "a-previous-instance",
        },
    )

    _, view = _call(service["app"], "GET", "/jobs/abc123")

    assert view["state"] == "failed"
    assert "interrumpió" in view["error"]
    assert _call(service["app"], "GET", "/jobs/missing")[0] == 404


def test_releases_lists_the_project_2_versions_and_which_one_can_train(service) -> None:
    status, body = _call(service["app"], "GET", "/releases")

    assert status == 200
    by_version = {release["version"]: release for release in body["releases"]}
    assert by_version["v-test"]["quality_status"] == "pass"
    assert by_version["v-test"]["approved"] is True
    assert by_version["v-test"]["has_manifest"] is True
    assert by_version["v-old"]["approved"] is False
    assert by_version["v-old"]["has_manifest"] is False
    assert body["manifest_dataset_version"] == "v-test"


@pytest.mark.parametrize("version", ["v-old", "v-unknown"])
def test_a_job_for_a_release_that_is_not_approved_or_has_no_manifest_is_refused(
    service, version
) -> None:
    payload = json.loads(_config())
    payload["dataset_version"] = version

    status, response = _call(service["app"], "POST", "/jobs", json.dumps(payload).encode())

    assert status == 409
    assert version in response["error"]
    assert not any(service["jobs"].iterdir())


def test_runs_reports_which_official_runs_are_valid(service, synthetic, tmp_path) -> None:
    from dataset_quality.classifier.training import train

    for name in ("first", "same-again"):
        train(
            tiny_config(max_epochs=2),
            manifest_path=synthetic.manifest_path,
            data_root=synthetic.root,
            output_root=tmp_path / "runs",
            pipeline_root=synthetic.root,
            experiment_name=jobs_app.OFFICIAL_EXPERIMENT,
            run_name=name,
            device="cpu",
        )

    status, body = _call(service["app"], "GET", "/runs")

    assert status == 200
    assert body["experiment"] == jobs_app.OFFICIAL_EXPERIMENT
    assert body["valid_runs"] == 1
    validity = {row["run_name"]: row for row in body["runs"]}
    assert validity["first"]["valid"] is True
    assert validity["same-again"]["valid"] is False
    assert validity["same-again"]["invalid_reasons"]
