import pytest
from pydantic import ValidationError

from dataset_quality.config.models import QualityCheckConfig, QualityConfig, SplitConfig


def test_quality_config_accepts_checks_with_threshold_and_supported_severity() -> None:
    config = QualityConfig(
        checks={
            "min_images_per_class": QualityCheckConfig(threshold=300, severity="fail"),
            "small_objects": QualityCheckConfig(threshold=40.0, severity="warn"),
        }
    )

    assert config.checks["min_images_per_class"].threshold == 300
    assert config.checks["small_objects"].severity == "warn"


def test_quality_config_rejects_unsupported_severity() -> None:
    with pytest.raises(ValidationError) as error:
        QualityCheckConfig(threshold=300, severity="critical")

    assert "severity" in str(error.value)


def test_split_config_requires_proportions_that_sum_to_one() -> None:
    with pytest.raises(ValidationError) as error:
        SplitConfig(train=0.7, val=0.2, test=0.2, seed=42)

    assert "proportions" in str(error.value)
