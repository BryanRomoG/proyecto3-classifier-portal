"""T3-1.2: the leak-free 70/20/10 classifier split manifest.

Locks down the new manifest's contract: the 70/20/10 proportions are configured without
touching the inherited 70/15/15 `split` stage; generation reuses the inherited
`generate_splits` (so duplicate pairs and their transitive chains always stay together and
no group can cross a split); every source image and every crop appears exactly once; the
artifact is deterministic (same seed -> identical ids and identical JSON bytes) and carries
SHA-256 provenance with no timestamps or absolute paths; and inconsistent provenance, a crop
pointing at an unknown image, a repeated crop identity or an unknown duplicate pair all fail
loudly instead of producing a manifest nobody can trust.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml

from dataset_quality.classifier_splits import (
    ClassifierSplitError,
    ClassifierSplitManifest,
    generate_classifier_split,
)
from dataset_quality.classifier_splits.__main__ import main as classifier_split_main
from dataset_quality.config.models import SplitConfig
from dataset_quality.crops.models import CropManifest

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
DATASET_VERSION = "v1.0.0"
PROPORTIONS = SplitConfig(train=0.70, val=0.20, test=0.10, seed=42)
SPLIT_NAMES = ("train", "val", "test")
IMAGE_IDS = list(range(1, 61))
CROP_IMAGE_IDS = list(range(1, 41))


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _category_id(image_id: int) -> int:
    """Deterministic but mixed label so both classes reach every split."""

    return 1 if image_id % 2 == 0 else 2


def _category_name(image_id: int) -> str:
    return "person" if _category_id(image_id) == 1 else "car"


def _image(image_id: int) -> dict[str, Any]:
    return {
        "id": image_id,
        "file_name": f"images/img_{image_id:05d}.jpg",
        "width": 640,
        "height": 480,
    }


def _raw_coco(image_ids: Sequence[int]) -> dict[str, Any]:
    return {
        "images": [_image(image_id) for image_id in image_ids],
        "categories": [{"id": 1, "name": "person"}, {"id": 2, "name": "car"}],
        "annotations": [
            {
                "id": image_id,
                "image_id": image_id,
                "category_id": _category_id(image_id),
                "bbox": [10.0, 10.0, 20.0, 20.0],
            }
            for image_id in image_ids
        ],
    }


def _crop_record(annotation_id: int, source_image_id: int) -> dict[str, Any]:
    category_name = _category_name(source_image_id)
    return {
        "annotation_id": annotation_id,
        "source_image_id": source_image_id,
        "source_file_name": f"images/img_{source_image_id:05d}.jpg",
        "category_id": _category_id(source_image_id),
        "category_name": category_name,
        "bbox": [10.0, 10.0, 20.0, 20.0],
        "x_min": 10,
        "y_min": 10,
        "x_max": 30,
        "y_max": 30,
        "crop_width": 20,
        "crop_height": 20,
        "source_image_width": 640,
        "source_image_height": 480,
        "observed_image_width": 640,
        "observed_image_height": 480,
        "relative_path": f"data/processed/crops/{category_name}/{annotation_id}.png",
        "png_sha256": "0" * 64,
    }


def _crops_for(image_ids: Sequence[int]) -> list[dict[str, Any]]:
    return [_crop_record(image_id, image_id) for image_id in image_ids]


def _crop_summary(crops: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_category: Counter[str] = Counter(crop["category_name"] for crop in crops)
    return {
        "total_annotations": len(crops),
        "target_annotations": len(crops),
        "ignored_non_target": 0,
        "crops": len(crops),
        "excluded": 0,
        "excluded_target_boxes": 0,
        "unresolvable_annotations": 0,
        "images_with_crops": len({crop["source_image_id"] for crop in crops}),
        "images_with_dimension_mismatch": 0,
        "crops_by_category": dict(sorted(by_category.items())),
        "exclusions_by_reason": {},
    }


def _write_inputs(
    tmp_path: Path,
    *,
    image_ids: Sequence[int],
    crops: Sequence[dict[str, Any]],
    pairs: Sequence[tuple[int, int]] = (),
    manifest_dataset_version: str | None = None,
    manifest_coco_sha256: str | None = None,
) -> dict[str, Path]:
    """Write a canonical COCO, its crops manifest and duplicate pairs; return their paths."""

    coco_path = tmp_path / "coco.json"
    coco_path.write_text(json.dumps(_raw_coco(image_ids), indent=2), encoding="utf-8")
    coco_sha256 = hashlib.sha256(coco_path.read_bytes()).hexdigest()

    crops_manifest = CropManifest.model_validate(
        {
            "dataset_version": manifest_dataset_version or DATASET_VERSION,
            "coco_file_name": coco_path.name,
            "coco_sha256": manifest_coco_sha256 or coco_sha256,
            "target_categories": ["person", "car"],
            "summary": _crop_summary(crops),
            "dimension_mismatches": [],
            "crops": list(crops),
        }
    )
    crops_path = tmp_path / "crops_manifest.json"
    crops_path.write_text(
        json.dumps(crops_manifest.model_dump(mode="json"), indent=2), encoding="utf-8"
    )

    pairs_path = tmp_path / "duplicate_pairs.json"
    pairs_path.write_text(json.dumps([list(pair) for pair in pairs]), encoding="utf-8")

    return {"coco": coco_path, "crops": crops_path, "pairs": pairs_path}


def _generate(
    paths: dict[str, Path],
    *,
    config: SplitConfig = PROPORTIONS,
    dataset_version: str = DATASET_VERSION,
) -> ClassifierSplitManifest:
    return generate_classifier_split(
        coco_path=paths["coco"],
        crops_manifest_path=paths["crops"],
        duplicate_pairs_path=paths["pairs"],
        dataset_version=dataset_version,
        config=config,
    ).manifest


# ---------------------------------------------------------------------------
# Configuration and DVC wiring
# ---------------------------------------------------------------------------


def test_classifier_split_is_seventy_twenty_ten_and_split_stays_inherited() -> None:
    params = yaml.safe_load((PIPELINE_ROOT / "params.yaml").read_text(encoding="utf-8"))

    assert params["classifier_split"] == {"train": 0.70, "val": 0.20, "test": 0.10, "seed": 42}
    assert (params["split"]["train"], params["split"]["val"], params["split"]["test"]) == (
        0.70,
        0.15,
        0.15,
    )

    stages = yaml.safe_load((PIPELINE_ROOT / "dvc.yaml").read_text(encoding="utf-8"))["stages"]

    assert "classifier_split" in stages, "T3-1.2 must add a `classifier_split` stage"
    stage = stages["classifier_split"]
    assert stage["outs"] == ["data/processed/classifier_split_manifest.json"]
    assert stage["params"] == [
        "dataset_version",
        "classifier_split.train",
        "classifier_split.val",
        "classifier_split.test",
        "classifier_split.seed",
    ]
    assert {
        "data/interim/coco.json",
        "data/processed/crops_manifest.json",
        "data/interim/duplicate_pairs.json",
    } <= set(stage["deps"])
    assert "dataset_quality.classifier_splits" in stage["cmd"]
    for placeholder in (
        "${classifier_split.train}",
        "${classifier_split.val}",
        "${classifier_split.test}",
        "${classifier_split.seed}",
    ):
        assert placeholder in stage["cmd"]

    split = stages["split"]
    assert set(split["outs"]) == {
        "data/interim/splits.json",
        "data/interim/split_assignment.json",
    }
    assert split["params"] == [
        "dataset_version",
        "split.train",
        "split.val",
        "split.test",
        "split.seed",
    ]


# ---------------------------------------------------------------------------
# Coverage and grouping
# ---------------------------------------------------------------------------


def test_every_source_image_and_crop_appears_exactly_once(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, image_ids=IMAGE_IDS, crops=_crops_for(CROP_IMAGE_IDS))

    manifest = _generate(paths)

    assert [section.name for section in manifest.splits] == list(SPLIT_NAMES)

    image_ids = [image_id for section in manifest.splits for image_id in section.image_ids]
    assert sorted(image_ids) == IMAGE_IDS
    assert len(image_ids) == len(set(image_ids))
    assert manifest.totals.images == len(IMAGE_IDS)

    crop_ids = [crop.annotation_id for section in manifest.splits for crop in section.crops]
    assert sorted(crop_ids) == CROP_IMAGE_IDS
    assert len(crop_ids) == len(set(crop_ids))
    assert manifest.totals.crops == len(CROP_IMAGE_IDS)

    image_sets = [set(section.image_ids) for section in manifest.splits]
    assert not image_sets[0] & image_sets[1]
    assert not image_sets[0] & image_sets[2]
    assert not image_sets[1] & image_sets[2]

    for section in manifest.splits:
        assert section.image_count == len(section.image_ids)
        assert section.crop_count == len(section.crops)
        assert sum(section.crops_by_category.values()) == section.crop_count
        assert set(section.crops_by_category) == set(section.images_by_category)
        assert {crop.source_image_id for crop in section.crops} <= set(section.image_ids)


def test_duplicate_pair_and_transitive_chain_stay_in_one_split(tmp_path: Path) -> None:
    paths = _write_inputs(
        tmp_path,
        image_ids=IMAGE_IDS,
        crops=_crops_for(CROP_IMAGE_IDS),
        pairs=[(3, 4), (4, 5), (10, 11)],
    )

    manifest = _generate(paths)

    split_of_image = {
        image_id: section.name for section in manifest.splits for image_id in section.image_ids
    }
    assert split_of_image[3] == split_of_image[4] == split_of_image[5]
    assert split_of_image[10] == split_of_image[11]

    assert manifest.leakage_check.status == "pass"
    assert manifest.leakage_check.duplicate_pairs_checked == 3
    assert manifest.leakage_check.duplicate_pairs_same_split == 3
    assert manifest.leakage_check.leaked_pairs == 0


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_same_seed_produces_identical_ids_and_json_bytes(tmp_path: Path) -> None:
    paths = _write_inputs(
        tmp_path, image_ids=IMAGE_IDS, crops=_crops_for(CROP_IMAGE_IDS), pairs=[(3, 4)]
    )

    first = _generate(paths)
    second = _generate(paths)

    assert first == second
    assert first.model_dump_json(indent=2) == second.model_dump_json(indent=2)

    payload = json.loads(first.model_dump_json(indent=2))
    assert payload["seed"] == 42
    assert payload["proportions"] == {"train": 0.70, "val": 0.20, "test": 0.10}
    assert "generated_at" not in payload
    assert str(tmp_path) not in first.model_dump_json(indent=2)


def test_changing_the_seed_keeps_the_partition_valid(tmp_path: Path) -> None:
    paths = _write_inputs(
        tmp_path,
        image_ids=IMAGE_IDS,
        crops=_crops_for(CROP_IMAGE_IDS),
        pairs=[(3, 4), (4, 5)],
    )

    base = _generate(paths, config=PROPORTIONS)
    other = _generate(paths, config=SplitConfig(train=0.70, val=0.20, test=0.10, seed=7))

    for manifest in (base, other):
        image_ids = sorted(
            image_id for section in manifest.splits for image_id in section.image_ids
        )
        assert image_ids == IMAGE_IDS
        assert manifest.leakage_check.leaked_pairs == 0
        assert manifest.totals.images == len(IMAGE_IDS)

    assert other.seed == 7

    def assignment(manifest: ClassifierSplitManifest) -> dict[int, str]:
        return {
            image_id: section.name for section in manifest.splits for image_id in section.image_ids
        }

    assert assignment(base) != assignment(other)


# ---------------------------------------------------------------------------
# Failing loudly on inputs that do not describe each other
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("manifest_dataset_version", "manifest_coco_sha256", "match"),
    [
        ("v9.9.9", None, "dataset_version"),
        (None, "f" * 64, "coco_sha256"),
    ],
)
def test_inconsistent_crops_manifest_provenance_fails(
    tmp_path: Path,
    manifest_dataset_version: str | None,
    manifest_coco_sha256: str | None,
    match: str,
) -> None:
    paths = _write_inputs(
        tmp_path,
        image_ids=IMAGE_IDS,
        crops=_crops_for(CROP_IMAGE_IDS),
        manifest_dataset_version=manifest_dataset_version,
        manifest_coco_sha256=manifest_coco_sha256,
    )

    with pytest.raises(ClassifierSplitError, match=match):
        _generate(paths)


def test_crop_referencing_an_unknown_coco_image_fails(tmp_path: Path) -> None:
    crops = _crops_for(CROP_IMAGE_IDS) + [_crop_record(999, 999)]
    paths = _write_inputs(tmp_path, image_ids=IMAGE_IDS, crops=crops)

    with pytest.raises(ClassifierSplitError, match="999"):
        _generate(paths)


@pytest.mark.parametrize("duplicate_field", ["annotation_id", "relative_path"])
def test_duplicated_crop_identity_fails(tmp_path: Path, duplicate_field: str) -> None:
    crops = _crops_for([1, 2])
    if duplicate_field == "annotation_id":
        crops[1]["annotation_id"] = crops[0]["annotation_id"]
    else:
        crops[1]["relative_path"] = crops[0]["relative_path"]

    paths = _write_inputs(tmp_path, image_ids=IMAGE_IDS, crops=crops)

    with pytest.raises(ClassifierSplitError, match=duplicate_field):
        _generate(paths)


def test_unknown_duplicate_pair_fails_through_the_inherited_generator(tmp_path: Path) -> None:
    paths = _write_inputs(
        tmp_path,
        image_ids=IMAGE_IDS,
        crops=_crops_for(CROP_IMAGE_IDS),
        pairs=[(1, 999)],
    )

    with pytest.raises(ValueError, match="unknown image_id"):
        _generate(paths)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_writes_the_expected_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _write_inputs(
        tmp_path,
        image_ids=IMAGE_IDS,
        crops=_crops_for(CROP_IMAGE_IDS),
        pairs=[(3, 4)],
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dataset_quality.classifier_splits",
            paths["coco"].name,
            "--crops-manifest",
            paths["crops"].name,
            "--duplicate-pairs",
            paths["pairs"].name,
            "--dataset-version",
            DATASET_VERSION,
            "--train",
            "0.70",
            "--val",
            "0.20",
            "--test",
            "0.10",
            "--seed",
            "42",
            "--output",
            "nested/classifier_split_manifest.json",
        ],
    )

    classifier_split_main()

    output = tmp_path / "nested" / "classifier_split_manifest.json"
    assert output.is_file()
    # The manifest is identified by its SHA-256: its bytes must not depend on the OS.
    assert b"\r\n" not in output.read_bytes(), "manifest written with CRLF line endings"

    text = output.read_text(encoding="utf-8")
    manifest = ClassifierSplitManifest.model_validate_json(text)
    assert (manifest.proportions.train, manifest.proportions.val, manifest.proportions.test) == (
        0.70,
        0.20,
        0.10,
    )
    assert manifest.totals.images == len(IMAGE_IDS)
    assert manifest.totals.crops == len(CROP_IMAGE_IDS)
    assert manifest.leakage_check.leaked_pairs == 0
    assert str(tmp_path) not in text

    assert json.loads(capsys.readouterr().out)["dataset_version"] == DATASET_VERSION
