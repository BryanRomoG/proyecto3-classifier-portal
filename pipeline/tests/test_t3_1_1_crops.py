"""T3-1.1: traceable COCO crop generation (``dataset_quality.crops``).

Locks down the crop stage's contract: valid boxes become deterministic PNG crops
with full traceability (dataset version, COCO hash, image/annotation/category/bbox),
invalid boxes become stable exclusion records instead of aborting the run,
non-target categories are ignored rather than reported as invalid, declared-vs-observed
image dimensions are reconciled explicitly, and unresolvable sources (missing DB row,
missing object, undecodable bytes) fail loudly instead of silently producing a partial
dataset: because the three outputs are published only once the whole run has succeeded,
a failed run leaves the previously published artifacts exactly as they were.

MariaDB and the object store are always exercised through in-memory doubles here: this
suite needs no Docker, no MinIO and no network.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml
from PIL import Image

from dataset_quality.crops import (
    BackendImageStore,
    CropCocoStructureError,
    CropConfigurationError,
    CropRunResult,
    CropSourceDecodeError,
    CropSourceUnavailableError,
    generate_crops,
    integer_crop_bounds,
    plan_crops,
)
from dataset_quality.crops.__main__ import main as crops_main

PIPELINE_ROOT = Path(__file__).resolve().parents[1]

# Paths as the DVC `crop` stage passes them (relative to pipeline/), so the tests
# exercise the same relative-path shape the manifest ends up carrying.
COCO_PATH = Path("data/interim/coco.json")
QUALITY_PATH = Path("data/interim/quality.json")
CROPS_ROOT = Path("data/processed/crops")
MANIFEST_PATH = Path("data/processed/crops_manifest.json")
EXCLUSIONS_PATH = Path("data/processed/crop_exclusions.json")

TARGET_CATEGORIES = ("person", "car")

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _gradient_image(width: int, height: int) -> Image.Image:
    """A source image whose every pixel is position-dependent.

    Cropping the wrong region, or cropping through the declared COCO grid instead
    of the observed pixel grid, changes the pixels — so a pixel-for-pixel
    comparison against ``Image.crop`` of the same source is a real check.
    """

    image = Image.new("RGB", (width, height))
    pixels = image.load()
    assert pixels is not None
    for y in range(height):
        for x in range(width):
            pixels[x, y] = ((x * 7) % 256, (y * 11) % 256, (x + y) % 256)
    return image


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _image(image_id: int, width: int, height: int) -> dict[str, Any]:
    return {
        "id": image_id,
        "file_name": f"photos/img_{image_id:05d}.png",
        "width": width,
        "height": height,
    }


def _annotation(annotation_id: Any, image_id: Any, category_id: Any, bbox: Any) -> dict[str, Any]:
    return {"id": annotation_id, "image_id": image_id, "category_id": category_id, "bbox": bbox}


def _raw_coco(
    *,
    images: list[Any],
    categories: list[Any],
    annotations: list[Any],
) -> dict[str, Any]:
    return {"images": images, "categories": categories, "annotations": annotations}


def _write_coco(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_quality_report(path: Path, overall_status: str = "pass") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "dataset_version": "v1.0.0",
                "generated_at": "2026-09-29T00:00:00Z",
                "overall_status": overall_status,
                "checks": [],
            }
        ),
        encoding="utf-8",
    )
    return path


class FakeSourceImageStore:
    """In-memory stand-in for MariaDB + object storage.

    Mirrors the real ``SourceImageStore`` contract (one ``storage_keys`` query per
    run, one ``read_bytes`` per image) and records every call, so tests can assert
    that each source image is downloaded exactly once.
    """

    def __init__(self, images_by_id: dict[int, bytes], *, missing_keys: bool = False) -> None:
        self.keys_by_image = {image_id: f"images/{image_id}.png" for image_id in images_by_id}
        self.objects_by_key = {
            self.keys_by_image[image_id]: data for image_id, data in images_by_id.items()
        }
        self.missing_keys = missing_keys
        self.key_queries: list[list[int]] = []
        self.byte_reads: list[str] = []

    def storage_keys(self, image_ids: Sequence[int]) -> dict[int, str]:
        requested = sorted(image_ids)
        self.key_queries.append(requested)
        if self.missing_keys:
            return {}
        return {
            image_id: self.keys_by_image[image_id]
            for image_id in requested
            if image_id in self.keys_by_image
        }

    def read_bytes(self, storage_key: str) -> bytes:
        self.byte_reads.append(storage_key)
        return self.objects_by_key[storage_key]


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def fetchall(self) -> list[Any]:
        return list(self._rows)


class _FakeConnection:
    def __init__(self, engine: _FakeEngine) -> None:
        self._engine = engine

    def execute(self, statement: Any, parameters: Any) -> _FakeResult:
        self._engine.statements.append((str(statement), dict(parameters)))
        return _FakeResult(self._engine.rows)

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False


class _FakeEngine:
    """Enough of SQLAlchemy's ``Engine`` surface for ``BackendImageStore``."""

    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.statements: list[tuple[str, dict[str, Any]]] = []

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self)


