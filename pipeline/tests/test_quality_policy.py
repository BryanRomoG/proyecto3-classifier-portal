from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from dataset_quality.ingestion.models import CocoAnnotation, CocoCategory, CocoDataset, CocoImage
from dataset_quality.quality_gate.models import QualityDatasetSummary, QualityPolicy, QualityReport
from dataset_quality.quality_gate.policy import evaluate_policy, load_policy


def _tiny_dataset() -> CocoDataset:
    """2 images, 3 annotations, 2 categories — just enough to check counts."""

    return CocoDataset(
        images=[
            CocoImage(id=1, file_name="images/img_00001.jpg", width=640, height=480),
            CocoImage(id=2, file_name="images/img_00002.jpg", width=640, height=480),
        ],
        categories=[
            CocoCategory(id=1, name="car"),
            CocoCategory(id=2, name="bicycle"),
        ],
        annotations=[
            CocoAnnotation(id=1, image_id=1, category_id=1, bbox=[10, 10, 20, 20]),
            CocoAnnotation(id=2, image_id=1, category_id=2, bbox=[30, 30, 10, 10]),
            CocoAnnotation(id=3, image_id=2, category_id=1, bbox=[5, 5, 15, 15]),
        ],
    )


def test_base_policy_requires_300_images_per_class_and_fail_severity() -> None:
    policy_path = Path(__file__).parents[1] / "quality.yaml"

    policy = load_policy(policy_path)
    minimum_images = policy.checks["min_images_per_class"]

    assert minimum_images.threshold >= 300
    assert minimum_images.severity == "fail"


@pytest.mark.parametrize(
    "check",
    [
        {"label": "Minimum images", "severity": "fail", "comparison": "min", "unit": "images"},
        {"label": "Minimum images", "threshold": 300, "comparison": "min", "unit": "images"},
        {
            "label": "Minimum images",
            "threshold": 300,
            "severity": "critical",
            "comparison": "min",
            "unit": "images",
        },
    ],
)
def test_policy_rejects_missing_threshold_severity_or_invalid_severity(
    check: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        QualityPolicy.from_mapping({"min_images_per_class": check})


def test_changing_yaml_threshold_changes_evaluation_without_python_changes(tmp_path: Path) -> None:
    policy_path = tmp_path / "quality.yaml"
    policy_path.write_text(
        """min_images_per_class:
  label: Minimum images per class
  threshold: 301
  severity: fail
  comparison: min
  unit: images
""",
        encoding="utf-8",
    )

    failing_report = evaluate_policy(
        load_policy(policy_path),
        observations={"min_images_per_class": 300},
        dataset_version="v-test",
    )
    assert failing_report.overall_status == "fail"
    assert failing_report.checks[0].status == "fail"

    policy_path.write_text(
        """min_images_per_class:
  label: Minimum images per class
  threshold: 300
  severity: fail
  comparison: min
  unit: images
""",
        encoding="utf-8",
    )
    passing_report = evaluate_policy(
        load_policy(policy_path),
        observations={"min_images_per_class": 300},
        dataset_version="v-test",
    )

    assert passing_report.overall_status == "pass"
    assert passing_report.checks[0].threshold == 300
    assert passing_report.checks[0].observed == 300


def test_quality_report_contract_keeps_required_fields_and_offending_samples() -> None:
    report = QualityReport.model_validate(
        {
            "dataset_version": "v-test",
            "generated_at": "2026-09-15T00:00:00Z",
            "overall_status": "warn",
            "checks": [
                {
                    "id": "class_imbalance",
                    "label": "Class imbalance ratio",
                    "severity": "warn",
                    "status": "warn",
                    "threshold": 3.0,
                    "observed": 4.2,
                    "unit": "majority/minority ratio",
                    "details": {"majority_class": "car"},
                    "offending_samples": [{"image_id": "img_00412", "class": "bicycle"}],
                }
            ],
        }
    )

    check = report.checks[0]
    assert check.observed == 4.2
    assert check.threshold == 3.0
    assert check.status == "warn"
    assert check.severity == "warn"
    assert check.offending_samples == [{"image_id": "img_00412", "class": "bicycle"}]


def test_versioned_quality_contract_example_validates_with_pydantic() -> None:
    project_root = Path(os.environ.get("PROJECT_ROOT", Path(__file__).parents[2]))
    contract_path = project_root / "contracts" / "quality.json"
    payload = json.loads(contract_path.read_text(encoding="utf-8"))

    report = QualityReport.model_validate(payload)

    assert report.dataset_version == "v0.2.0-mock"
    assert report.checks[0].id == "min_images_per_class"
    # APP-05 Overview needs dataset-level totals that no single check carries
    # on its own (total images, total bounding boxes, total categories).
    assert report.dataset_summary is not None
    assert report.dataset_summary.total_images > 0
    assert report.dataset_summary.total_bounding_boxes > 0
    assert report.dataset_summary.total_categories > 0


def test_dataset_summary_is_populated_when_a_dataset_is_passed_to_evaluate_policy(
    tmp_path: Path,
) -> None:
    policy_path = tmp_path / "quality.yaml"
    policy_path.write_text(
        """min_images_per_class:
  label: Minimum images per class
  threshold: 300
  severity: fail
  comparison: min
  unit: images
""",
        encoding="utf-8",
    )

    report = evaluate_policy(
        load_policy(policy_path),
        observations={"min_images_per_class": 2},
        dataset_version="v-test",
        dataset=_tiny_dataset(),
    )

    assert report.dataset_summary == QualityDatasetSummary(
        total_images=2, total_bounding_boxes=3, total_categories=2
    )


def test_dataset_summary_is_none_when_no_dataset_is_passed_to_evaluate_policy(
    tmp_path: Path,
) -> None:
    policy_path = tmp_path / "quality.yaml"
    policy_path.write_text(
        """min_images_per_class:
  label: Minimum images per class
  threshold: 300
  severity: fail
  comparison: min
  unit: images
""",
        encoding="utf-8",
    )

    report = evaluate_policy(
        load_policy(policy_path),
        observations={"min_images_per_class": 2},
        dataset_version="v-test",
    )

    assert report.dataset_summary is None


def test_dataset_summary_none_serializes_as_json_null_and_round_trips(tmp_path: Path) -> None:
    """Review fix (APP-05 PR): Pydantic serializes ``dataset_summary=None`` as a
    literal JSON ``null`` — it does not omit the key. A consumer (the frontend
    Zod schema) that only accepts the key being *absent* rejects this real,
    valid output. This pins down the actual JSON shape so that contract stays
    documented on the pipeline side too.
    """

    policy_path = tmp_path / "quality.yaml"
    policy_path.write_text(
        """min_images_per_class:
  label: Minimum images per class
  threshold: 300
  severity: fail
  comparison: min
  unit: images
""",
        encoding="utf-8",
    )

    report = evaluate_policy(
        load_policy(policy_path),
        observations={"min_images_per_class": 2},
        dataset_version="v-test",
    )

    payload = json.loads(report.model_dump_json())
    assert "dataset_summary" in payload
    assert payload["dataset_summary"] is None

    # And it must still round-trip: a consumer that stores/replays this exact
    # JSON should be able to load it back into a QualityReport.
    assert QualityReport.model_validate(payload).dataset_summary is None


def test_quality_dataset_summary_rejects_fields_outside_the_contract() -> None:
    with pytest.raises(ValidationError, match="extra"):
        QualityDatasetSummary.model_validate(
            {
                "total_images": 10,
                "total_bounding_boxes": 20,
                "total_categories": 2,
                "_note": "not part of the contract",
            }
        )
