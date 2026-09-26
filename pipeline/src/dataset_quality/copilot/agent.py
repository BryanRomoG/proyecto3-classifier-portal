"""The grounded agent loop: turns a question into tool calls into an answer.

Deliberately thin. The agent never puts a number in front of the provider
that didn't come out of a tool result, and never puts a number in the final
``CopilotAnswer`` that the provider didn't produce from those tool results —
groundedness is a property of *who is allowed to originate text*, not
something checked after the fact.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict, Field

from dataset_quality.copilot.providers import LLMProvider


class CopilotAnswer(BaseModel):
    """A grounded Copilot answer: the text, plus what it's grounded in."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    dataset_version: str | None
    tools_used: list[str]


class CopilotProviderError(Exception):
    """Raised when the LLM provider fails or misbehaves.

    The message is always a short, fixed summary — never the provider
    exception's own text or traceback — so a raw stack trace (which can
    carry request internals) never reaches a caller. The original exception
    is still chained via ``__cause__`` for server-side logging.
    """


DEFAULT_MAX_TOOL_CALLS = 4


async def answer_question(
    question: str,
    *,
    server: MCPServer,
    provider: LLMProvider,
    tool_specs: list[dict],
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
) -> CopilotAnswer:
    """Answer ``question`` by letting ``provider`` call tools on ``server``.

    Loops: ask the provider for its next turn; if it wants tools, run them
    through ``server.call_tool`` (the same MCP server external clients talk
    to — no separate code path) and feed the results back; stop as soon as
    the provider returns a final answer. Raises ``CopilotProviderError`` if
    the provider errors out or exhausts ``max_tool_calls`` without settling
    on an answer.
    """

    history: list[dict] = []
    tools_used: list[str] = []
    dataset_version: str | None = None

    for _ in range(max_tool_calls + 1):
        try:
            turn = provider.next_turn(question=question, tool_specs=tool_specs, history=history)
        except Exception as exc:
            raise CopilotProviderError(
                "The Copilot's language model provider is unavailable right now."
            ) from exc

        if turn.final_answer is not None:
            return CopilotAnswer(
                answer=turn.final_answer,
                dataset_version=dataset_version,
                tools_used=tools_used,
            )

        if not turn.tool_calls:
            raise CopilotProviderError(
                "The Copilot's language model provider returned neither an answer nor a tool call."
            )

        for call in turn.tool_calls:
            try:
                result = await server.call_tool(call.name, call.arguments)
            except Exception as exc:
                raise CopilotProviderError(f"Tool '{call.name}' could not be run.") from exc
            if result.is_error:
                raise CopilotProviderError(f"Tool '{call.name}' failed.")

            payload = json.loads(result.content[0].text)
            tools_used.append(call.name)
            if dataset_version is None and isinstance(payload, dict):
                # Every tool payload names the dataset it describes, but not
                # under the same key: get_quality_report / get_split_report /
                # get_release_blockers all echo the contract's own
                # `dataset_version` field, while get_version_history's
                # payload is VersionsReport.model_dump(), which only has
                # `current_version` at the top level (see
                # copilot/contracts.py). Falling back to `current_version`
                # is what makes "dataset version appears in responses" true
                # for that tool too -- see the review fix in
                # tests/test_app08_adversarial.py.
                dataset_version = payload.get("dataset_version") or payload.get("current_version")
            history.append({"tool": call.name, "arguments": call.arguments, "result": payload})

    raise CopilotProviderError(
        "The Copilot could not reach a grounded answer within the tool-call budget."
    )


def tool_specs_from_server(server: MCPServer) -> list[dict]:
    """Build the ``tool_specs`` list ``answer_question`` (and a provider) needs,
    straight from the MCP server's own registered tools — one source of truth."""

    import asyncio

    async def _list() -> list[dict]:
        return [
            {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
            for tool in await server.list_tools()
        ]

    return asyncio.run(_list())


def default_contracts_dir(repo_root: Path | None = None) -> Path:
    """Default location of the pipeline's real output: ``pipeline/data/interim/``.

    Review finding (APP-10 smoke test, same bug class as Mau's APP-07 review
    on the Node backend, SPEC-PIPE-001): this used to default to repo-root
    ``contracts/`` -- the versioned APP-01/APP-05 mock -- instead of
    ``pipeline/data/interim/``, where ``pipeline/dvc.yaml``'s
    ``quality_gate``/``split``/``release`` stages actually write
    quality.json/splits.json/versions.json. With the old default, running
    `dvc repro` never changed what the Copilot could see, exactly like it
    never changed what the Web App displayed before the APP-07 fix. See
    contracts/README.md, "Reconciliación con APP-07", for the Node-side
    counterpart of this same fix.
    """

    root = repo_root or Path(__file__).resolve().parents[4]
    return root / "pipeline" / "data" / "interim"