class _FakeObjectStore:
    def __init__(self, objects: dict[str, bytes], *, failing: tuple[str, ...] = ()) -> None:
        self.objects = objects
        self.failing = set(failing)

    def get_bytes(self, key: str) -> bytes:
        if key in self.failing:
            raise RuntimeError(f"object store is down for {key}")
        return self.objects[key]


def _generate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw: dict[str, Any],
    *,
    images: dict[int, Image.Image] | None = None,
    target_categories: Sequence[str] = TARGET_CATEGORIES,
    dataset_version: str = "v1.0.0",
    store: FakeSourceImageStore | None = None,
) -> tuple[CropRunResult, FakeSourceImageStore]:
    """Write the COCO input and run the real ``generate_crops`` from ``tmp_path``."""

    monkeypatch.chdir(tmp_path)
    _write_coco(COCO_PATH, raw)
    fake_store = store or FakeSourceImageStore(
        {image_id: _png_bytes(image) for image_id, image in (images or {}).items()}
    )
    result = generate_crops(
        coco_path=COCO_PATH,
        crops_root=CROPS_ROOT,
        manifest_path=MANIFEST_PATH,
        exclusions_path=EXCLUSIONS_PATH,
        dataset_version=dataset_version,
        target_categories=list(target_categories),
        source_store=fake_store,
    )
    return result, fake_store


def _cli_argv(
    *, categories: Sequence[str] = TARGET_CATEGORIES, version: str = "v1.0.0"
) -> list[str]:
    argv = [
        "crops",
        str(COCO_PATH),
        "--quality-report",
        str(QUALITY_PATH),
        "--dataset-version",
        version,
        "--crops-root",
        str(CROPS_ROOT),
        "--manifest-output",
        str(MANIFEST_PATH),
        "--exclusions-output",
        str(EXCLUSIONS_PATH),
    ]
    for category in categories:
        argv += ["--category", category]
    return argv


# ---------------------------------------------------------------------------
# Pixel bounds (pure geometry)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bbox", "expected"),
    [
        ((3.4, 5.2, 10.3, 7.9), (3, 5, 14, 14)),
        ((0, 0, 1, 1), (0, 0, 1, 1)),
        ((5.0, 5.0, 0.4, 0.4), (5, 5, 6, 6)),
        ((1.5, 2.5, 2.5, 3.5), (1, 2, 4, 6)),
    ],
)
def test_integer_crop_bounds_floors_origin_and_ceils_far_corner(
    bbox: tuple[float, float, float, float], expected: tuple[int, int, int, int]
) -> None:
    bounds = integer_crop_bounds(bbox)

    assert (bounds.x_min, bounds.y_min, bounds.x_max, bounds.y_max) == expected
    assert (bounds.width, bounds.height) == (expected[2] - expected[0], expected[3] - expected[1])


# ---------------------------------------------------------------------------
# Valid crop: pixels, dimensions, traceability
# ---------------------------------------------------------------------------


def test_valid_box_produces_crop_with_expected_pixels_bounds_and_traceability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _raw_coco(
        images=[_image(7, 40, 30)],
        categories=[{"id": 1, "name": "person"}, {"id": 2, "name": "car"}],
        annotations=[_annotation(11, 7, 2, [3.4, 5.2, 10.3, 7.9])],
    )
    source = _gradient_image(40, 30)

    result, store = _generate(monkeypatch, tmp_path, raw, images={7: source})

    # Traceability back to release, dataset file, image, annotation, category, box.
    manifest = result.manifest
    assert manifest.dataset_version == "v1.0.0"
    assert manifest.coco_file_name == "coco.json"
    assert manifest.coco_sha256 == hashlib.sha256(COCO_PATH.read_bytes()).hexdigest()
    assert manifest.target_categories == ["person", "car"]

    assert len(manifest.crops) == 1
    record = manifest.crops[0]
    assert record.annotation_id == 11
    assert record.source_image_id == 7
    assert record.source_file_name == "photos/img_00007.png"
    assert (record.category_id, record.category_name) == (2, "car")
    assert tuple(record.bbox) == (3.4, 5.2, 10.3, 7.9)
    assert (record.x_min, record.y_min, record.x_max, record.y_max) == (3, 5, 14, 14)
    assert (record.crop_width, record.crop_height) == (11, 9)
    assert (record.source_image_width, record.source_image_height) == (40, 30)
    assert (record.observed_image_width, record.observed_image_height) == (40, 30)
    assert record.relative_path == "data/processed/crops/car/11.png"

    # The PNG exists at the documented path, holds the rasterized region, and its
    # recorded hash matches the bytes on disk.
    crop_path = Path(record.relative_path)
    assert crop_path.exists()
    with Image.open(crop_path) as crop:
        assert crop.format == "PNG"
        assert crop.mode == "RGB"
        assert crop.size == (11, 9)
        assert crop.tobytes() == source.crop((3, 5, 14, 14)).tobytes()
    assert record.png_sha256 == hashlib.sha256(crop_path.read_bytes()).hexdigest()
    assert [path.as_posix() for path in result.written] == [record.relative_path]

    # Counts per class cover every configured target, present or not.
    assert manifest.summary.crops_by_category == {"person": 0, "car": 1}
    assert manifest.summary.crops == 1
    assert manifest.summary.excluded == 0
    assert manifest.summary.target_annotations == 1
    assert manifest.summary.ignored_non_target == 0
    assert manifest.summary.images_with_crops == 1
    assert manifest.summary.images_with_dimension_mismatch == 0
    assert manifest.dimension_mismatches == []

    # The exclusions artifact is always written, even when nothing was excluded.
    exclusions = json.loads(EXCLUSIONS_PATH.read_text(encoding="utf-8"))
    assert exclusions["exclusions"] == []
    assert exclusions["dataset_version"] == "v1.0.0"
    assert exclusions["coco_sha256"] == manifest.coco_sha256
    assert exclusions["target_categories"] == ["person", "car"]
    assert exclusions["summary"] == result.exclusions.summary.model_dump(mode="json")
    assert store.key_queries == [[7]]


