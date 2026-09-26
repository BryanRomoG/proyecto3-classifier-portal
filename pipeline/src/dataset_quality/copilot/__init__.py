"""Dataset Copilot: read-only MCP server and grounded agent. Owner: Application & AI Engineer.

Exposes the shared data contracts (``contracts/quality.json``, ``splits.json``,
``versions.json``) as MCP tools, and a small provider-agnostic agent loop that
answers questions by calling those tools — never by inventing numbers.
"""

from dataset_quality.copilot.agent import (
    CopilotAnswer,
    CopilotProviderError,
    answer_question,
    default_contracts_dir,
    tool_specs_from_server,
)
from dataset_quality.copilot.providers import AnthropicProvider, LLMProvider, ProviderTurn, ToolCall
from dataset_quality.copilot.server import TOOL_NAMES, build_server
from dataset_quality.copilot.store import ContractStore

__all__ = [
    "TOOL_NAMES",
    "AnthropicProvider",
    "ContractStore",
    "CopilotAnswer",
    "CopilotProviderError",
    "LLMProvider",
    "ProviderTurn",
    "ToolCall",
    "answer_question",
    "build_server",
    "default_contracts_dir",
    "tool_specs_from_server",
]
