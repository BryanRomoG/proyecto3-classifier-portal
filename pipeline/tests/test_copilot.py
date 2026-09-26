from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from pydantic import ValidationError

import dataset_quality.copilot.server as server_module
from dataset_quality.copilot.agent import (
    CopilotProviderError,
    answer_question,
    default_contracts_dir,
    tool_specs_from_server,
)
from dataset_quality.copilot.contracts import VersionsReport
from dataset_quality.copilot.providers import AnthropicProvider, ProviderTurn, ToolCall
from dataset_quality.copilot.server import TOOL_NAMES, build_server
from dataset_quality.copilot.store import ContractStore
from dataset_quality.copilot.tools import TOOL_HANDLERS, get_release_blockers

QUALITY_JSON = {
    "dataset_version": "v-test-1",
    "generated_at": "2026-09-17T00:00:00Z",
    "overall_status": "fail",
    "checks": [
        {
            "id": "min_images_per_class",
            "label": "Minimum images per class",
            "severity": "fail",
            "status": "fail",
            "threshold": 300,
            "observed": 214,
            "unit": "images",
            "details": {},
            "offending_samples": [{"image_id": "img_1", "class": "bicycle"}],
        },
        {
            "id": "invalid_boxes",
            "label": "Invalid boxes",
            "severity": "fail",
            "status": "pass",
            "threshold": 0,
            "observed": 0,
            "unit": "count",
            "details": {},
            "offending_samples": [],
        },
        {
            "id": "class_imbalance",
            "label": "Class imbalance ratio",
            "severity": "warn",
            "status": "warn",
            "threshold": 3.0,
            "observed": 4.2,
            "unit": "ratio",
            "details": {},
            "offending_samples": [],
        },
    ],
}

SPLITS_JSON = {
    "dataset_version": "v-test-1",
    "generated_at": "2026-09-17T00:00:00Z",
    "seed": 42,
    "proportions": {"train": 0.7, "val": 0.15, "test": 0.15},
    "tolerance": 0.02,
    "totals": {"images": 100, "train": 70, "val": 15, "test": 15},
    "class_distribution": {
        "train": {"car": 40, "bicycle": 20},
        "val": {"car": 9, "bicycle": 4},
        "test": {"car": 9, "bicycle": 4},
    },
    "leakage_check": {
        "status": "pass",
        "leaked_pairs": 0,
        "near_duplicate_pairs_checked": 0,
        "near_duplicate_pairs_same_split": 0,
    },
    "reproducibility_check": {"status": "pass", "note": "Two runs matched."},
}

VERSIONS_JSON = {
    "current_version": "v-test-1",
    "versions": [
        {
            "version": "v-test-1",
            "released_at": "2026-09-17T00:00:00Z",
            "content_hash": "sha256:test",
            "quality_status": "fail",
            "environments": {
                "dev": {
                    "provider": "minio",
                    "status": "synced",
                    "synced_at": "2026-09-17T00:05:00Z",
                },
                "prod": {"provider": "s3", "status": "blocked_by_quality_gate", "synced_at": None},
            },
            "diff_from_previous": None,
        }
    ],
}


def _write_contracts(tmp_path: Path) -> Path:
    (tmp_path / "quality.json").write_text(json.dumps(QUALITY_JSON), encoding="utf-8")
    (tmp_path / "splits.json").write_text(json.dumps(SPLITS_JSON), encoding="utf-8")
    (tmp_path / "versions.json").write_text(json.dumps(VERSIONS_JSON), encoding="utf-8")
    return tmp_path


def _server_and_specs(contracts_dir: Path):
    server = build_server(contracts_dir)
    return server, tool_specs_from_server(server)


class FakeProvider:
    """Scripted LLMProvider: returns each turn in ``turns`` in order."""

    def __init__(self, turns: list[ProviderTurn]) -> None:
        self._turns = list(turns)
        self.calls = 0

    def next_turn(
        self, *, question: str, tool_specs: list[dict], history: list[dict]
    ) -> ProviderTurn:
        self.calls += 1
        return self._turns.pop(0)


class RaisingProvider:
    """An LLMProvider that always blows up, to test error handling."""

    def next_turn(
        self, *, question: str, tool_specs: list[dict], history: list[dict]
    ) -> ProviderTurn:
        raise RuntimeError(
            "connection reset by peer at api.anthropic.internal:443 — full stack trace follows"
        )


# ---------------------------------------------------------------------------
# MCP server: tools have a name, description and input schema; none can write
# ---------------------------------------------------------------------------


def test_mcp_server_exposes_the_four_read_only_tools_with_name_description_and_schema(
    tmp_path: Path,
) -> None:
    server = build_server(_write_contracts(tmp_path))

    tools = asyncio.run(server.list_tools())

    assert {tool.name for tool in tools} == set(TOOL_NAMES)
    for tool in tools:
        assert tool.name
        assert tool.description and len(tool.description) > 10
        assert isinstance(tool.input_schema, dict)


