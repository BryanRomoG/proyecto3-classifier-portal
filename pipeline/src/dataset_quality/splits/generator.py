"""Stratified, reproducible train/validation/test split generation (Tier 4)."""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from dataset_quality.config.models import SplitConfig
from dataset_quality.ingestion.models import CocoDataset
from dataset_quality.splits.models import (
    SplitClassDistribution,
    SplitLeakageCheck,
    SplitProportions,
    SplitReproducibilityCheck,
    SplitResult,
    SplitTotals,
)

if TYPE_CHECKING:
    from dataset_quality.quality_gate.runner import QualityGateDecision

_SPLIT_NAMES: tuple[str, ...] = ("train", "val", "test")


@dataclass(frozen=True)
class SplitGenerationResult:
    """The full per-image assignment plus the serializable summary report.

    ``assignment`` (image ids per split, sorted) is what callers use to write
    the actual dataset files; ``report`` is the ``contracts/splits.json``-shaped
    summary consumed by the Splits screen (APP-05) and DVC (OPS-04).
    """

    assignment: dict[str, list[int]]
    report: SplitResult


def generate_splits(
    dataset: CocoDataset,
    config: SplitConfig,
    dataset_version: str,
    duplicate_pairs: Sequence[tuple[int, int]] | None = None,
    tolerance: float = 0.02,
    generated_at: datetime | None = None,
    quality_gate: QualityGateDecision | None = None,
) -> SplitGenerationResult:
    """Partition every image in ``dataset`` into train/validation/test per ``config``.

    - Deterministic: the same dataset, config and ``duplicate_pairs`` always
      produce the same image-id assignment for a given seed. This is not just
      assumed — the assignment is computed twice and compared before
      returning, and the result is reported in ``reproducibility_check``.
    - Grouped: image ids linked by ``duplicate_pairs`` (near-duplicates, e.g.
      DQ-05's pHash output, once available) are always kept together in a
      single split, so cross-split leakage is impossible by construction.
    - Stratified: groups are assigned by their scarcest carried class's
      remaining deficit against the configured train/val/test ratios, not
      just by overall image count — so a minority class's own split
      proportions track the configured ratios too, the same as the totals do.
    - Covered: every category present in ``dataset`` is guaranteed to appear
      in both the validation and test splits whenever that's possible without
      un-covering a class a split already has — donating the smallest
      eligible group, preferring train, when the first pass misses one. See
      ``_fill_class_coverage_gaps`` for exactly what "possible" means here.

    Raises ``ValueError`` if a duplicate pair references an image id that is
    not part of ``dataset``.
    """

    if quality_gate is not None:
        quality_gate.require("split")

    duplicate_pairs = list(duplicate_pairs or [])
    image_ids = [image.id for image in dataset.images]
    known_image_ids = set(image_ids)
    for image_a, image_b in duplicate_pairs:
        if image_a not in known_image_ids or image_b not in known_image_ids:
            raise ValueError(
                f"duplicate pair ({image_a}, {image_b}) references an unknown image_id"
            )

    image_categories = _image_categories(dataset)
    name_by_category_id = {category.id: category.name for category in dataset.categories}
    groups = _build_duplicate_groups(image_ids, duplicate_pairs)

    first_assignment, first_group_split = _assign_with_full_class_coverage(
        groups, config, image_categories, dataset
    )
    second_assignment, _ = _assign_with_full_class_coverage(
        groups, config, image_categories, dataset
    )
    reproducible = _sorted(first_assignment) == _sorted(second_assignment)

    totals = SplitTotals(
        images=len(image_ids),
        train=len(first_assignment["train"]),
        val=len(first_assignment["val"]),
        test=len(first_assignment["test"]),
    )
    class_distribution = SplitClassDistribution(
        **{
            split_name: _class_counts(
                first_assignment[split_name], image_categories, name_by_category_id
            )
            for split_name in _SPLIT_NAMES
        }
    )
    leakage_check = _leakage_check(duplicate_pairs, first_group_split, groups)
    reproducibility_check = SplitReproducibilityCheck(
        status="pass" if reproducible else "fail",
        note=(
            f"Two runs with seed={config.seed} produced identical image_id assignments per split."
            if reproducible
            else f"Two runs with seed={config.seed} produced DIFFERENT image_id "
            "assignments — split generation is not reproducible."
        ),
    )

    report = SplitResult(
        dataset_version=dataset_version,
        generated_at=generated_at or datetime.now(UTC),
        seed=config.seed,
        proportions=SplitProportions(train=config.train, val=config.val, test=config.test),
        tolerance=tolerance,
        totals=totals,
        class_distribution=class_distribution,
        leakage_check=leakage_check,
        reproducibility_check=reproducibility_check,
    )

    return SplitGenerationResult(assignment=_sorted(first_assignment), report=report)


def _image_categories(dataset: CocoDataset) -> dict[int, set[int]]:
    categories: dict[int, set[int]] = defaultdict(set)
    for annotation in dataset.annotations:
        categories[annotation.image_id].add(annotation.category_id)
    return categories


