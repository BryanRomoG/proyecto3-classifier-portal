"""Internal HTTP inference service for the classifier portal (T3-4.1).

The caller supplies only an image and an MLflow ``runId``.  It can never supply an
artifact URL or filesystem path: this process downloads that run's ``model.pt`` through
``MlflowClient`` and verifies it against the SHA-256 recorded by the training run before
loading it with :func:`load_checkpoint`.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

CHECKPOINT_ARTIFACT = "model.pt"
DEFAULT_CACHE_DIR = Path(".inference-cache")
DEFAULT_MAX_IMAGE_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_IMAGE_PIXELS = 25_000_000
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


class InferenceRequestError(ValueError):
    """A safe, client-facing inference error."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ModelIdentity:
    run_id: str
    run_name: str
    checkpoint_sha256: str


@dataclass(frozen=True)
class ResolvedCheckpoint:
    path: Path
    identity: ModelIdentity


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class MlflowCheckpointResolver:
    """Resolve a backend-authorized run through MLflow and verify its checkpoint."""

    def __init__(
        self,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self._client_factory = client_factory
        self._lock = threading.Lock()

    def resolve(self, run_id: str) -> ResolvedCheckpoint:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise InferenceRequestError("runId is invalid")

        if self._client_factory is None:
            from mlflow.tracking import MlflowClient

            client = MlflowClient()
        else:
            client = self._client_factory()
        run = client.get_run(run_id)
        if getattr(run.info, "status", None) != "FINISHED":
            raise InferenceRequestError("runId is not a finished model", status_code=409)
        tags = getattr(run.data, "tags", {})
        expected_sha = tags.get("checkpoint_sha256")
        if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
            raise RuntimeError("MLflow run has no valid checkpoint digest")

        with self._lock:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            target_dir = self.cache_dir / run_id
            target_dir.mkdir(parents=True, exist_ok=True)
            checkpoint = target_dir / CHECKPOINT_ARTIFACT
            if not checkpoint.is_file() or _sha256(checkpoint) != expected_sha:
                downloaded = Path(
                    client.download_artifacts(run_id, CHECKPOINT_ARTIFACT, dst_path=str(target_dir))
                )
                if not downloaded.is_file():
                    raise RuntimeError("MLflow did not return model.pt")
                # MLflow may return cache/model.pt or cache/<run>/model.pt.  Verify first,
                # then use that exact file; never derive a path from request data.
                checkpoint = downloaded
            actual_sha = _sha256(checkpoint)
            if actual_sha != expected_sha:
                raise RuntimeError("selected checkpoint failed SHA-256 verification")

            run_name = tags.get("mlflow.runName") or getattr(run.info, "run_name", None)
            if not isinstance(run_name, str) or not run_name:
                run_name = run_id
            return ResolvedCheckpoint(
                path=checkpoint,
                identity=ModelIdentity(run_id, run_name, actual_sha),
            )


class InferenceService:
    """Resolve, load and cache verified models, then reuse the canonical predictor."""

    def __init__(
        self,
        resolver: MlflowCheckpointResolver,
        loader: Callable[[Path], Any] | None = None,
        predictor: Callable[[Any, list[Image.Image]], list[Any]] | None = None,
    ) -> None:
        if loader is None or predictor is None:
            # Keep resolver and request-contract tests lightweight; the inference process
            # itself uses the canonical torch-backed checkpoint loader and eval transform.
            from dataset_quality.classifier.predict import load_checkpoint, predict_images

            loader = loader or load_checkpoint
            predictor = predictor or predict_images
        self.resolver = resolver
        self.loader = loader
        self.predictor = predictor
        self._models: dict[str, Any] = {}
        self._lock = threading.Lock()

    def predict(self, run_id: str, image: Image.Image) -> tuple[Any, ModelIdentity]:
        resolved = self.resolver.resolve(run_id)
        key = resolved.identity.checkpoint_sha256
        with self._lock:
            classifier = self._models.get(key)
            if classifier is None:
                classifier = self.loader(resolved.path)
                self._models = {key: classifier}
        prediction = self.predictor(classifier, [image])[0]
        return prediction, resolved.identity


def _decode_image(payload: bytes, max_pixels: int) -> Image.Image:
    import io

    try:
        with Image.open(io.BytesIO(payload)) as image:
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > max_pixels:
                raise InferenceRequestError("image dimensions are not allowed", status_code=413)
            image.load()
            return image.convert("RGB")
    except InferenceRequestError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise InferenceRequestError("file is not a valid image") from error


def build_inference_app(
    service: InferenceService | None = None,
    *,
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
    max_image_pixels: int = DEFAULT_MAX_IMAGE_PIXELS,
) -> Starlette:
    if service is None:
        service = InferenceService(
            MlflowCheckpointResolver(
                cache_dir=Path(
                    os.environ.get("CLASSIFIER_INFERENCE_CACHE", str(DEFAULT_CACHE_DIR))
                ),
            )
        )

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def predict(request: Request) -> JSONResponse:
        content_length = request.headers.get("content-length")
        if (
            content_length
            and content_length.isdigit()
            and int(content_length) > max_image_bytes + 65536
        ):
            return JSONResponse({"error": "image is too large"}, status_code=413)
        try:
            async with request.form(
                max_files=1, max_fields=2, max_part_size=max_image_bytes
            ) as form:
                if set(form) != {"file", "runId"}:
                    raise InferenceRequestError("multipart fields must be exactly file and runId")
                upload = form["file"]
                run_id = form["runId"]
                if not isinstance(upload, UploadFile) or not isinstance(run_id, str):
                    raise InferenceRequestError("file and runId are required")
                if upload.content_type not in ALLOWED_CONTENT_TYPES:
                    raise InferenceRequestError("file type is not allowed", status_code=415)
                payload = await upload.read(max_image_bytes + 1)
                if len(payload) > max_image_bytes:
                    raise InferenceRequestError("image is too large", status_code=413)
            image = _decode_image(payload, max_image_pixels)
            result, identity = await run_in_threadpool(service.predict, run_id, image)
        except InferenceRequestError as error:
            return JSONResponse({"error": str(error)}, status_code=error.status_code)
        except Exception:
            # Do not leak MLflow locations, local paths, framework errors or checkpoint data.
            return JSONResponse({"error": "inference service unavailable"}, status_code=503)

        return JSONResponse(
            {
                "model": {
                    "runId": identity.run_id,
                    "runName": identity.run_name,
                    "checkpointSha256": identity.checkpoint_sha256,
                },
                "predictedClass": result.label,
                "confidence": result.confidence,
                "probabilities": result.probabilities,
            }
        )

    return Starlette(
        routes=[Route("/health", health), Route("/predict", predict, methods=["POST"])]
    )
