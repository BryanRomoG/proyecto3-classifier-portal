"""APP-08 — adversarial testing of splits and Dataset Copilot behavior.

`test_splits.py` and `test_copilot.py` already cover the happy path for each
unit (one seed producing one stable assignment, one duplicate pair, one
"ask -> tool -> answer" turn). This file targets the specific adversarial
scenarios the ticket calls out that those files don't exercise:

- Splits: that train/validation/test never actually overlap (not just that
  their counts sum correctly), that near-duplicate grouping survives the
  class-coverage rebalancing pass (which moves whole groups between splits
  and is exactly the kind of internal machinery that could reintroduce
  leakage), and that per-split proportions hold up under a skewed class
  distribution, not just a balanced one.
- Copilot: that a grounded answer actually changes when the underlying
  contract data changes between two questions in the same conversation --
  the "change source data / repeat the question / verify the answer
  changes" steps from the ticket's Copilot Validation Tests, which no
  existing test drives end to end through `answer_question`.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from dataset_quality.config.models import SplitConfig
from dataset_quality.copilot.agent import answer_question, tool_specs_from_server
from dataset_quality.copilot.providers import ProviderTurn, ToolCall
from dataset_quality.copilot.server import build_server
from dataset_quality.ingestion.models import CocoAnnotation, CocoCategory, CocoDataset, CocoImage
from dataset_quality.splits.generator import generate_splits

# ---------------------------------------------------------------------------
# Splits: adversarial dataset builders
# ---------------------------------------------------------------------------


def _make_dataset(image_class_map: dict[int, list[str]]) -> CocoDataset:
    """Build a small COCO dataset from {image_id: [class_name, ...]}."""

    category_names = sorted({name for names in image_class_map.values() for name in names})
    category_id_by_name = {name: index + 1 for index, name in enumerate(category_names)}

    images = [
        CocoImage(id=image_id, file_name=f"images/img_{image_id:05d}.jpg", width=640, height=480)
        for image_id in image_class_map
    ]
    categories = [CocoCategory(id=cid, name=name) for name, cid in category_id_by_name.items()]

    annotations = []
    next_id = 1
    for image_id, class_names in image_class_map.items():
        for name in class_names:
            annotations.append(
                CocoAnnotation(
                    id=next_id,
                    image_id=image_id,
                    category_id=category_id_by_name[name],
                    bbox=[10, 10, 20, 20],
                )
            )
            next_id += 1

    return CocoDataset(images=images, annotations=annotations, categories=categories)


def _balanced_dataset(total_images: int) -> CocoDataset:
    image_class_map: dict[int, list[str]] = {}
    for image_id in range(1, total_images + 1):
        classes = []
        if image_id % 2 == 0:
            classes.append("car")
        if image_id % 3 == 0:
            classes.append("bicycle")
        if image_id % 5 == 0:
            classes.append("traffic_light")
        if not classes:
            classes.append("car")
        image_class_map[image_id] = classes
    return _make_dataset(image_class_map)


def _skewed_dataset(total_images: int) -> CocoDataset:
    """~90% majority class, a mid class, and a rare class on ~3% of images.

    Deliberately adversarial to the deficit-balanced assignment: a tiny
    minority class is exactly the case most likely to blow the configured
    tolerance if the algorithm isn't actually respecting it.
    """

    image_class_map: dict[int, list[str]] = {}
    for image_id in range(1, total_images + 1):
        classes = ["car"]
        if image_id % 7 == 0:
            classes.append("bicycle")
        if image_id % 31 == 0:
            classes.append("traffic_light")
        image_class_map[image_id] = classes
    return _make_dataset(image_class_map)


# ---------------------------------------------------------------------------
# Splits: intersections must be empty
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [1, 2, 42, 999])
@pytest.mark.parametrize("total_images", [30, 97, 240])
def test_split_assignments_never_overlap_between_train_validation_and_test(
    seed: int, total_images: int
) -> None:
    dataset = _balanced_dataset(total_images)
    config = SplitConfig(train=0.70, val=0.15, test=0.15, seed=seed)

    result = generate_splits(dataset, config, "v-test")

    train_ids = set(result.assignment["train"])
    val_ids = set(result.assignment["val"])
    test_ids = set(result.assignment["test"])

    assert train_ids & val_ids == set()
    assert train_ids & test_ids == set()
    assert val_ids & test_ids == set()
    # Every image lands in exactly one split -- no image dropped, none
    # duplicated across splits.
    assert train_ids | val_ids | test_ids == {image.id for image in dataset.images}


# ---------------------------------------------------------------------------
# Splits: near-duplicate grouping must survive class-coverage rebalancing
# ---------------------------------------------------------------------------


def test_duplicate_groups_never_split_across_splits_under_class_coverage_rebalancing() -> None:
    """The rare class only appears inside near-duplicate groups.

    This forces `_fill_class_coverage_gaps` to move whole duplicate groups
    into val/test so the rare class is represented there -- exactly the code
    path (`_move_group`) that could reintroduce leakage if it ever moved
    part of a group instead of all of it. A single well-behaved duplicate
    pair (as in `test_splits.py`) never exercises this path.
    """

    image_class_map: dict[int, list[str]] = {}
    for image_id in range(1, 61):
        image_class_map[image_id] = ["car"]
    # Three near-duplicate groups of 2 carrying the only "rare" annotations
    # in the whole dataset -- coverage rebalancing has no choice but to move
    # one of these groups (as a whole) into val and another into test.
    for image_id in (61, 62, 63, 64, 65, 66):
        image_class_map[image_id] = ["car", "rare"]
    dataset = _make_dataset(image_class_map)

    duplicate_pairs = [(61, 62), (63, 64), (65, 66)]
    config = SplitConfig(train=0.70, val=0.15, test=0.15, seed=5)

    result = generate_splits(dataset, config, "v-test", duplicate_pairs=duplicate_pairs)

    assert result.report.leakage_check.leaked_pairs == 0
    assert result.report.leakage_check.near_duplicate_pairs_checked == 3

    # Don't just trust the report -- recompute leakage directly from the
    # actual per-image assignment.
    split_of = {
        image_id: split_name
        for split_name, image_ids in result.assignment.items()
        for image_id in image_ids
    }
    for image_a, image_b in duplicate_pairs:
        assert split_of[image_a] == split_of[image_b], (
            f"near-duplicate pair ({image_a}, {image_b}) landed in different splits"
        )

    # And the rare class did in fact get donated into val/test, proving the
    # rebalancing path (the one that risked the leak) actually ran.
    for split_name in ("val", "test"):
        distribution = getattr(result.report.class_distribution, split_name)
        assert distribution.get("rare", 0) > 0, f"rare class missing from {split_name}"


# ---------------------------------------------------------------------------
# Splits: per-split proportions must hold up under a skewed class distribution
# ---------------------------------------------------------------------------


def test_split_proportions_stay_within_tolerance_for_a_heavily_skewed_class_distribution() -> None:
    dataset = _skewed_dataset(500)
    config = SplitConfig(train=0.70, val=0.15, test=0.15, seed=11)
    tolerance = 0.03

    result = generate_splits(dataset, config, "v-test", tolerance=tolerance)

    total = result.report.totals.images
    for split_name, target_proportion in (("train", 0.70), ("val", 0.15), ("test", 0.15)):
        achieved = getattr(result.report.totals, split_name) / total
        assert abs(achieved - target_proportion) <= tolerance, (
            f"{split_name} proportion {achieved:.3f} exceeds tolerance {tolerance} "
            f"of target {target_proportion}"
        )


# ---------------------------------------------------------------------------
# Copilot: change source data, repeat the question, verify the answer changes
# ---------------------------------------------------------------------------


def _write_quality_json(contracts_dir: Path, *, blocked: bool) -> None:
    payload = {
        "dataset_version": "v-test-1",
        "generated_at": "2026-09-17T00:00:00Z",
        "overall_status": "fail" if blocked else "pass",
        "checks": [
            {
                "id": "min_images_per_class",
                "label": "Minimum images per class",
                "severity": "fail",
                "status": "fail" if blocked else "pass",
                "threshold": 300,
                "observed": 214 if blocked else 300,
                "unit": "images",
                "details": {},
                "offending_samples": [],
            }
        ],
    }
    (contracts_dir / "quality.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_minimal_splits_and_versions(contracts_dir: Path) -> None:
    (contracts_dir / "splits.json").write_text(
        json.dumps(
            {
                "dataset_version": "v-test-1",
                "generated_at": "2026-09-17T00:00:00Z",
                "seed": 42,
                "proportions": {"train": 0.7, "val": 0.15, "test": 0.15},
                "tolerance": 0.02,
                "totals": {"images": 100, "train": 70, "val": 15, "test": 15},
                "class_distribution": {
                    "train": {"car": 40},
                    "val": {"car": 9},
                    "test": {"car": 9},
                },
                "leakage_check": {
                    "status": "pass",
                    "leaked_pairs": 0,
                    "near_duplicate_pairs_checked": 0,
                    "near_duplicate_pairs_same_split": 0,
                },
                "reproducibility_check": {"status": "pass", "note": "ok"},
            }
        ),
        encoding="utf-8",
    )
    (contracts_dir / "versions.json").write_text(
        json.dumps(
            {
                "current_version": "v-test-1",
                "versions": [
                    {
                        "version": "v-test-1",
                        "released_at": "2026-09-17T00:00:00Z",
                        "content_hash": "sha256:test",
                        "quality_status": "fail",
                        "environments": {
                            "dev": {"provider": "minio", "status": "synced", "synced_at": None},
                            "prod": {
                                "provider": "s3",
                                "status": "blocked_by_quality_gate",
                                "synced_at": None,
                            },
                        },
                        "diff_from_previous": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class _EchoingProvider:
    """Not scripted with canned turns like `FakeProvider` in test_copilot.py --
    this one actually reads the tool result and echoes the real numbers back,
    the way a real grounded LLM would. That's the point: it lets the test
    prove the *answer text* changed because the *tool result* changed, not
    just that some hardcoded string was swapped in.
    """

    def __init__(self) -> None:
        self.calls = 0

    def next_turn(
        self, *, question: str, tool_specs: list[dict], history: list[dict]
    ) -> ProviderTurn:
        self.calls += 1
        if not history:
            return ProviderTurn(tool_calls=[ToolCall(name="get_release_blockers")])
        last_result = history[-1]["result"]
        if last_result["is_blocked"]:
            observed = last_result["blocking_checks"][0]["observed"]
            answer = f"El release está bloqueado: {observed} de 300 imágenes por clase."
        else:
            answer = "El release no está bloqueado: todos los checks obligatorios pasan."
        return ProviderTurn(final_answer=answer)


def test_copilot_grounded_answer_reflects_source_data_changes_between_two_questions(
    tmp_path: Path,
) -> None:
    """Review note (APP-08 PR #44, @Mau): this drives `answer_question` twice,
    each call building its own internal tool-call history from scratch --
    that is correct, not an oversight. Nothing in this codebase threads a
    conversation/session object across separate questions: `answer_question`
    takes no `history` parameter from its caller (see `agent.py`), and
    `AnthropicProvider._build_anthropic_messages` rebuilds its message list
    "from scratch each call instead of kept as provider state" by its own
    docstring. So asking the same question again, the way a real chat UI
    would call `answer_question` once per user turn, IS two independent
    calls. What must carry over between them -- and what this test actually
    proves -- is that the on-disk contract data, not any in-memory
    conversation state, is what the second answer is grounded in: same
    `server`/`ContractStore` instance, no re-instantiation, only the
    `quality.json` file underneath it changes.
    """

    _write_quality_json(tmp_path, blocked=True)
    _write_minimal_splits_and_versions(tmp_path)
    server = build_server(tmp_path)
    specs = tool_specs_from_server(server)

    first = asyncio.run(
        answer_question(
            "¿Por qué está bloqueado el release?",
            server=server,
            provider=_EchoingProvider(),
            tool_specs=specs,
        )
    )
    assert first.tools_used == ["get_release_blockers"]
    assert first.dataset_version == "v-test-1"
    assert "214" in first.answer

    # Change the source data under the Copilot -- no new server, no new
    # store, nothing re-instantiated. The same `ContractStore` must pick up
    # the change because it re-reads from disk on every call (see
    # `copilot/store.py`).
    _write_quality_json(tmp_path, blocked=False)

    second = asyncio.run(
        answer_question(
            "¿Por qué está bloqueado el release?",
            server=server,
            provider=_EchoingProvider(),
            tool_specs=specs,
        )
    )

    # The tool was actually called again -- the answer isn't reused/cached
    # from the first turn.
    assert second.tools_used == ["get_release_blockers"]
    assert second.dataset_version == "v-test-1"
    assert second.answer != first.answer
    assert "214" not in second.answer
    assert "no está bloqueado" in second.answer


class _SingleToolProvider:
    """Calls exactly one named tool, then answers -- lets the dataset_version
    test below drive each of the four tools individually instead of only the
    one (`get_release_blockers`) that `_EchoingProvider` happens to call.
    """

    def __init__(self, tool_name: str) -> None:
        self._tool_name = tool_name

    def next_turn(
        self, *, question: str, tool_specs: list[dict], history: list[dict]
    ) -> ProviderTurn:
        if not history:
            return ProviderTurn(tool_calls=[ToolCall(name=self._tool_name)])
        return ProviderTurn(final_answer="ok")


@pytest.mark.parametrize(
    "tool_name",
    ["get_quality_report", "get_split_report", "get_version_history", "get_release_blockers"],
)
def test_copilot_dataset_version_is_present_for_every_tool_not_just_release_blockers(
    tool_name: str, tmp_path: Path
) -> None:
    """Review fix (APP-08 PR #44, @Mau): the original version of this test only
    ever drove `get_release_blockers`, whose handler happens to build a dict
    with an explicit `dataset_version` key. `get_version_history` doesn't --
    its payload is `VersionsReport.model_dump()`, which only has
    `current_version` at the top level -- so `answer_question`'s
    `payload.get("dataset_version")` silently returned `None` for that tool
    even though a tool genuinely was used and the report clearly names a
    dataset version. Parametrizing over all four tools makes that the kind of
    gap this test can no longer hide.
    """

    _write_quality_json(tmp_path, blocked=True)
    _write_minimal_splits_and_versions(tmp_path)
    server = build_server(tmp_path)
    specs = tool_specs_from_server(server)

    result = asyncio.run(
        answer_question(
            "¿Cuál es el estado del release?",
            server=server,
            provider=_SingleToolProvider(tool_name),
            tool_specs=specs,
        )
    )

    assert result.tools_used == [tool_name]
    assert result.dataset_version == "v-test-1", (
        f"{tool_name} was used but dataset_version was not extracted from its result"
    )