def test_each_source_image_is_downloaded_once_for_all_of_its_crops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _raw_coco(
        images=[_image(7, 40, 30)],
        categories=[{"id": 1, "name": "person"}, {"id": 2, "name": "car"}],
        annotations=[
            _annotation(11, 7, 1, [1, 1, 5, 5]),
            _annotation(12, 7, 1, [10, 10, 5, 5]),
            _annotation(13, 7, 2, [20, 20, 5, 5]),
        ],
    )

    result, store = _generate(monkeypatch, tmp_path, raw, images={7: _gradient_image(40, 30)})

    assert [record.annotation_id for record in result.manifest.crops] == [11, 12, 13]
    assert store.key_queries == [[7]]
    assert store.byte_reads == ["images/7.png"]


# ---------------------------------------------------------------------------
# Invalid geometry: registered as exclusions, never fatal
# ---------------------------------------------------------------------------


def _assert_same_raw_bbox(actual: Any, expected: Any) -> None:
    """Compare raw JSON values, including NaN (list equality would not)."""

    assert json.dumps(actual, allow_nan=True) == json.dumps(expected, allow_nan=True)


@pytest.mark.parametrize(
    ("bbox", "expected_reasons"),
    [
        ([1, 2, 3], ["malformed_bbox"]),
        ("not-a-box", ["malformed_bbox"]),
        (None, ["malformed_bbox"]),
        ([1, 2, 3, "wide"], ["non_numeric_bbox"]),
        ([1, True, 3, 4], ["non_numeric_bbox"]),
        ([1, 2, 3, float("nan")], ["non_finite_bbox"]),
        ([float("inf"), 2, 3, 4], ["non_finite_bbox"]),
        ([0, 0, 0, 5], ["nonpositive_width"]),
        ([0, 0, 5, 0], ["nonpositive_height"]),
        ([0, 0, -3, 5], ["nonpositive_width"]),
        ([-4, 2, 5, 5], ["negative_origin"]),
        ([2, -4, 5, 5], ["negative_origin"]),
        ([40, 2, 5, 5], ["origin_outside_image", "exceeds_image_bounds"]),
        ([2, 30, 5, 5], ["origin_outside_image", "exceeds_image_bounds"]),
        ([35, 2, 10, 5], ["exceeds_image_bounds"]),
        ([2, 25, 5, 10], ["exceeds_image_bounds"]),
        ([-2, 2, -3, 5], ["nonpositive_width", "negative_origin"]),
    ],
)
def test_invalid_boxes_are_excluded_with_stable_reasons(
    bbox: Any, expected_reasons: list[str]
) -> None:
    raw = _raw_coco(
        images=[_image(7, 40, 30)],
        categories=[{"id": 1, "name": "person"}, {"id": 2, "name": "car"}],
        annotations=[_annotation(11, 7, 1, bbox)],
    )

    plan = plan_crops(raw, TARGET_CATEGORIES)

    assert plan.eligible == []
    assert len(plan.exclusions) == 1
    exclusion = plan.exclusions[0]
    assert exclusion.reasons == expected_reasons
    assert exclusion.annotation_id == 11
    assert exclusion.image_id == 7
    assert exclusion.image_file_name == "photos/img_00007.png"
    assert (exclusion.category_id, exclusion.category_name) == (1, "person")
    _assert_same_raw_bbox(exclusion.bbox, bbox)


def test_annotation_without_a_bbox_field_is_excluded_as_malformed() -> None:
    raw = _raw_coco(
        images=[_image(7, 40, 30)],
        categories=[{"id": 1, "name": "person"}, {"id": 2, "name": "car"}],
        annotations=[{"id": 11, "image_id": 7, "category_id": 1}],
    )

    plan = plan_crops(raw, TARGET_CATEGORIES)

    assert plan.eligible == []
    assert plan.exclusions[0].reasons == ["malformed_bbox"]
    assert plan.exclusions[0].bbox is None


def test_every_invalid_box_is_registered_instead_of_aborting_on_the_first() -> None:
    raw = _raw_coco(
        images=[_image(7, 40, 30), _image(8, 40, 30)],
        categories=[{"id": 1, "name": "person"}, {"id": 2, "name": "car"}],
        annotations=[
            _annotation(11, 7, 1, [0, 0, 0, 5]),
            _annotation(12, 7, 1, [1, 1, 5, 5]),
            _annotation(13, 8, 2, [2, 25, 5, 10]),
        ],
    )

    plan = plan_crops(raw, TARGET_CATEGORIES)

    assert [crop.annotation_id for crop in plan.eligible] == [12]
    assert [exclusion.annotation_id for exclusion in plan.exclusions] == [11, 13]
    assert plan.total_annotations == 3
    assert plan.target_annotations == 3
    assert plan.ignored_non_target == 0


