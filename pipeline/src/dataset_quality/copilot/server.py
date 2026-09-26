"""The Dataset Copilot's MCP server: four read-only tools, nothing else.

Built on the real MCP Python SDK (``mcp.server.mcpserver.MCPServer``), so name,
description and input schema for every tool come from the SDK itself — not
hand-rolled — and are inspectable via ``list_tools()`` exactly as an external
MCP client (Claude Desktop, another agent) would see them.

No tool here can write. There is no database client and no object-storage
client imported anywhere in this module or in ``tools.py`` / ``store.py`` —
the Copilot physically cannot INSERT, UPDATE, DELETE or ``put_object``,
because nothing in its dependency graph knows how. ``tests/test_copilot.py``
asserts this by scanning the source.
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.mcpserver import MCPServer

from dataset_quality.copilot.store import ContractStore
from dataset_quality.copilot.tools import (
    get_quality_report,
    get_release_blockers,
    get_split_report,
    get_version_history,
)

TOOL_NAMES: tuple[str, ...] = (
    "get_quality_report",
    "get_split_report",
    "get_version_history",
    "get_release_blockers",
)


def build_server(contracts_dir: Path) -> MCPServer:
    """Build the Copilot's MCP server, reading contracts from ``contracts_dir``."""

    store = ContractStore(contracts_dir)
    server = MCPServer(
        "dataset-copilot",
        description=(
            "Read-only Dataset Copilot: quality gate status, split composition "
            "and dataset version history for this project. Never writes to the "
            "annotation database or object storage."
        ),
    )

    @server.tool(name="get_quality_report")
    def _get_quality_report() -> dict:
        """Current Quality Gate report: overall status, and each check's pass/warn/fail
        result with its observed value vs. threshold and any offending samples."""

        return get_quality_report(store)

    @server.tool(name="get_split_report")
    def _get_split_report() -> dict:
        """Current train/validation/test split report: image counts and class
        distribution per split, the seed and proportions used, and the
        leakage/reproducibility check results."""

        return get_split_report(store)

    @server.tool(name="get_version_history")
    def _get_version_history() -> dict:
        """Dataset version timeline: current version, each version's quality
        status, DEV (MinIO) / PROD (S3) sync status, and its diff from the
        previous version."""

        return get_version_history(store)

    @server.tool(name="get_release_blockers")
    def _get_release_blockers() -> dict:
        """Only the Quality Gate checks currently blocking a release — those
        with severity 'fail' that are not passing — with their observed
        value, threshold and offending samples. Empty list means nothing is
        blocking the release."""

        return get_release_blockers(store)

    return server
