"""DQ-08: Adversarial test suite for Quality Gate and analyzers (issue #33).

Exercises intentional defects and verifies that analyzers and the Quality Gate
fail closed:
1. Negative-width and out-of-bounds boxes detected before downstream consumption.
2. Perceptual duplicate detection of recompressed images vs. distinct controls.
3. Quality Gate CLI execution via subprocess with exit code != 0, report generation,
   and downstream stage blocking (split, export, promotion) via observable callbacks.
4. Quality Gate CLI execution with non-blocking WARN allowing downstream stages.
5. Reactive configuration changes in YAML altering CLI outcomes without code changes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError

from dataset_quality.analyzers.dq05 import (
    ImageReference,
    PerceptualHashConfig,
    detect_invalid_boxes,
    find_near_duplicate_images,
)
from dataset_quality.config.models import SplitConfig
from dataset_quality.ingestion.models import (
    CocoAnnotation,
    CocoCategory,
    CocoDataset,
    CocoImage,
)
from dataset_quality.quality_gate.runner import (
    QualityGateBlockedError,
    QualityGateDecision,
    execute_quality_gate,
)
from dataset_quality.splits.generator import generate_splits

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml_policy(path: Path, min_images: int = 300, spatial_threshold: float = 30.0) -> None:
    path.write_text(
        f"""min_images_per_class:
  label: Minimum images per class
  threshold: {min_images}
  severity: fail
  comparison: min
  unit: images
class_imbalance:
  label: Class imbalance ratio
  threshold: 3.0
  severity: warn
  comparison: max
  unit: ratio
spatial_bias:
  label: Maximum spatial cell concentration
  threshold: {spatial_threshold}
  severity: warn
  comparison: max
  unit: percent
duplicates:
  label: Near duplicate images
  threshold: 0
  severity: fail
  comparison: max
  unit: pairs
invalid_boxes:
  label: Degenerate bounding boxes
  threshold: 0
  severity: fail
  comparison: max
  unit: boxes