def test_excluded_boxes_reach_the_exclusions_artifact_and_render_no_png(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _raw_coco(
        images=[_image(7, 40, 30)],
        categories=[{"id": 1, "name": "person"}, {"id": 2, "name": "car"}],
        annotations=[
            _annotation(11, 7, 1, [1, 1, 5, 5]),
            _annotation(12, 7, 1, [0, 0, 0, 5]),
            _annotation(13, 7, 2, [35, 2, 10, 5]),
        ],
    )

    result, store = _generate(monkeypatch, tmp_path, raw, images={7: _gradient_image(40, 30)})

    payload = json.loads(EXCLUSIONS_PATH.read_text(encoding="utf-8"))
    assert [entry["annotation_id"] for entry in payload["exclusions"]] == [12, 13]
    assert payload["exclusions"][0]["reasons"] == ["nonpositive_width"]
    assert payload["exclusions"][1]["reasons"] == ["exceeds_image_bounds"]
    assert payload["exclusions"][0]["bbox"] == [0, 0, 0, 5]
    assert payload["exclusions"][0]["image_id"] == 7
    assert payload["exclusions"][0]["image_file_name"] == "photos/img_00007.png"
    assert (payload["exclusions"][0]["category_id"], payload["exclusions"][0]["category_name"]) == (
        1,
        "person",
    )
    assert payload["summary"]["crops"] == 1
    assert payload["summary"]["excluded"] == 2
    assert payload["summary"]["excluded_target_boxes"] == 2
    assert payload["summary"]["unresolvable_annotations"] == 0
    assert payload["summary"]["exclusions_by_reason"] == {
        "nonpositive_width": 1,
        "exceeds_image_bounds": 1,
    }
    assert payload["summary"]["crops_by_category"] == {"person": 1, "car": 0}
    assert sorted(path.name for path in CROPS_ROOT.rglob("*.png")) == ["11.png"]
    exclusions_by_reason = payload["summary"]["exclusions_by_reason"]
    assert result.manifest.summary.exclusions_by_reason == exclusions_by_reason
    assert store.byte_reads == ["images/7.png"]


# ---------------------------------------------------------------------------
# Non-target categories: ignored, never reported as invalid
# ---------------------------------------------------------------------------


def test_non_target_annotations_are_ignored_and_never_reported_as_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _raw_coco(
        images=[_image(7, 40, 30), _image(9, 40, 30)],
        categories=[
            {"id": 1, "name": "person"},
            {"id": 2, "name": "car"},
            {"id": 3, "name": "dog"},
        ],
        annotations=[
            _annotation(11, 7, 1, [1, 1, 5, 5]),
            _annotation(12, 9, 3, [0, 0, 0, 0]),
            _annotation(13, 9, 3, "garbage"),
        ],
    )

    result, store = _generate(monkeypatch, tmp_path, raw, images={7: _gradient_image(40, 30)})

    # Both dog annotations are counted as ignored, not as errors.
    assert result.manifest.summary.ignored_non_target == 2
    assert result.manifest.summary.excluded == 0
    assert result.manifest.summary.excluded_target_boxes == 0
    assert result.manifest.summary.unresolvable_annotations == 0
    assert result.manifest.summary.target_annotations == 1
    assert result.manifest.summary.crops == 1
    assert result.manifest.summary.crops_by_category == {"person": 1, "car": 0}
    assert result.exclusions.exclusions == []
    assert result.manifest.dimension_mismatches == []

    # Image 9 carries no target annotation, so it is never even fetched.
    assert store.key_queries == [[7]]
    assert store.byte_reads == ["images/7.png"]
    assert not (CROPS_ROOT / "dog").exists()

    # Non-target vocabulary never leaks into the manifest as an error record.
    manifest_text = MANIFEST_PATH.read_text(encoding="utf-8")
    assert "dog" not in manifest_text
    assert json.loads(manifest_text)["summary"]["ignored_non_target"] == 2
    exclusions = json.loads(EXCLUSIONS_PATH.read_text(encoding="utf-8"))
    assert exclusions["exclusions"] == []
    assert exclusions["summary"]["ignored_non_target"] == 2


def test_annotations_with_unresolvable_category_or_image_are_excluded_not_crashed() -> None:
    raw = _raw_coco(
        images=[_image(7, 40, 30)],
        categories=[{"id": 1, "name": "person"}, {"id": 2, "name": "car"}],
        annotations=[
            _annotation(11, 7, 99, [1, 1, 5, 5]),
            _annotation(12, 7, "person", [1, 1, 5, 5]),
            _annotation(13, 99, 1, [1, 1, 5, 5]),
            "not-an-annotation",
        ],
    )

    plan = plan_crops(raw, TARGET_CATEGORIES)

    assert plan.eligible == []
    assert [exclusion.annotation_id for exclusion in plan.exclusions] == [11, 12, 13, None]
    assert [exclusion.reasons for exclusion in plan.exclusions] == [
        ["unknown_category"],
        ["unknown_category"],
        ["unknown_image"],
        ["malformed_annotation"],
    ]
    unknown_image = plan.exclusions[2]
    assert unknown_image.image_id == 99
    assert unknown_image.image_file_name is None
    assert (unknown_image.category_id, unknown_image.category_name) == (1, "person")
    assert plan.total_annotations == 4
    assert plan.target_annotations == 1
    assert plan.ignored_non_target == 0


# ---------------------------------------------------------------------------
# Structural and configuration failures: loud, before anything is written
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"images": {}, "categories": []},
        {
            "images": [_image(7, 40, 30)],
            "categories": {"1": "person"},
            "annotations": [],
        },
        {
            "images": [_image(7, 40, 30)],
            "categories": [],
            "annotations": "not-a-list",
        },
        {"images": ["not-an-image"], "categories": [], "annotations": []},
        {
            "images": [{"id": 7, "file_name": "x.png", "height": 30}],
            "categories": [],
            "annotations": [],
        },
        {
            "images": [{"id": 7, "file_name": "x.png", "width": 0, "height": 30}],
            "categories": [],
            "annotations": [],
        },
        {
            "images": [{"file_name": "x.png", "width": 40, "height": 30}],
            "categories": [],
            "annotations": [],
        },
    ],
)
def test_malformed_coco_structure_aborts_instead_of_recording_exclusions(
    raw: dict[str, Any],
) -> None:
    with pytest.raises(CropCocoStructureError):
        plan_crops(raw, TARGET_CATEGORIES)


