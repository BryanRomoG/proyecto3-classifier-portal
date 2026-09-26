"""Thin HTTP layer over the Copilot agent, for the Web App's chat screen.

`server.py` stays the real MCP protocol surface (for Claude Desktop, another
agent). This module doesn't replace it -- it gives
`frontend/src/pages/dataset/Copilot.tsx` a plain JSON endpoint to ask a
question through, calling the exact same `answer_question` agent loop and
MCP server underneath (see agent.py's own docstring: "no separate code
path").

Split the same way `tools.py` / `server.py` already are: `handle_query` is
the real logic (validate the request body, run the agent loop, decide what
kind of failure this is) and is what tests exercise directly, with no ASGI
request/response involved. `build_app` is a thin Starlette adapter around
it that only maps outcomes to status codes -- it never invents its own
error text, and it never lets a raw exception (or its traceback) reach the
HTTP response body.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from dataset_quality.copilot.agent import CopilotAnswer, CopilotProviderError, answer_question
from dataset_quality.copilot.providers import LLMProvider

MAX_QUESTION_LENGTH = 2000


class InvalidQuestionError(Exception):
    """The request body isn't a usable question. Maps to HTTP 400."""


class CopilotUnavailableError(Exception):
    """The Copilot can't answer right now (e.g. no ANTHROPIC_API_KEY configured).

    Distinct from CopilotProviderError (a configured provider that failed
    mid-call, HTTP 502): this is "never configured", HTTP 503.
    """


class ServerLike(Protocol):
    """What `handle_query` needs from an MCP server: just `call_tool`, the
    same subset `answer_question` itself depends on."""

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


async def handle_query(
    payload: Any,
    *,
    server: ServerLike,
    provider: LLMProvider,
    tool_specs: list[dict[str, Any]],
) -> CopilotAnswer:
    """Validate ``payload`` as a question and answer it through the agent loop.

    Raises ``InvalidQuestionError`` for a bad request body and
    ``CopilotProviderError`` (from ``answer_question`` itself) for anything
    that goes wrong actually answering it -- the split ``build_app`` maps to
    400 vs. 502.
    """

    if not isinstance(payload, dict):
        raise InvalidQuestionError("El cuerpo debe ser un objeto JSON.")

    question = payload.get("question")
    if not isinstance(question, str) or not question.strip():
        raise InvalidQuestionError("Falta 'question' (texto no vacío).")
    if len(question) > MAX_QUESTION_LENGTH:
        raise InvalidQuestionError(
            f"La pregunta es demasiado larga (máximo {MAX_QUESTION_LENGTH} caracteres)."
        )

    return await answer_question(question, server=server, provider=provider, tool_specs=tool_specs)


def build_app(
    *,
    server: ServerLike,
    provider_factory: Callable[[], LLMProvider],
    tool_specs: list[dict[str, Any]],
) -> Starlette:
    """Build the Copilot's HTTP app.

    ``provider_factory`` is a zero-argument callable returning an
    ``LLMProvider`` (or raising), called **per request** rather than once at
    import time -- so a missing/invalid ``ANTHROPIC_API_KEY`` surfaces as a
    clean 503 on the next question asked, instead of crash-looping the whole
    process at startup the way the Node backend's eager `env.ts` parse does
    (see the CRLF/`.env` friction that caused on APP-09's clean-clone
    validation -- deliberately not repeating that pattern here).
    """

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def query(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"error": "El cuerpo debe ser JSON válido."}, status_code=400)

        try:
            provider = provider_factory()
        except Exception:
            return JSONResponse(
                {"error": "El Copilot no está configurado (falta ANTHROPIC_API_KEY)."},
                status_code=503,
            )

        try:
            answer = await handle_query(
                payload, server=server, provider=provider, tool_specs=tool_specs
            )
        except InvalidQuestionError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except CopilotProviderError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)

        return JSONResponse(answer.model_dump(mode="json"))

    return Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/query", query, methods=["POST"]),
        ]
    )