def test_tool_handlers_and_registered_mcp_tool_names_stay_in_sync() -> None:
    assert set(TOOL_HANDLERS) == set(TOOL_NAMES)


def test_no_write_capable_code_anywhere_in_the_copilot_package() -> None:
    package_dir = Path(server_module.__file__).parent
    # Call-syntax / import-syntax specific, so this doesn't trip on the module's
    # own docstrings *talking about* the forbidden actions (see module docstrings
    # in server.py / store.py).
    forbidden = (
        "INSERT INTO ",
        "DELETE FROM ",
        "PUT_OBJECT(",
        "DROP TABLE ",
        "IMPORT BOTO3",
        "IMPORT PYMYSQL",
        "IMPORT SQLALCHEMY",
        "IMPORT MINIO",
    )
    for path in package_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8").upper()
        for term in forbidden:
            assert term not in text, f"{path} contains forbidden write-capable term {term!r}"


def test_get_release_blockers_only_counts_failing_severity_checks_not_passing(
    tmp_path: Path,
) -> None:
    store = ContractStore(_write_contracts(tmp_path))

    payload = get_release_blockers(store)

    blocking_ids = {check["id"] for check in payload["blocking_checks"]}
    assert blocking_ids == {"min_images_per_class"}  # severity=fail, status=fail
    assert payload["is_blocked"] is True
    assert payload["dataset_version"] == "v-test-1"


def test_release_blockers_payload_changes_when_the_underlying_quality_json_changes(
    tmp_path: Path,
) -> None:
    contracts_dir = _write_contracts(tmp_path)
    store = ContractStore(contracts_dir)

    before = get_release_blockers(store)
    assert before["is_blocked"] is True

    now_passing = json.loads(json.dumps(QUALITY_JSON))
    now_passing["overall_status"] = "pass"
    now_passing["checks"][0]["status"] = "pass"
    now_passing["checks"][0]["observed"] = 300
    (contracts_dir / "quality.json").write_text(json.dumps(now_passing), encoding="utf-8")

    after = get_release_blockers(store)
    assert after["is_blocked"] is False
    assert after != before


# ---------------------------------------------------------------------------
# versions.json contract (new for APP-06 — versions.json had no strict model)
# ---------------------------------------------------------------------------


def test_versions_report_rejects_fields_outside_the_contract() -> None:
    payload = json.loads(json.dumps(VERSIONS_JSON))
    payload["_note"] = "not part of the contract"

    with pytest.raises(ValidationError, match="_note"):
        VersionsReport.model_validate(payload)


def test_real_versions_contract_validates_with_the_new_model() -> None:
    project_root = Path(os.environ.get("PROJECT_ROOT", Path(__file__).parents[2]))
    payload = json.loads((project_root / "contracts" / "versions.json").read_text(encoding="utf-8"))

    report = VersionsReport.model_validate(payload)

    assert report.current_version == "v0.2.0-mock"
    assert report.versions[0].environments.dev.status == "synced"


# ---------------------------------------------------------------------------
# Agent loop: grounding, dataset version / tools used, errors, budgets
# ---------------------------------------------------------------------------


def test_answer_question_grounds_the_answer_in_a_tool_result(tmp_path: Path) -> None:
    server, specs = _server_and_specs(_write_contracts(tmp_path))
    provider = FakeProvider(
        [
            ProviderTurn(tool_calls=[ToolCall(name="get_release_blockers")]),
            ProviderTurn(
                final_answer=(
                    "El release está bloqueado por min_images_per_class: 214 de 300 imágenes."
                )
            ),
        ]
    )

    result = asyncio.run(
        answer_question(
            "¿Por qué está bloqueado el release?",
            server=server,
            provider=provider,
            tool_specs=specs,
        )
    )

    assert result.dataset_version == "v-test-1"
    assert result.tools_used == ["get_release_blockers"]
    assert "214" in result.answer  # the number came from the tool result


def test_answer_question_lets_the_provider_decline_out_of_scope_questions(tmp_path: Path) -> None:
    server, specs = _server_and_specs(_write_contracts(tmp_path))
    provider = FakeProvider(
        [
            ProviderTurn(
                final_answer="No tengo herramientas para responder eso — está fuera del dataset."
            )
        ]
    )

    result = asyncio.run(
        answer_question(
            "¿Cuál es la capital de Francia?", server=server, provider=provider, tool_specs=specs
        )
    )

    assert result.tools_used == []
    assert result.dataset_version is None
    assert "fuera del dataset" in result.answer