@pytest.mark.parametrize(
    ("target_categories", "categories"),
    [
        (("truck",), [{"id": 1, "name": "person"}]),
        ((), [{"id": 1, "name": "person"}]),
        (("person", "person"), [{"id": 1, "name": "person"}]),
        (("a/b",), [{"id": 1, "name": "a/b"}]),
        (("..",), [{"id": 1, "name": ".."}]),
        (("person",), [{"name": "person"}]),
    ],
)
def test_target_category_configuration_is_validated_before_any_fetch(
    target_categories: tuple[str, ...], categories: list[Any]
) -> None:
    raw = _raw_coco(images=[_image(7, 40, 30)], categories=categories, annotations=[])

    with pytest.raises(CropConfigurationError):
        plan_crops(raw, target_categories)


# ---------------------------------------------------------------------------
# Declared vs observed image dimensions
# ---------------------------------------------------------------------------


def test_declared_and_observed_dimensions_are_reconciled_explicitly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _raw_coco(
        images=[_image(7, 40, 30), _image(8, 40, 30), _image(9, 20, 15)],
        categories=[{"id": 1, "name": "person"}, {"id": 2, "name": "car"}],
        annotations=[
            _annotation(1, 7, 1, [4, 6, 10, 8]),
            _annotation(2, 8, 1, [30, 6, 8, 8]),
            _annotation(3, 9, 2, [5, 5, 10, 8]),
        ],
    )
    sources = {
        7: _gradient_image(20, 15),
        8: _gradient_image(20, 15),
        9: _gradient_image(40, 30),
    }

    result, _store = _generate(monkeypatch, tmp_path, raw, images=sources)

    # A box that still fits the real pixel grid is rendered from that grid.
    record_7 = next(crop for crop in result.manifest.crops if crop.annotation_id == 1)
    assert (record_7.source_image_width, record_7.source_image_height) == (40, 30)
    assert (record_7.observed_image_width, record_7.observed_image_height) == (20, 15)
    assert (record_7.x_min, record_7.y_min, record_7.x_max, record_7.y_max) == (4, 6, 14, 14)
    assert (record_7.crop_width, record_7.crop_height) == (10, 8)
    with Image.open(Path(record_7.relative_path)) as crop:
        assert crop.tobytes() == sources[7].crop((4, 6, 14, 14)).tobytes()

    # Same when the declared grid is smaller than the real one.
    record_9 = next(crop for crop in result.manifest.crops if crop.annotation_id == 3)
    assert (record_9.source_image_width, record_9.source_image_height) == (20, 15)
    assert (record_9.observed_image_width, record_9.observed_image_height) == (40, 30)
    assert (record_9.x_min, record_9.y_min, record_9.x_max, record_9.y_max) == (5, 5, 15, 13)
    with Image.open(Path(record_9.relative_path)) as crop:
        assert crop.tobytes() == sources[9].crop((5, 5, 15, 13)).tobytes()

    # A box that only fits the declared grid is excluded, never silently clipped.
    assert [crop.annotation_id for crop in result.manifest.crops] == [1, 3]
    assert result.exclusions.exclusions[0].annotation_id == 2
    assert result.exclusions.exclusions[0].reasons == [
        "real_dimension_mismatch",
        "exceeds_real_image_bounds",
    ]
    assert not (CROPS_ROOT / "person" / "2.png").exists()

    assert [
        (mismatch.image_id, mismatch.declared_width, mismatch.observed_width)
        for mismatch in result.manifest.dimension_mismatches
    ] == [(7, 40, 20), (8, 40, 20), (9, 20, 40)]
    assert result.manifest.summary.images_with_dimension_mismatch == 3
    assert result.manifest.summary.crops == 2
    assert result.manifest.summary.excluded == 1