def _build_duplicate_groups(
    image_ids: list[int], duplicate_pairs: list[tuple[int, int]]
) -> dict[int, list[int]]:
    """Union-find over ``duplicate_pairs``. Returns group_id -> sorted member image ids.

    Every image belongs to exactly one group; an image with no duplicate
    pair is its own singleton group.
    """

    parent = {image_id: image_id for image_id in image_ids}

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: int, b: int) -> None:
        root_a, root_b = find(a), find(b)
        if root_a == root_b:
            return
        # Smaller id always wins as root, regardless of pair order, so the
        # resulting grouping is deterministic for a given set of pairs.
        if root_a < root_b:
            parent[root_b] = root_a
        else:
            parent[root_a] = root_b

    for image_a, image_b in duplicate_pairs:
        union(image_a, image_b)

    members: dict[int, list[int]] = defaultdict(list)
    for image_id in image_ids:
        members[find(image_id)].append(image_id)
    return {group_id: sorted(ids) for group_id, ids in members.items()}


def _assign_with_full_class_coverage(
    groups: dict[int, list[int]],
    config: SplitConfig,
    image_categories: dict[int, set[int]],
    dataset: CocoDataset,
) -> tuple[dict[str, list[int]], dict[int, str]]:
    assignment, group_split = _assign_groups(groups, config, image_categories, dataset)
    _fill_class_coverage_gaps(groups, group_split, assignment, image_categories, dataset)
    return assignment, group_split


def _assign_groups(
    groups: dict[int, list[int]],
    config: SplitConfig,
    image_categories: dict[int, set[int]],
    dataset: CocoDataset,
) -> tuple[dict[str, list[int]], dict[int, str]]:
    """Deficit-balanced (Bresenham-style) group assignment, stratified by class.

    Groups are visited in a seeded-shuffle order, but that order is then
    re-sorted so the groups carrying the rarest classes go first — while
    every split still has the most room relative to its target, which is
    when a scarce class's placement matters most. Each group is scored by
    the remaining deficit, per split, of its *scarcest* carried class (target
    count for that class in that split minus what's already there), with the
    group's overall size deficit as a tie-breaker; it goes to whichever split
    scores highest. This keeps each class's own train/val/test proportions
    close to the configured ratios, not just the overall image count.

    (Previously this only used the overall size deficit, so a minority class
    could land lopsided across splits even when the totals looked fine — see
    the "Mau's review" tests in tests/test_splits.py.)

    Fully determined by the seed: the shuffle picks the tie-break order, and
    everything downstream of it is a deterministic sort/max, so the same seed
    always produces the same assignment.
    """

    target_ratio = {"train": config.train, "val": config.val, "test": config.test}
    total_images = sum(len(members) for members in groups.values())
    target_count = {name: ratio * total_images for name, ratio in target_ratio.items()}

    group_categories: dict[int, Counter[int]] = {
        group_id: Counter(
            category_id
            for image_id in members
            for category_id in image_categories.get(image_id, ())
        )
        for group_id, members in groups.items()
    }
    total_by_category: Counter[int] = Counter()
    for counts in group_categories.values():
        total_by_category.update(counts)
    target_class_count = {
        name: {category_id: ratio * total for category_id, total in total_by_category.items()}
        for name, ratio in target_ratio.items()
    }

    ordered_group_ids = sorted(groups)
    random.Random(config.seed).shuffle(ordered_group_ids)
    shuffle_position = {group_id: index for index, group_id in enumerate(ordered_group_ids)}

    def rarity_key(group_id: int) -> tuple[float, int]:
        categories = group_categories[group_id]
        if not categories:
            return (float("inf"), shuffle_position[group_id])
        rarest = min(total_by_category[category_id] for category_id in categories)
        return (rarest, shuffle_position[group_id])

    # Rarest-class-first: the few groups carrying a scarce class are the ones
    # most at risk of landing lopsided if placed last, so they get first pick
    # of each split's remaining capacity.
    visiting_order = sorted(ordered_group_ids, key=rarity_key)

    counts = dict.fromkeys(_SPLIT_NAMES, 0)
    class_counts: dict[str, Counter[int]] = {name: Counter() for name in _SPLIT_NAMES}
    assignment: dict[str, list[int]] = {name: [] for name in _SPLIT_NAMES}
    group_split: dict[int, str] = {}

    for group_id in visiting_order:
        members = groups[group_id]
        categories = group_categories[group_id]
        driving_category = (
            min(categories, key=lambda category_id: total_by_category[category_id])
            if categories
            else None
        )

        def score(
            name: str, driving_category: int | None = driving_category
        ) -> tuple[float, float]:
            total_deficit = target_count[name] - counts[name]
            if driving_category is None:
                return (total_deficit, total_deficit)
            class_deficit = (
                target_class_count[name][driving_category] - class_counts[name][driving_category]
            )
            return (class_deficit, total_deficit)

        chosen = max(_SPLIT_NAMES, key=score)
        group_split[group_id] = chosen
        counts[chosen] += len(members)
        for category_id, occurrences in categories.items():
            class_counts[chosen][category_id] += occurrences
        assignment[chosen].extend(members)

    return assignment, group_split


