"""LLM providers behind the Copilot agent — swappable, so the ticket isn't
blocked on having a real API key, and so the agent loop never depends on any
one vendor's SDK.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolCall:
    """One tool the provider wants the agent to run before it can answer."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderTurn:
    """One step of the provider's turn: either more tool calls, or a final answer.

    Exactly one of ``tool_calls`` / ``final_answer`` is meaningful: a
    non-empty ``tool_calls`` means "run these and call me again with the
    results"; ``final_answer`` set means the provider is done.
    """

    tool_calls: list[ToolCall] = field(default_factory=list)
    final_answer: str | None = None


class LLMProvider(Protocol):
    """What the agent loop needs from an LLM provider. Anthropic, OpenAI, a
    test double — anything implementing this works with ``agent.answer_question``.
    """

    def next_turn(
        self,
        *,
        question: str,
        tool_specs: list[dict[str, Any]],
        history: list[dict[str, Any]],
    ) -> ProviderTurn:
        """Given the question, the available tools, and prior tool results
        (``history``, in call order), return the next turn."""
        ...


class AnthropicProvider:
    """Grounds answers using Claude's tool-use loop (Anthropic Messages API).

    The network client is injected (``client``) so the request/response
    mapping can be unit-tested without a real API key or network access —
    see ``tests/test_copilot.py``. In production, ``from_settings`` builds a
    real ``anthropic.Anthropic`` client from ``ANTHROPIC_API_KEY``.
    """

    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    @classmethod
    def from_settings(cls, *, api_key: str | None, model: str) -> AnthropicProvider:
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. Configure it in the environment "
                "(see .env.example) before using AnthropicProvider."
            )
        import anthropic

        return cls(anthropic.Anthropic(api_key=api_key), model)

    def next_turn(
        self,
        *,
        question: str,
        tool_specs: list[dict[str, Any]],
        history: list[dict[str, Any]],
    ) -> ProviderTurn:
        messages = _build_anthropic_messages(question, history)
        tools = [
            {
                "name": spec["name"],
                "description": spec["description"],
                "input_schema": spec["input_schema"],
            }
            for spec in tool_specs
        ]

        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=(
                "You are the Dataset Copilot for a dataset-quality project. "
                "Answer only using the provided tools — never invent counts, "
                "statuses or thresholds. If the question is outside what the "
                "tools can answer, say so plainly instead of guessing."
            ),
            tools=tools,
            messages=messages,
        )

        tool_calls = [
            ToolCall(name=block.name, arguments=dict(block.input))
            for block in response.content
            if block.type == "tool_use"
        ]
        if tool_calls:
            return ProviderTurn(tool_calls=tool_calls)

        text = "".join(block.text for block in response.content if block.type == "text")
        return ProviderTurn(final_answer=text)


def _build_anthropic_messages(question: str, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replay ``history`` (generic tool-call log) as an Anthropic message list.

    Rebuilt from scratch each call instead of kept as provider state, so
    ``AnthropicProvider`` stays a thin, stateless mapper — the agent loop
    (``agent.py``) owns the conversation.
    """

    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    for turn_index, entry in enumerate(history):
        tool_use_id = f"tool_{turn_index}"
        messages.append(
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": tool_use_id,
                        "name": entry["tool"],
                        "input": entry["arguments"],
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": json.dumps(entry["result"]),
                    }
                ],
            }
        )
    return messages
