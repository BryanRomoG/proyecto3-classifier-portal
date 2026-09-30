"""T3-1.4 / rubric 2.2: the training-config API rejects invalid values before any job exists.

Drives the ASGI app directly (same approach as ``test_copilot_http.py``, no socket). Every
rejection must name the offending field with a readable message, and the API must agree
with ``TrainingConfig`` -- the model the trainer itself reads -- on every case, so the API
can never accept a value the trainer refuses. The service must also start without torch.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from dataset_quality.classifier.config import SEARCHED_HYPERPARAMETERS, TrainingConfig
from dataset_quality.classifier.http_app import build_app, handle_validate

INVALID_CASES = [
    ({"batch_size": 0}, "batch_size"),
    ({"learning_rate": -0.1}, "learning_rate"),
    ({"optimizer": "rmsprop"}, "optimizer"),
    ({"max_epochs": 1000}, "max_epochs"),
    ({"image_size": 16}, "image_size"),
    ({"hidden_layers": [4]}, "hidden_layers"),
    ({"dropout": 1.0}, "dropout"),
    ({"early_stopping": {"patience": 0}}, "early_stopping.patience"),
    ({"batchsize": 64}, "batchsize"),
]


def _call(app, method: str, path: str, body: bytes = b"") -> tuple[int, object]:
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("test", 0),
        "server": ("test", 80),
    }
    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    payload = next(m for m in sent if m["type"] == "http.response.body")["body"]
    return start["status"], json.loads(payload) if payload else None


@pytest.mark.parametrize(("payload", "field"), INVALID_CASES)
def test_invalid_value_is_rejected_with_the_field_and_a_message(payload, field) -> None:
    status, body = _call(build_app(), "POST", "/training/validate", json.dumps(payload).encode())

    assert status == 422
    assert body["valid"] is False
    assert field in [error["field"] for error in body["errors"]]
    assert all(error["message"] for error in body["errors"])
    with pytest.raises(ValidationError):
        TrainingConfig.model_validate(payload)


def test_valid_config_returns_the_effective_values_the_trainer_will_use() -> None:
    payload = {"optimizer": "sgd", "batch_size": 16, "early_stopping": {"patience": 3}}

    status, body = _call(build_app(), "POST", "/training/validate", json.dumps(payload).encode())

    assert status == 200
    assert body == {
        "valid": True,
        "config": TrainingConfig.model_validate(payload).model_dump(mode="json"),
    }


def test_several_invalid_values_are_all_reported() -> None:
    status, body = handle_validate({"batch_size": 0, "dropout": 2})

    assert status == 422
    assert {error["field"] for error in body["errors"]} == {"batch_size", "dropout"}


def test_a_body_that_is_not_an_object_or_not_json_is_rejected() -> None:
    app = build_app()

    assert _call(app, "POST", "/training/validate", b"[1, 2]")[0] == 422
    status, body = _call(app, "POST", "/training/validate", b"{not json")
    assert status == 400
    assert body["valid"] is False


def test_schema_exposes_every_searched_hyperparameter_with_its_limits() -> None:
    status, schema = _call(build_app(), "GET", "/training/schema")

    assert status == 200
    assert set(SEARCHED_HYPERPARAMETERS) <= set(schema["properties"])
    assert schema["properties"]["batch_size"]["minimum"] == 1
    assert schema["additionalProperties"] is False


def test_health() -> None:
    assert _call(build_app(), "GET", "/health") == (200, {"status": "ok"})


def test_the_service_does_not_import_torch_or_mlflow() -> None:
    code = (
        "import sys; import dataset_quality.classifier.http_app; "
        "assert 'torch' not in sys.modules and 'mlflow' not in sys.modules"
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    subprocess.run([sys.executable, "-c", code], check=True, env=env)