def _fill_class_coverage_gaps(
    groups: dict[int, list[int]],
    group_split: dict[int, str],
    assignment: dict[str, list[int]],
    image_categories: dict[int, set[int]],
    dataset: CocoDataset,
) -> None:
    """Guarantee every category in ``dataset`` appears in both val and test,
    without ever un-covering a class a split already has.

    A group is only moved out of val or test — to satisfy the *other* one's
    coverage — when that's *safe*: every category the group carries must
    still be covered by some other group left behind in its current split.
    Moving a group out of train is always allowed, since only val/test carry
    a coverage guarantee.

    This is the fix for the review finding that the previous version could
    move a group (in particular a multilabel one, carrying more than one
    category) from val to test, or vice versa, to satisfy one missing class,
    silently dropping a *different* class that split already had covered —
    see the "Mau's review" tests in tests/test_splits.py. When a category
    only has one eligible group in the whole dataset and val and test both
    need it, only one of them can have it (a group can't be split across
    splits) — that's a genuine data-scarcity limit, not a bug, and this
    function leaves the already-covered split alone rather than shuffling
    the gap around.

    Runs to a fixed point (bounded by category count) instead of a single
    val-then-test pass, so a fill made while completing one split's coverage
    is re-checked against the other, not just assumed to stick.
    """

    group_category_ids = {
        group_id: {
            category_id
            for image_id in members
            for category_id in image_categories.get(image_id, ())
        }
        for group_id, members in groups.items()
    }
    ordered_group_ids = sorted(groups)
    all_category_ids = [category.id for category in dataset.categories]

    def present(split_name: str) -> set[int]:
        return {
            category_id
            for image_id in assignment[split_name]
            for category_id in image_categories.get(image_id, ())
        }

    def other_groups_cover(category_id: int, split_name: str, excluding: int) -> bool:
        return any(
            category_id in group_category_ids[group_id]
            for group_id in ordered_group_ids
            if group_id != excluding and group_split[group_id] == split_name
        )

    def is_safe_donor(group_id: int, source_split: str) -> bool:
        if source_split == "train":
            return True
        return all(
            other_groups_cover(category_id, source_split, excluding=group_id)
            for category_id in group_category_ids[group_id]
        )

    def find_donor(category_id: int, required_split: str) -> int | None:
        other_required = "test" if required_split == "val" else "val"
        # Prefer donating from train (the largest, least disruptive pool, and
        # the only one always safe to take from) before borrowing from the
        # other split that also needs full class coverage.
        for source in ("train", other_required):
            candidates = [
                group_id
                for group_id in ordered_group_ids
                if group_split[group_id] == source
                and category_id in group_category_ids[group_id]
                and is_safe_donor(group_id, source)
            ]
            if candidates:
                candidates.sort(key=lambda group_id: (len(groups[group_id]), group_id))
                return candidates[0]
        return None

    changed = True
    max_passes = 2 * len(all_category_ids) + 4  # generous, deterministic bound
    passes = 0
    while changed and passes < max_passes:
        changed = False
        passes += 1
        for required_split in ("val", "test"):
            missing = [
                category_id
                for category_id in all_category_ids
                if category_id not in present(required_split)
            ]
            for category_id in missing:
                donor = find_donor(category_id, required_split)
                if donor is None:
                    # No donor can cover this category here without un-covering
                    # it from a split that already relies on it — nothing left
                    # to safely move.
                    continue
                _move_group(donor, required_split, groups, group_split, assignment)
                changed = True


def _move_group(
    group_id: int,
    target_split: str,
    groups: dict[int, list[int]],
    group_split: dict[int, str],
    assignment: dict[str, list[int]],
) -> None:
    source = group_split[group_id]
    if source == target_split:
        return
    members = set(groups[group_id])
    assignment[source] = [image_id for image_id in assignment[source] if image_id not in members]
    assignment[target_split].extend(groups[group_id])
    group_split[group_id] = target_split


def _class_counts(
    image_ids: list[int],
    image_categories: dict[int, set[int]],
    name_by_category_id: dict[int, str],
) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for image_id in image_ids:
        for category_id in image_categories.get(image_id, ()):
            counter[name_by_category_id[category_id]] += 1
    return dict(counter)


def _leakage_check(
    duplicate_pairs: list[tuple[int, int]],
    group_split: dict[int, str],
    groups: dict[int, list[int]],
) -> SplitLeakageCheck:
    image_to_group = {
        image_id: group_id for group_id, members in groups.items() for image_id in members
    }
    same_split = sum(
        1
        for image_a, image_b in duplicate_pairs
        if group_split[image_to_group[image_a]] == group_split[image_to_group[image_b]]
    )
    checked = len(duplicate_pairs)
    leaked = checked - same_split
    return SplitLeakageCheck(
        status="pass" if leaked == 0 else "fail",
        leaked_pairs=leaked,
        near_duplicate_pairs_checked=checked,
        near_duplicate_pairs_same_split=same_split,
    )


def _sorted(assignment: dict[str, list[int]]) -> dict[str, list[int]]:
    return {name: sorted(ids) for name, ids in assignment.items()}
