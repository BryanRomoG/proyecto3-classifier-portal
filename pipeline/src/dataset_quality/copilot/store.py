"""Reads the shared data contracts from disk. The Copilot's only I/O.

No write methods exist here, deliberately: the Copilot only ever reads
``contracts/*.json`` — never the annotation database or object storage — so
there is nothing to add a write path to by accident. See ``server.py`` and
``tests/test_copilot.py`` for the "no write-capable tool" guardrail this
enables.
"""

from __future__ import annotations

import json
from pathlib import Path

from dataset_quality.copilot.contracts import SplitsSummary, VersionsReport
from dataset_quality.quality_gate.models import QualityReport


class ContractStore:
    """Reads ``quality.json`` / ``splits.json`` / ``versions.json`` from a directory.

    Re-reads from disk on every call (no caching), on purpose: a Copilot
    answer must reflect whatever the contracts say *right now*, including in
    the Agent Test scenario where the underlying data changes between two
    questions.
    """

    def __init__(self, contracts_dir: Path) -> None:
        self._contracts_dir = contracts_dir

    def load_quality_report(self) -> QualityReport:
        return QualityReport.model_validate(self._read_json("quality.json"))

    def load_split_report(self) -> SplitsSummary:
        return SplitsSummary.model_validate(self._read_json("splits.json"))

    def load_versions_report(self) -> VersionsReport:
        return VersionsReport.model_validate(self._read_json("versions.json"))

    def _read_json(self, filename: str) -> object:
        path = self._contracts_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"contract file not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))