# ---------------------------------------------------------------------------
# Unresolvable sources: explicit failure, never a partial dataset
# ---------------------------------------------------------------------------


def test_storage_keys_query_is_a_single_lookup_by_image_id() -> None:
    engine = _FakeEngine(rows=[(7, "images/7.png"), (8, "images/8.png")])
    store = BackendImageStore(engine=engine, object_store=_FakeObjectStore({}))

    assert store.storage_keys([8, 7]) == {7: "images/7.png", 8: "images/8.png"}

    statement, parameters = engine.statements[0]
    assert "storage_key" in statement
    assert "images" in statement
    assert parameters == {"ids": (7, 8)}


def test_missing_images_row_fails_naming_the_missing_ids() -> None:
    engine = _FakeEngine(rows=[(7, "images/7.png")])
    store = BackendImageStore(engine=engine, object_store=_FakeObjectStore({}))

    with pytest.raises(CropSourceUnavailableError, match="8"):
        store.storage_keys([7, 8])


@pytest.mark.parametrize("storage_key", ["", "   ", None])
def test_blank_storage_key_is_rejected(storage_key: Any) -> None:
    engine = _FakeEngine(rows=[(7, storage_key)])
    store = BackendImageStore(engine=engine, object_store=_FakeObjectStore({}))

    with pytest.raises(CropSourceUnavailableError, match="7"):
        store.storage_keys([7])


def test_object_store_failures_are_wrapped_with_the_storage_key() -> None:
    store = BackendImageStore(
        engine=_FakeEngine(rows=[]),
        object_store=_FakeObjectStore({}, failing=("images/7.png",)),
    )

    with pytest.raises(CropSourceUnavailableError, match="images/7.png"):
        store.read_bytes("images/7.png")


def test_corrupt_source_image_fails_visibly_and_writes_no_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _raw_coco(
        images=[_image(7, 40, 30)],
        categories=[{"id": 1, "name": "person"}, {"id": 2, "name": "car"}],
        annotations=[_annotation(11, 7, 1, [1, 1, 5, 5])],
    )
    corrupt_store = FakeSourceImageStore({7: b"this is definitely not an image"})

    with pytest.raises(CropSourceDecodeError, match="id=7"):
        _generate(monkeypatch, tmp_path, raw, store=corrupt_store)

    assert not MANIFEST_PATH.exists()
    assert not EXCLUSIONS_PATH.exists()
    # Nothing was published at all: the crops tree never even appears.
    assert not CROPS_ROOT.exists()


def test_source_without_a_storage_key_fails_instead_of_key_erroring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _raw_coco(
        images=[_image(7, 40, 30)],
        categories=[{"id": 1, "name": "person"}, {"id": 2, "name": "car"}],
        annotations=[_annotation(11, 7, 1, [1, 1, 5, 5])],
    )
    store = FakeSourceImageStore({7: _png_bytes(_gradient_image(40, 30))}, missing_keys=True)

    with pytest.raises(CropSourceUnavailableError, match="7"):
        _generate(monkeypatch, tmp_path, raw, store=store)

    assert store.key_queries == [[7]]
    assert not MANIFEST_PATH.exists()


# ---------------------------------------------------------------------------
# Determinism: equal inputs, byte-identical outputs
# ---------------------------------------------------------------------------


def _processed_bytes() -> dict[str, bytes]:
    """Every file under data/processed, keyed by its relative POSIX path."""

    root = Path("data/processed")
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_two_runs_with_equal_inputs_produce_identical_json_and_png_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _raw_coco(
        images=[_image(7, 40, 30), _image(8, 24, 18)],
        categories=[{"id": 1, "name": "person"}, {"id": 2, "name": "car"}],
        annotations=[
            _annotation(11, 7, 2, [3.4, 5.2, 10.3, 7.9]),
            _annotation(12, 7, 1, [1, 1, 5, 5]),
            _annotation(13, 8, 1, [0, 0, 0, 5]),
            _annotation(14, 8, 2, [4, 4, 6.5, 6.5]),
        ],
    )
    sources = {7: _gradient_image(40, 30), 8: _gradient_image(24, 18)}

    first_run, _ = _generate(monkeypatch, tmp_path, raw, images=sources)
    first_bytes = _processed_bytes()
    assert sorted(first_bytes) == [
        "crop_exclusions.json",
        "crops/car/11.png",
        "crops/car/14.png",
        "crops/person/12.png",
        "crops_manifest.json",
    ]

    # Wipe the whole output tree and regenerate with a brand-new store double, so
    # nothing at all can be reused from the first run.
    shutil.rmtree(Path("data/processed"))
    second_run, _ = _generate(monkeypatch, tmp_path, raw, images=sources)

    assert second_run.manifest == first_run.manifest
    assert second_run.exclusions == first_run.exclusions
    assert _processed_bytes() == first_bytes
    # Nothing run-dependent (a timestamp, a host path, ...) may leak into the JSON.
    assert "generated_at" not in first_bytes["crops_manifest.json"].decode("utf-8")
    assert "generated_at" not in first_bytes["crop_exclusions.json"].decode("utf-8")
    # Their hashes are recorded downstream (classifier split provenance): no OS-dependent CRLF.
    assert b"\r\n" not in first_bytes["crops_manifest.json"]
    assert b"\r\n" not in first_bytes["crop_exclusions.json"]


