"""HTTP API for training configs: the contract the portal and job creation call first.

Rubric 2.2 / plan T3-1.4: an invalid value must be rejected, with a useful message, by the
API and by the portal *before* a training job exists. Both go through this service, which
validates with the very same ``TrainingConfig`` the trainer reads (``config.py``), so the
API cannot accept a value the trainer would refuse, nor show a field the trainer ignores.

Routes (mounted by nginx under ``/classifier-api/``):

* ``GET  /health``
* ``GET  /training/schema``   -- JSON Schema of ``TrainingConfig`` (ranges, defaults) so the
  Training form mirrors the trainer's rules instead of copying them.
* ``POST /training/validate`` -- 200 ``{"valid": true, "config": <effective config>}`` or
  422 ``{"valid": false, "errors": [{"field", "message"}, ...]}``. Nothing is created.

Same split as ``copilot/http_app.py``: ``handle_validate`` is the logic tests call directly;
``build_app`` only maps its outcome to status codes. This module imports ``config`` only
(no torch, no MLflow), so the service starts on the base pipeline image.
"""

from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from dataset_quality.classifier.config import TrainingConfig, json_schema, validation_issues


def handle_validate(payload: Any) -> tuple[int, dict[str, Any]]:
    """Validate a candidate config; return ``(status, body)``. Never creates anything."""

    if not isinstance(payload, dict):
        return 422, {
            "valid": False,
            "errors": [{"field": "<root>", "message": "El cuerpo debe ser un objeto JSON."}],
        }
    issues = validation_issues(payload)
    if issues:
        return 422, {"valid": False, "errors": issues}
    config = TrainingConfig.model_validate(payload)
    return 200, {"valid": True, "config": config.model_dump(mode="json")}


def build_app() -> Starlette:
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def schema(_request: Request) -> JSONResponse:
        return JSONResponse(json_schema())

    async def validate(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(
                {
                    "valid": False,
                    "errors": [{"field": "<root>", "message": "El cuerpo debe ser JSON válido."}],
                },
                status_code=400,
            )
        status, body = handle_validate(payload)
        return JSONResponse(body, status_code=status)

    return Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/training/schema", schema, methods=["GET"]),
            Route("/training/validate", validate, methods=["POST"]),
        ]
    )
