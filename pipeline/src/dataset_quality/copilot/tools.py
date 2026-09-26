"""Pure, read-only payload builders behind each Copilot MCP tool.

Every function here takes a :class:`~dataset_quality.copilot.store.ContractStore`
and returns a plain JSON-serializable ``dict`` — no side effects, no writes.
``server.py`` wraps these as MCP tool handlers; ``agent.py`` calls the same
handlers in-process through the MCP server's ``call_tool``, so there is a
single implementation behind both the real MCP server and the in-process
agent loop.
"""

from __future__ import annotations

from typing import Any

from dataset_quality.copilot.store import ContractStore


def get_quality_report(store: ContractStore) -> dict[str, Any]:
    """Current Quality Gate report: overall status, and each check's pass/warn/fail
    result with its observed value vs. threshold and any offending samples."""

    return store.load_quality_report().model_dump(mode="json")


def get_split_report(store: ContractStore) -> dict[str, Any]:
    """Current train/validation/test split report: image counts and class
    distribution per split, the seed and proportions used, and the
    leakage/reproducibility check results."""

    return store.load_split_report().model_dump(mode="json")


def get_version_history(store: ContractStore) -> dict[str, Any]:
    """Dataset version timeline: current version, each version's quality
    status, DEV (MinIO) / PROD (S3) sync status, and its diff from the
    previous version."""

    return store.load_versions_report().model_dump(mode="json")


def get_release_blockers(store: ContractStore) -> dict[str, Any]:
    """Only the Quality Gate checks currently blocking a release — those with
    severity 'fail' that are not passing — with their observed value,
    threshold and offending samples. Empty list means nothing is blocking
    the release."""

    report = store.load_quality_report()
    blocking = [
        check.model_dump(mode="json")
        for check in report.checks
        if check.severity == "fail" and check.status != "pass"
    ]
    return {
        "dataset_version": report.dataset_version,
        "overall_status": report.overall_status,
        "blocking_checks": blocking,
        "is_blocked": len(blocking) > 0,
    }


# Every tool this module exposes, by name. server.py registers each of these
# on the MCP server; tests/test_copilot.py checks the two stay in sync with
# dataset_quality.copilot.server.TOOL_NAMES.
TOOL_HANDLERS = {
    "get_quality_report": get_quality_report,
    "get_split_report": get_split_report,
    "get_version_history": get_version_history,
    "get_release_blockers": get_release_blockers,
}