def test_stale_crop_files_are_removed_so_the_tree_matches_the_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    stale = CROPS_ROOT / "person" / "999.png"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"stale bytes from an earlier run")
    raw = _raw_coco(
        images=[_image(7, 40, 30)],
        categories=[{"id": 1, "name": "person"}, {"id": 2, "name": "car"}],
        annotations=[_annotation(11, 7, 1, [1, 1, 5, 5])],
    )

    _generate(monkeypatch, tmp_path, raw, images={7: _gradient_image(40, 30)})

    assert not stale.exists()
    assert [path.relative_to(CROPS_ROOT).as_posix() for path in CROPS_ROOT.rglob("*.png")] == [
        "person/11.png"
    ]


# ---------------------------------------------------------------------------
# Atomic publication: a failed run never damages what is already published
# ---------------------------------------------------------------------------


def _staging_leftovers() -> list[str]:
    """Every unpublished staging path left behind under ``data/processed``."""

    root = Path("data/processed")
    return [
        path.relative_to(root).as_posix()
        for path in sorted(root.rglob("*"))
        if ".staging-" in path.name or ".previous-" in path.name
    ]


def test_failed_run_keeps_the_published_artifacts_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run that dies mid-way must not replace the previous release in part.

    Regression: ``crops/`` used to be wiped before the first image was fetched, so a
    later run failing on a missing/corrupt object left a truncated crop tree behind
    while ``crops_manifest.json`` and ``crop_exclusions.json`` still described the
    previous release.
    """

    published_coco = _raw_coco(
        images=[_image(7, 40, 30), _image(8, 40, 30)],
        categories=[{"id": 1, "name": "person"}, {"id": 2, "name": "car"}],
        annotations=[
            _annotation(11, 7, 1, [1, 1, 5, 5]),
            _annotation(13, 8, 2, [4, 4, 6, 6]),
        ],
    )
    _generate(
        monkeypatch,
        tmp_path,
        published_coco,
        images={7: _gradient_image(40, 30), 8: _gradient_image(40, 30)},
    )

    published = _processed_bytes()
    assert sorted(published) == [
        "crop_exclusions.json",
        "crops/car/13.png",
        "crops/person/11.png",
        "crops_manifest.json",
    ]

    # The second run would add a crop for image 7 and rewrite image 8's crop before
    # reaching id=9, whose stored bytes cannot be decoded: image ids are processed in
    # ascending order, so at least one other image is fully processed first.
    failing_coco = _raw_coco(
        images=[_image(7, 40, 30), _image(8, 40, 30), _image(9, 40, 30)],
        categories=[{"id": 1, "name": "person"}, {"id": 2, "name": "car"}],
        annotations=[
            _annotation(11, 7, 1, [1, 1, 5, 5]),
            _annotation(12, 7, 2, [8, 8, 6, 6]),
            _annotation(13, 8, 2, [4, 4, 6, 6]),
            _annotation(15, 9, 1, [1, 1, 5, 5]),
        ],
    )
    corrupt_store = FakeSourceImageStore(
        {
            7: _png_bytes(_gradient_image(40, 30)),
            8: _png_bytes(_gradient_image(40, 30)),
            9: b"this is definitely not an image",
        }
    )

    with pytest.raises(CropSourceDecodeError, match="id=9"):
        _generate(monkeypatch, tmp_path, failing_coco, store=corrupt_store)

    assert corrupt_store.byte_reads == ["images/7.png", "images/8.png", "images/9.png"]

    # Every previously published artifact is untouched, byte for byte: no partial crop
    # tree and no manifest that would disagree with it.
    assert _processed_bytes() == published
    # The crop the failing run had already rendered (image 7, annotation 12) was never
    # published, and the manifest still describes the previous release.
    assert not (CROPS_ROOT / "car" / "12.png").exists()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert [crop["annotation_id"] for crop in manifest["crops"]] == [11, 13]
    # The staging paths of the failed run are gone.
    assert _staging_leftovers() == []


# ---------------------------------------------------------------------------
# CLI: the DVC `crop` stage entry point
# ---------------------------------------------------------------------------


def test_cli_writes_outputs_and_prints_the_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = _raw_coco(
        images=[_image(7, 40, 30)],
        categories=[{"id": 1, "name": "person"}, {"id": 2, "name": "car"}],
        annotations=[
            _annotation(11, 7, 2, [1, 1, 5, 5]),
            _annotation(12, 7, 1, [0, 0, 0, 0]),
        ],
    )
    store = FakeSourceImageStore({7: _png_bytes(_gradient_image(40, 30))})
    monkeypatch.chdir(tmp_path)
    _write_coco(COCO_PATH, raw)
    _write_quality_report(QUALITY_PATH, "pass")
    monkeypatch.setattr("sys.argv", _cli_argv())

    crops_main(source_store=store)

    assert MANIFEST_PATH.exists()
    assert EXCLUSIONS_PATH.exists()
    summary = json.loads(capsys.readouterr().out)
    assert summary["crops"] == 1
    assert summary["crops_by_category"] == {"person": 0, "car": 1}
    assert summary["excluded"] == 1
    assert summary["target_annotations"] == 2
    assert store.byte_reads == ["images/7.png"]


def test_cli_blocks_and_writes_nothing_when_the_quality_gate_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = _raw_coco(
        images=[_image(7, 40, 30)],
        categories=[{"id": 1, "name": "person"}, {"id": 2, "name": "car"}],
        annotations=[_annotation(11, 7, 2, [1, 1, 5, 5])],
    )
    store = FakeSourceImageStore({7: _png_bytes(_gradient_image(40, 30))})
    monkeypatch.chdir(tmp_path)
    _write_coco(COCO_PATH, raw)
    _write_quality_report(QUALITY_PATH, "fail")
    monkeypatch.setattr("sys.argv", _cli_argv())

    with pytest.raises(SystemExit) as exit_info:
        crops_main(source_store=store)

    assert exit_info.value.code == 1
    assert "quality" in capsys.readouterr().err.lower()
    assert store.key_queries == []
    assert not MANIFEST_PATH.exists()
    assert not CROPS_ROOT.exists()


def test_cli_crops_only_the_categories_it_is_configured_with(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = _raw_coco(
        images=[_image(7, 40, 30)],
        categories=[{"id": 1, "name": "person"}, {"id": 2, "name": "car"}],
        annotations=[_annotation(11, 7, 1, [1, 1, 5, 5])],
    )
    store = FakeSourceImageStore({})
    monkeypatch.chdir(tmp_path)
    _write_coco(COCO_PATH, raw)
    _write_quality_report(QUALITY_PATH, "pass")
    monkeypatch.setattr("sys.argv", _cli_argv(categories=("car",), version="v2.0.0"))

    crops_main(source_store=store)

    summary = json.loads(capsys.readouterr().out)
    assert summary["crops_by_category"] == {"car": 0}
    assert summary["ignored_non_target"] == 1
    assert summary["crops"] == 0
    assert store.key_queries == []
    assert json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["dataset_version"] == "v2.0.0"


def test_crop_package_reuses_the_centralized_client_layer_only() -> None:
    """No boto3 and no engine construction outside ``config/clients.py``."""

    package_root = PIPELINE_ROOT / "src" / "dataset_quality" / "crops"
    sources = {
        path.name: path.read_text(encoding="utf-8") for path in sorted(package_root.glob("*.py"))
    }

    assert "sources.py" in sources
    for name, text in sources.items():
        assert "import boto3" not in text, name
        assert "from boto3" not in text, name
        assert "boto3.client" not in text, name
        assert "create_engine(" not in text, name
    assert "from dataset_quality.config.clients import get_db_engine" in sources["sources.py"]
    assert "from dataset_quality.storage.object_store import ObjectStore" in sources["sources.py"]


# ---------------------------------------------------------------------------
# DVC stage wiring
# ---------------------------------------------------------------------------


def _dvc_stages() -> dict[str, Any]:
    payload = yaml.safe_load((PIPELINE_ROOT / "dvc.yaml").read_text(encoding="utf-8"))
    return payload["stages"]


def test_dvc_crop_stage_consumes_the_canonical_coco_quality_report_and_code() -> None:
    stages = _dvc_stages()

    assert "crop" in stages, "T3-1.1 must add a `crop` stage"
    crop = stages["crop"]

    deps = set(crop["deps"])
    assert {"data/interim/coco.json", "data/interim/quality.json"} <= deps
    for module in (
        "__main__.py",
        "errors.py",
        "generator.py",
        "geometry.py",
        "models.py",
        "planning.py",
        "sources.py",
    ):
        assert f"src/dataset_quality/crops/{module}" in deps
    assert "src/dataset_quality/storage/object_store.py" in deps
    assert "src/dataset_quality/config/clients.py" in deps
    assert "src/dataset_quality/config/settings.py" in deps

    assert crop["params"] == ["dataset_version", "m3.target_categories"]
    assert set(crop["outs"]) == {
        "data/processed/crops",
        "data/processed/crops_manifest.json",
        "data/processed/crop_exclusions.json",
    }

    command = crop["cmd"]
    assert "dataset_quality.crops" in command
    assert "--quality-report data/interim/quality.json" in command
    assert "${dataset_version}" in command
    assert "${m3.target_categories[0]}" in command
    assert "${m3.target_categories[1]}" in command
    for output in crop["outs"]:
        assert output in command


def test_dvc_split_stage_stays_the_inherited_seventy_fifteen_fifteen_stage() -> None:
    """T3-1.2 owns the new manifest; T3-1.1 must not touch the inherited split."""

    split = _dvc_stages()["split"]

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
    for placeholder in ("${split.train}", "${split.val}", "${split.test}", "${split.seed}"):
        assert placeholder in split["cmd"]


def test_shared_params_keep_the_frozen_classes_and_proportions() -> None:
    params = yaml.safe_load((PIPELINE_ROOT / "params.yaml").read_text(encoding="utf-8"))

    assert params["dataset_version"] == "v1.0.0"
    assert params["m3"]["target_categories"] == ["person", "car"]
    assert (params["split"]["train"], params["split"]["val"], params["split"]["test"]) == (
        0.70,
        0.15,
        0.15,
    )
