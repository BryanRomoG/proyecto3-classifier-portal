"""Tests for the Copilot's HTTP layer (copilot/http_app.py).

`handle_query` (the real logic) is exercised directly, no HTTP involved --
same split as the rest of the copilot package (tools.py's pure functions vs.
server.py's thin MCP wiring). `build_app`'s routing/status-code mapping gets
a light integration pass via `_call`, a small hand-rolled ASGI caller --
deliberately not adding httpx as a new dependency just to get Starlette's
TestClient, since `handle_query` is where the actual behavior lives.

Async calls are driven with `asyncio.run(...)` from plain sync test
functions, matching the rest of this package's tests (no pytest-asyncio
plugin is installed).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from test_copilot import FakeProvider, RaisingProvider, _write_contracts

from dataset_quality.copilot.agent import CopilotProviderError, tool_specs_from_server
from dataset_quality.copilot.http_app import InvalidQuestionError, build_app, handle_query
from dataset_quality.copilot.providers import ProviderTurn, ToolCall
from dataset_quality.copilot.server import build_server


async def _call(app, method: str, path: str, json_body: object | None = None):
    """Drive `app` (an ASGI callable) through one request with no real
    network/socket involved, and return (status, parsed_json_body_or_None)."""

    body = b"" if json_body is None else json.dumps(json_body).encode("utf-8")
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

    await app(scope, receive, send)

    start = next(m for m in sent if m["type"] == "http.response.start")
    body_msg = next(m for m in sent if m["type"] == "http.response.body")
    status = start["status"]
    payload = json.loads(body_msg["body"]) if body_msg["body"] else None
    return status, payload


def _server_and_specs(tmp_path: Path):
    server = build_server(_write_contracts(tmp_path))
    return server, tool_specs_from_server(server)


# ---------------------------------------------------------------------------
# handle_query: the real logic, tested directly
# ---------------------------------------------------------------------------


def test_handle_query_answers_a_valid_question(tmp_path: Path) -> None:
    server, specs = _server_and_specs(tmp_path)
    provider = FakeProvider(
        [
            ProviderTurn(tool_calls=[ToolCall(name="get_version_history")]),
            ProviderTurn(final_answer="La versión actual es v-test-1."),
        ]
    )

    answer = asyncio.run(
        handle_query(
            {"question": "¿Cuál es la versión actual?"},
            server=server,
            provider=provider,
            tool_specs=specs,
        )
    )

    assert answer.answer == "La versión actual es v-test-1."
    assert answer.dataset_version == "v-test-1"
    assert answer.tools_used == ["get_version_history"]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "just a string",
        {},
        {"question": ""},
        {"question": "   "},
        {"question": 42},
        {"question": "x" * 2001},
    ],
)
def test_handle_query_rejects_bad_request_bodies(tmp_path: Path, payload: object) -> None:
    server, specs = _server_and_specs(tmp_path)

    with pytest.raises(InvalidQuestionError):
        asyncio.run(
            handle_query(payload, server=server, provider=FakeProvider([]), tool_specs=specs)
        )


def test_handle_query_propagates_copilot_provider_error_without_a_raw_traceback(
    tmp_path: Path,
) -> None:
    server, specs = _server_and_specs(tmp_path)

    with pytest.raises(CopilotProviderError) as exc_info:
        asyncio.run(
            handle_query(
                {"question": "?"}, server=server, provider=RaisingProvider(), tool_specs=specs
            )
        )

    assert "api.anthropic.internal" not in str(exc_info.value)
    assert "traceback" not in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# build_app: routing and status-code mapping
# ---------------------------------------------------------------------------


def test_get_health_returns_200_ok(tmp_path: Path) -> None:
    server, specs = _server_and_specs(tmp_path)
    app = build_app(server=server, provider_factory=lambda: FakeProvider([]), tool_specs=specs)

    status, payload = asyncio.run(_call(app, "GET", "/health"))

    assert status == 200
    assert payload == {"status": "ok"}


def test_post_query_with_a_valid_question_returns_200_and_the_answer(tmp_path: Path) -> None:
    server, specs = _server_and_specs(tmp_path)
    provider = FakeProvider([ProviderTurn(final_answer="Todo en orden.")])
    app = build_app(server=server, provider_factory=lambda: provider, tool_specs=specs)

    status, payload = asyncio.run(_call(app, "POST", "/query", {"question": "¿Todo bien?"}))

    assert status == 200
    assert payload["answer"] == "Todo en orden."
    assert payload["tools_used"] == []


def test_post_query_with_no_question_returns_400(tmp_path: Path) -> None:
    server, specs = _server_and_specs(tmp_path)
    app = build_app(server=server, provider_factory=lambda: FakeProvider([]), tool_specs=specs)

    status, payload = asyncio.run(_call(app, "POST", "/query", {}))

    assert status == 400
    assert "question" in payload["error"]


def test_post_query_when_provider_is_not_configured_returns_503_not_a_crash(
    tmp_path: Path,
) -> None:
    server, specs = _server_and_specs(tmp_path)

    def _factory():
        raise ValueError("ANTHROPIC_API_KEY is not set.")

    app = build_app(server=server, provider_factory=_factory, tool_specs=specs)

    status, payload = asyncio.run(_call(app, "POST", "/query", {"question": "?"}))

    # A fixed, operator-facing message naming the missing setting is fine (it's
    # our own string, not the raw exception) -- what matters is the process
    # answers cleanly instead of crash-looping the whole service at startup.
    assert status == 503
    # the raw ValueError text specifically must not leak into the response
    assert "is not set" not in payload["error"]


def test_post_query_when_the_provider_fails_returns_502_not_a_raw_traceback(
    tmp_path: Path,
) -> None:
    server, specs = _server_and_specs(tmp_path)
    app = build_app(server=server, provider_factory=lambda: RaisingProvider(), tool_specs=specs)

    status, payload = asyncio.run(_call(app, "POST", "/query", {"question": "?"}))

    assert status == 502
    assert "api.anthropic.internal" not in payload["error"]
    assert "Traceback" not in payload["error"]
