"""Focused T3-4.1 tests for the internal, model-pinned inference endpoint."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from dataset_quality.classifier.inference_http import (
    InferenceRequestError,
    MlflowCheckpointResolver,
    ModelIdentity,
    ResolvedCheckpoint,
    build_inference_app,
)


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 6), (10, 20, 30)).save(output, format="PNG")
    return output.getvalue()


def _post(app, *, data: dict[str, str], files: dict[str, tuple[str, bytes, str]]):
    boundary = b"t341-boundary"
    parts = []
    for name, value in data.items():
        parts.append(
            b"--"
            + boundary
            + f'\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    for name, (filename, payload, content_type) in files.items():
        parts.append(
            b"--"
            + boundary
            + (
                f'\r\nContent-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'
            ).encode()
            + payload
            + b"\r\n"
        )
    body = b"".join(parts) + b"--" + boundary + b"--\r\n"

    async def call():
        sent = []
        delivered = False

        async def receive():
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "path": "/predict",
            "raw_path": b"/predict",
            "query_string": b"",
            "headers": [
                (b"content-type", b"multipart/form-data; boundary=" + boundary),
                (b"content-length", str(len(body)).encode()),
            ],
            "client": ("test", 1),
            "server": ("test", 80),
        }
        await app(scope, receive, send)
        start = next(item for item in sent if item["type"] == "http.response.start")
        response_body = b"".join(
            item.get("body", b"") for item in sent if item["type"] == "http.response.body"
        )
        return SimpleNamespace(status_code=start["status"], json=lambda: json.loads(response_body))

    return asyncio.run(call())


class FakeService:
    def __init__(self) -> None:
        self.calls = []

    def predict(self, run_id, image):
        self.calls.append((run_id, image.mode, image.size))
        return (
            SimpleNamespace(
                label="car",
                index=0,
                confidence=0.875,
                probabilities={"car": 0.875, "person": 0.125},
            ),
            ModelIdentity(run_id, "selected-cnn", "a" * 64),
        )


def test_predict_contract_returns_probabilities_and_verified_model_identity() -> None:
    service = FakeService()
    response = _post(
        build_inference_app(service),
        data={"runId": "run_123"},
        files={"file": ("sample.png", _png(), "image/png")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "model": {
            "runId": "run_123",
            "runName": "selected-cnn",
            "checkpointSha256": "a" * 64,
        },
        "predictedClass": "car",
        "confidence": 0.875,
        "probabilities": {"car": 0.875, "person": 0.125},
    }
    assert service.calls == [("run_123", "RGB", (8, 6))]


def test_predict_rejects_url_or_path_fields_and_never_calls_model() -> None:
    service = FakeService()
    response = _post(
        build_inference_app(service),
        data={"runId": "run_123", "checkpointUrl": "https://evil.invalid/model.pt"},
        files={"file": ("sample.png", _png(), "image/png")},
    )

    assert response.status_code == 422
    assert response.json() == {"error": "multipart fields must be exactly file and runId"}
    assert service.calls == []


def test_predict_rejects_non_image_and_oversized_uploads() -> None:
    service = FakeService()
    app = build_inference_app(service, max_image_bytes=32)

    wrong_type = _post(
        app,
        data={"runId": "run_123"},
        files={"file": ("sample.txt", b"hello", "text/plain")},
    )
    too_large = _post(
        app,
        data={"runId": "run_123"},
        files={"file": ("sample.png", b"x" * 33, "image/png")},
    )

    assert wrong_type.status_code == 415
    assert too_large.status_code == 413
    assert service.calls == []


class FakeMlflowClient:
    def __init__(self, sources: dict[str, Path], digests: dict[str, str] | None = None) -> None:
        self.sources = sources
        self.digests = digests or {
            run_id: hashlib.sha256(path.read_bytes()).hexdigest()
            for run_id, path in sources.items()
        }
        self.downloads = []

    def get_run(self, run_id):
        return SimpleNamespace(
            info=SimpleNamespace(status="FINISHED", run_name=f"model-{run_id}"),
            data=SimpleNamespace(tags={"checkpoint_sha256": self.digests[run_id]}),
        )

    def download_artifacts(self, run_id, artifact_path, dst_path):
        self.downloads.append((run_id, artifact_path, dst_path))
        return str(self.sources[run_id])


def test_resolver_uses_each_backend_run_id_and_verifies_mlflow_sha256(tmp_path: Path) -> None:
    first = tmp_path / "first.pt"
    second = tmp_path / "second.pt"
    first.write_bytes(b"first verified checkpoint")
    second.write_bytes(b"second verified checkpoint")
    client = FakeMlflowClient({"run_a": first, "run_b": second})
    resolver = MlflowCheckpointResolver(tmp_path / "cache", lambda: client)

    resolved_a = resolver.resolve("run_a")
    resolved_b = resolver.resolve("run_b")

    assert resolved_a == ResolvedCheckpoint(
        first,
        ModelIdentity("run_a", "model-run_a", hashlib.sha256(first.read_bytes()).hexdigest()),
    )
    assert resolved_b.identity.run_id == "run_b"
    assert resolved_b.identity.checkpoint_sha256 == hashlib.sha256(second.read_bytes()).hexdigest()
    assert [download[:2] for download in client.downloads] == [
        ("run_a", "model.pt"),
        ("run_b", "model.pt"),
    ]
    try:
        resolver.resolve("../../model.pt")
    except InferenceRequestError as error:
        assert error.status_code == 422
    else:
        raise AssertionError("an invalid run id must be rejected before contacting MLflow")


def test_resolver_fails_closed_when_checkpoint_digest_does_not_match(tmp_path: Path) -> None:
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"tampered")
    client = FakeMlflowClient(
        {"run_123": checkpoint},
        {"run_123": hashlib.sha256(b"expected").hexdigest()},
    )
    resolver = MlflowCheckpointResolver(tmp_path / "cache", lambda: client)

    try:
        resolver.resolve("run_123")
    except RuntimeError as error:
        assert "SHA-256" in str(error)
    else:
        raise AssertionError("a modified checkpoint must never be loaded")