def test_answer_question_wraps_provider_errors_without_a_raw_traceback(tmp_path: Path) -> None:
    server, specs = _server_and_specs(_write_contracts(tmp_path))

    with pytest.raises(CopilotProviderError) as exc_info:
        asyncio.run(
            answer_question("¿Algo?", server=server, provider=RaisingProvider(), tool_specs=specs)
        )

    message = str(exc_info.value)
    assert "Traceback" not in message
    assert "api.anthropic.internal" not in message  # raw exception text never leaks out
    assert exc_info.value.__cause__ is not None  # still chained for server-side logging


def test_answer_question_wraps_unknown_tool_requests_cleanly(tmp_path: Path) -> None:
    server, specs = _server_and_specs(_write_contracts(tmp_path))
    provider = FakeProvider([ProviderTurn(tool_calls=[ToolCall(name="delete_everything")])])

    with pytest.raises(CopilotProviderError) as exc_info:
        asyncio.run(answer_question("?", server=server, provider=provider, tool_specs=specs))

    assert "Traceback" not in str(exc_info.value)


def test_answer_question_gives_up_after_the_tool_call_budget(tmp_path: Path) -> None:
    server, specs = _server_and_specs(_write_contracts(tmp_path))
    provider = FakeProvider(
        [ProviderTurn(tool_calls=[ToolCall(name="get_quality_report")]) for _ in range(5)]
    )

    with pytest.raises(CopilotProviderError, match="tool-call budget"):
        asyncio.run(
            answer_question(
                "?", server=server, provider=provider, tool_specs=specs, max_tool_calls=2
            )
        )


# ---------------------------------------------------------------------------
# Provider: API key from environment configuration, clean errors
# ---------------------------------------------------------------------------


def test_anthropic_provider_requires_an_api_key_from_settings() -> None:
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        AnthropicProvider.from_settings(api_key=None, model="claude-sonnet-4-5")


def test_anthropic_provider_builds_a_client_when_a_key_is_configured() -> None:
    provider = AnthropicProvider.from_settings(
        api_key="sk-test-not-a-real-key", model="claude-sonnet-4-5"
    )

    assert provider._model == "claude-sonnet-4-5"


@dataclass
class _FakeBlock:
    type: str
    text: str = ""
    name: str = ""
    input: dict = field(default_factory=dict)


@dataclass
class _FakeMessage:
    content: list


class _FakeMessagesEndpoint:
    def __init__(self, response: _FakeMessage) -> None:
        self._response = response

    def create(self, **_kwargs: object) -> _FakeMessage:
        return self._response


class _FakeAnthropicClient:
    def __init__(self, response: _FakeMessage) -> None:
        self.messages = _FakeMessagesEndpoint(response)


def test_anthropic_provider_maps_a_tool_use_response_into_a_tool_call() -> None:
    response = _FakeMessage(
        content=[_FakeBlock(type="tool_use", name="get_quality_report", input={})]
    )
    provider = AnthropicProvider(_FakeAnthropicClient(response), model="claude-sonnet-4-5")

    turn = provider.next_turn(
        question="?",
        tool_specs=[{"name": "get_quality_report", "description": "d", "input_schema": {}}],
        history=[],
    )

    assert turn.tool_calls == [ToolCall(name="get_quality_report", arguments={})]
    assert turn.final_answer is None


def test_anthropic_provider_maps_a_text_response_into_a_final_answer() -> None:
    response = _FakeMessage(content=[_FakeBlock(type="text", text="La respuesta es 42.")])
    provider = AnthropicProvider(_FakeAnthropicClient(response), model="claude-sonnet-4-5")

    turn = provider.next_turn(question="?", tool_specs=[], history=[])

    assert turn.tool_calls == []
    assert turn.final_answer == "La respuesta es 42."


def test_default_contracts_dir_resolves_to_pipeline_data_interim_not_contracts(
    tmp_path: Path,
) -> None:
    """Review finding (same bug class as Mau's APP-07 review on the Node backend,
    SPEC-PIPE-001): the Copilot's ``ContractStore`` only ever reads whatever
    directory it's built with, and this default pointed it at repo-root
    ``contracts/`` -- the versioned APP-01/APP-05 mock -- instead of
    ``pipeline/data/interim/``, where ``pipeline/dvc.yaml``'s
    ``quality_gate``/``split``/``release`` stages actually write
    quality.json/splits.json/versions.json. With the old default, running
    `dvc repro` never changed what the Copilot could see, same as it never
    changed what the Web App displayed before the APP-07 fix.
    """

    repo_root = tmp_path / "repo"
    (repo_root / "pipeline" / "data" / "interim").mkdir(parents=True)
    (repo_root / "contracts").mkdir(parents=True)

    resolved = default_contracts_dir(repo_root)

    assert resolved == repo_root / "pipeline" / "data" / "interim"
    assert resolved.name != "contracts"