""",
        encoding="utf-8",
    )


def _minimal_valid_dataset() -> CocoDataset:
    return CocoDataset(
        images=[
            CocoImage(id=1, file_name="img1.jpg", width=200, height=200),
            CocoImage(id=2, file_name="img2.jpg", width=200, height=200),
            CocoImage(id=3, file_name="img3.jpg", width=200, height=200),
        ],
        categories=[CocoCategory(id=1, name="car")],
        annotations=[
            CocoAnnotation(id=1, image_id=1, category_id=1, bbox=[10, 10, 50, 50]),
            CocoAnnotation(id=2, image_id=2, category_id=1, bbox=[20, 20, 50, 50]),
            CocoAnnotation(id=3, image_id=3, category_id=1, bbox=[30, 30, 50, 50]),
        ],
    )


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------


def test_adversarial_invalid_boxes_negative_width_and_out_of_bounds() -> None:
    """Raw COCO with negative width and out-of-bounds boxes must be detected.

    Also asserts that strict Pydantic models reject negative dimensions so that
    corrupted annotations never reach downstream stages silently.
    """
    raw_coco: dict[str, Any] = {
        "images": [
            {"id": 1, "file_name": "test1.jpg", "width": 640, "height": 480},
            {"id": 2, "file_name": "test2.jpg", "width": 640, "height": 480},
        ],
        "categories": [{"id": 1, "name": "car"}],
        "annotations": [
            # 1. Negative width
            {"id": 101, "image_id": 1, "category_id": 1, "bbox": [50.0, 50.0, -10.0, 30.0]},
            # 2. Coordinate starting outside image bounds
            {"id": 102, "image_id": 1, "category_id": 1, "bbox": [700.0, 50.0, 40.0, 40.0]},
            # 3. Coordinate within bounds but box exceeds image dimensions
            {"id": 103, "image_id": 2, "category_id": 1, "bbox": [600.0, 400.0, 100.0, 100.0]},
            # 4. Valid box for control
            {"id": 104, "image_id": 2, "category_id": 1, "bbox": [10.0, 10.0, 50.0, 50.0]},
        ],
    }

    # Verify analyzer detection
    result = detect_invalid_boxes(raw_coco)
    issues_by_id = {issue.annotation_id: issue.reasons for issue in result.invalid_boxes}

    assert 101 in issues_by_id
    assert "nonpositive_width" in issues_by_id[101]

    assert 102 in issues_by_id
    assert "coordinate_outside_image" in issues_by_id[102]

    assert 103 in issues_by_id
    assert "exceeds_image_bounds" in issues_by_id[103]

    assert 104 not in issues_by_id
    assert len(result.invalid_boxes) == 3

    # Verify that strict Pydantic CocoDataset refuses negative width
    with pytest.raises(ValidationError) as exc_info:
        CocoDataset.model_validate(raw_coco)
    errors = str(exc_info.value)
    assert "bbox" in errors


def test_adversarial_near_duplicate_recompressed_vs_distinct_control(tmp_path: Path) -> None:
    """Recompressed image is detected as near-duplicate while a visual control is not."""
    img_dir = tmp_path / "images"
    img_dir.mkdir()

    # 1. Base image with synthetic pattern
    base_path = img_dir / "base.jpg"
    base_img = Image.new("RGB", (200, 200), color=(240, 240, 240))
    draw = ImageDraw.Draw(base_img)
    draw.rectangle([20, 20, 80, 80], fill=(20, 40, 180))
    draw.ellipse([100, 100, 180, 180], fill=(180, 40, 20))
    base_img.save(base_path, "JPEG", quality=95)

    # 2. Recompressed version of base image (lower quality JPEG)
    recompressed_path = img_dir / "recompressed.jpg"
    base_img.save(recompressed_path, "JPEG", quality=25)

    # 3. Visually distinct control image (diagonal stripes, inverted palette)
    control_path = img_dir / "control.jpg"
    control_img = Image.new("RGB", (200, 200), color=(10, 10, 10))
    ctrl_draw = ImageDraw.Draw(control_img)
    for i in range(0, 200, 20):
        ctrl_draw.line([(0, i), (i, 0)], fill=(255, 255, 255), width=8)
    control_img.save(control_path, "JPEG", quality=95)

    refs = [
        ImageReference(image_id=1, path=base_path),
        ImageReference(image_id=2, path=recompressed_path),
        ImageReference(image_id=3, path=control_path),
    ]

    # Evaluate with pHash threshold max_distance=10
    config = PerceptualHashConfig(hash_size=8, max_distance=10)
    result = find_near_duplicate_images(refs, config=config)

    detected_pairs = [(p.image_id_a, p.image_id_b) for p in result.pairs]

    # Base (1) and Recompressed (2) must be detected as duplicate
    assert (1, 2) in detected_pairs
    pair_1_2 = next(p for p in result.pairs if (p.image_id_a, p.image_id_b) == (1, 2))
    assert pair_1_2.distance <= 10
    assert pair_1_2.similarity >= 0.84

    # Control (3) must NOT be detected as duplicate with base (1) or recompressed (2)
    assert (1, 3) not in detected_pairs
    assert (2, 3) not in detected_pairs
    assert len(detected_pairs) == 1


def test_adversarial_cli_gate_execution_fail_blocks_downstream_stages(tmp_path: Path) -> None:
    """CLI execution with impossible threshold exits non-zero and blocks downstream stages.

    Downstream stages (split, export, promotion) are guarded by QualityGateDecision.
    Observable callbacks verify that no downstream stage is executed when gate fails.
    """
    policy_path = tmp_path / "quality.yaml"
    _write_yaml_policy(policy_path, min_images=999999)

    obs_path = tmp_path / "observations.json"
    observations = {
        "min_images_per_class": 311,
        "class_imbalance": 1.2,
        "spatial_bias": 15.0,
        "duplicates": 0,
        "invalid_boxes": 0,
    }
    obs_path.write_text(json.dumps(observations), encoding="utf-8")

    report_path = tmp_path / "quality.json"

    # Execute real CLI via subprocess
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "dataset_quality.quality_gate.runner",
            "--policy",
            str(policy_path),
            "--observations",
            str(obs_path),
            "--dataset-version",
            "v-adv-fail",
            "--report",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    # 1. Process exit code must be non-zero (1 for FAIL)
    assert proc.returncode == 1

    # 2. quality.json must be written and contain overall_status == "fail"
    assert report_path.exists()
    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_data["overall_status"] == "fail"
    min_check = next(c for c in report_data["checks"] if c["id"] == "min_images_per_class")
    assert min_check["status"] == "fail"
    assert min_check["observed"] == 311
    assert min_check["threshold"] == 999999

    # 3. Downstream stage guards with observable callbacks
    decision = execute_quality_gate(
        policy_path=policy_path,
        observations=observations,
        dataset_version="v-adv-fail",
        report_path=tmp_path / "runtime_quality.json",
    )
    assert decision.exit_code == 1
    assert not decision.allows("split")
    assert not decision.allows("export")
    assert not decision.allows("promotion")

    executed_callbacks: list[str] = []

    def mock_downstream_stage(stage_name: str, gate_decision: QualityGateDecision) -> None:
        """Observable callback demonstrating downstream stage protection."""
        gate_decision.require(stage_name)  # type: ignore[arg-type]
        executed_callbacks.append(stage_name)

    for stage in ("split", "export", "promotion"):
        with pytest.raises(QualityGateBlockedError, match=stage):
            mock_downstream_stage(stage, decision)

    # Verify no downstream callbacks were executed
    assert executed_callbacks == []

    # Also verify real generate_splits refuses to run
    with pytest.raises(QualityGateBlockedError, match="split"):
        generate_splits(
            _minimal_valid_dataset(),
            SplitConfig(train=0.7, val=0.2, test=0.1, seed=42),
            dataset_version="v-adv-fail",
            quality_gate=decision,
        )


def test_adversarial_cli_gate_execution_warn_allows_downstream_stages(tmp_path: Path) -> None:
    """CLI execution with WARN exits 0 and allows downstream stages via callbacks."""
    policy_path = tmp_path / "quality.yaml"
    _write_yaml_policy(policy_path, min_images=300, spatial_threshold=30.0)

    obs_path = tmp_path / "observations.json"
    # spatial_bias is 42.0 > threshold 30.0 (severity: warn)
    observations = {
        "min_images_per_class": 310,
        "class_imbalance": 1.1,
        "spatial_bias": 42.0,
        "duplicates": 0,
        "invalid_boxes": 0,
    }
    obs_path.write_text(json.dumps(observations), encoding="utf-8")

    report_path = tmp_path / "quality.json"

    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "dataset_quality.quality_gate.runner",
            "--policy",
            str(policy_path),
            "--observations",
            str(obs_path),
            "--dataset-version",
            "v-adv-warn",
            "--report",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    # 1. Process exit code must be 0 for WARN
    assert proc.returncode == 0

    # 2. quality.json must reflect overall_status == "warn"
    assert report_path.exists()
    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_data["overall_status"] == "warn"

    # 3. Downstream stages must be allowed
    decision = execute_quality_gate(
        policy_path=policy_path,
        observations=observations,
        dataset_version="v-adv-warn",
        report_path=tmp_path / "runtime_quality.json",
    )
    assert decision.exit_code == 0
    assert decision.allows("split")
    assert decision.allows("export")
    assert decision.allows("promotion")

    executed_callbacks: list[str] = []

    def mock_downstream_stage(stage_name: str, gate_decision: QualityGateDecision) -> None:
        gate_decision.require(stage_name)  # type: ignore[arg-type]
        executed_callbacks.append(stage_name)

    for stage in ("split", "export", "promotion"):
        mock_downstream_stage(stage, decision)

    assert executed_callbacks == ["split", "export", "promotion"]

    # generate_splits proceeds without error
    splits = generate_splits(
        _minimal_valid_dataset(),
        SplitConfig(train=0.7, val=0.2, test=0.1, seed=42),
        dataset_version="v-adv-warn",
        quality_gate=decision,
    )
    assert sum(len(ids) for ids in splits.assignment.values()) == 3


def test_adversarial_yaml_change_alters_cli_outcome_without_python_changes(tmp_path: Path) -> None:
    """Editing quality.yaml threshold changes CLI exit code without altering Python code."""
    policy_path = tmp_path / "quality.yaml"
    obs_path = tmp_path / "observations.json"
    report_path = tmp_path / "quality.json"

    # Fixed observation
    observations = {
        "min_images_per_class": 300,
        "class_imbalance": 1.0,
        "spatial_bias": 10.0,
        "duplicates": 0,
        "invalid_boxes": 0,
    }
    obs_path.write_text(json.dumps(observations), encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")

    # Step 1: Policy threshold 301 -> observation 300 FAILS
    _write_yaml_policy(policy_path, min_images=301)
    proc_fail = subprocess.run(
        [
            sys.executable,
            "-m",
            "dataset_quality.quality_gate.runner",
            "--policy",
            str(policy_path),
            "--observations",
            str(obs_path),
            "--dataset-version",
            "v-test-yaml",
            "--report",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc_fail.returncode == 1

    # Step 2: Policy threshold relaxed to 300 -> observation 300 PASSES
    _write_yaml_policy(policy_path, min_images=300)
    proc_pass = subprocess.run(
        [
            sys.executable,
            "-m",
            "dataset_quality.quality_gate.runner",
            "--policy",
            str(policy_path),
            "--observations",
            str(obs_path),
            "--dataset-version",
            "v-test-yaml",
            "--report",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc_pass.returncode == 0
