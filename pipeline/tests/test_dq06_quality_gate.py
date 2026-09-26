from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataset_quality.analyzers.dq06 import analyze_spatial_bias
from dataset_quality.config.models import SplitConfig
from dataset_quality.ingestion.models import CocoAnnotation, CocoCategory, CocoDataset, CocoImage
from dataset_quality.quality_gate.runner import QualityGateBlockedError, execute_quality_gate
from dataset_quality.splits.generator import generate_splits


def _dataset() -> CocoDataset:
    return CocoDataset(
        images=[
            CocoImage(id=1, file_name="one.jpg", width=100, height=100),
            CocoImage(id=2, file_name="two.jpg", width=100, height=100),
            CocoImage(id=3, file_name="three.jpg", width=100, height=100),
        ],
        categories=[CocoCategory(id=1, name="car")],
        annotations=[
            CocoAnnotation(id=1, image_id=1, category_id=1, bbox=[5, 5, 10, 10]),
            CocoAnnotation(id=2, image_id=2, category_id=1, bbox=[45, 45, 10, 10]),
            CocoAnnotation(id=3, image_id=3, category_id=1, bbox=[85, 85, 10, 10]),
        ],
    )


def _write_policy(path: Path, minimum: int = 300) -> None:
    path.write_text(
        f"""min_images_per_class:
  label: Minimum images per class
  threshold: {minimum}
  severity: fail
  comparison: min
  unit: images
class_imbalance:
  label: Class imbalance ratio
  threshold: 2.0
  severity: warn
  comparison: max
  unit: ratio
spatial_bias:
  label: Maximum spatial cell concentration
  threshold: 30.0
  severity: warn
  comparison: max
  unit: percent
""",
        encoding="utf-8",
    )


def test_spatial_bias_reports_center_statistics_percentiles_and_grid_distribution() -> None:
    result = analyze_spatial_bias(_dataset())

    assert result.valid_boxes == 3
    assert result.x.mean == pytest.approx(0.5)
    assert result.x.median == pytest.approx(0.5)
    assert result.x.p10 == pytest.approx(0.18)
    assert result.x.p90 == pytest.approx(0.82)
    assert result.y == result.x
    assert result.grid_counts == {"0,0": 1, "1,1": 1, "2,2": 1}
    assert result.max_cell_percentage == pytest.approx(100 / 3)


def test_warn_writes_quality_json_but_does_not_block_downstream_stages(tmp_path: Path) -> None:
    policy_path = tmp_path / "quality.yaml"
    report_path = tmp_path / "quality.json"
    _write_policy(policy_path)

    decision = execute_quality_gate(
        policy_path=policy_path,
        observations={"min_images_per_class": 300, "class_imbalance": 2.5, "spatial_bias": 10},
        dataset_version="v-test",
        report_path=report_path,
        evidence_by_check={
            "class_imbalance": {
                "details": {"majority_class": "car"},
                "offending_samples": [{"image_id": 3, "class": "car"}],
            }
        },
    )

    assert decision.exit_code == 0
    assert decision.report.overall_status == "warn"
    assert all(decision.allows(stage) for stage in ("split", "export", "promotion"))
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["overall_status"] == "warn"
    assert payload["checks"][1]["details"] == {"majority_class": "car"}
    assert payload["checks"][1]["offending_samples"] == [{"image_id": 3, "class": "car"}]


def test_fail_returns_nonzero_and_blocks_split_export_and_promotion(tmp_path: Path) -> None:
    policy_path = tmp_path / "quality.yaml"
    report_path = tmp_path / "quality.json"
    _write_policy(policy_path, minimum=999999)

    decision = execute_quality_gate(
        policy_path=policy_path,
        observations={"min_images_per_class": 3, "class_imbalance": 1.0, "spatial_bias": 10},
        dataset_version="v-test",
        report_path=report_path,
    )

    assert decision.exit_code == 1
    assert decision.report.overall_status == "fail"
    assert report_path.exists()
    for stage in ("split", "export", "promotion"):
        with pytest.raises(QualityGateBlockedError, match=stage):
            decision.require(stage)
    with pytest.raises(QualityGateBlockedError, match="split"):
        generate_splits(
            _dataset(),
            SplitConfig(train=0.7, val=0.2, test=0.1, seed=7),
            "v-test",
            quality_gate=decision,
        )
