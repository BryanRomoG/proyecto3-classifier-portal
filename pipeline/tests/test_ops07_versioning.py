from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataset_quality.versioning.__main__ import _diff, _parse_semver, main
from dataset_quality.versioning.models import VersionSnapshot


def test_parse_semver_accepts_plain_major_minor_patch() -> None:
    assert _parse_semver("v1.0.0") == (1, 0, 0)
    assert _parse_semver("v2.11.3") == (2, 11, 3)


@pytest.mark.parametrize("version", ["1.0.0", "v1.0", "v1.0.0-dev", "vX.0.0", "v1.0.0.0"])
def test_parse_semver_rejects_anything_else(version: str) -> None:
    with pytest.raises(ValueError, match="MAJOR"):
        _parse_semver(version)


def _snapshot(
    image_count: int,
    box_count: int,
    per_class_counts: dict[str, int],
    small_object_percentage: float,
) -> VersionSnapshot:
    return VersionSnapshot(
        image_count=image_count,
        box_count=box_count,
        per_class_counts=per_class_counts,
        small_object_percentage=small_object_percentage,
    )


def test_diff_signs_match_direction_of_change_not_just_magnitude() -> None:
    previous = _snapshot(100, 250, {"person": 300, "car": 305}, 10.0)
    current = _snapshot(90, 260, {"person": 300, "car": 305}, 12.5)

    diff = _diff(current, previous, min_images_threshold=300)

    assert diff.images_added == -10  # fewer images than before: negative, not "removed=10"
    assert diff.boxes_added == 10
    assert diff.small_object_ratio_change_pct == pytest.approx(2.5)


def test_diff_classes_left_minimum_only_lists_new_regressions() -> None:
    # "car" was already below 300 last release — not a *new* regression this time.
    # "person" just dropped below 300 this release — that IS a new regression.
    # "bike" stays comfortably above 300 both times — never listed.
    previous = _snapshot(500, 1000, {"person": 305, "car": 280, "bike": 400}, 5.0)
    current = _snapshot(495, 990, {"person": 298, "car": 275, "bike": 390}, 5.0)

    diff = _diff(current, previous, min_images_threshold=300)

    assert diff.classes_left_minimum == ["person"]


def test_diff_classes_left_minimum_empty_when_nothing_newly_regresses() -> None:
    previous = _snapshot(500, 1000, {"person": 310, "car": 320}, 5.0)
    current = _snapshot(505, 1010, {"person": 312, "car": 325}, 5.0)

    diff = _diff(current, previous, min_images_threshold=300)

    assert diff.classes_left_minimum == []


# --- main()'s version-ordering guard ---------------------------------------
#
# `main()` parses `--dataset-version` and checks it against the history ledger
# *before* it ever reads --coco/--quality-report/--m3-baseline/--observations/
# --policy, so those can stay as placeholder (non-existent) paths in these
# tests — the ValueError fires first. Only --history's content matters.


def _run_main(monkeypatch: pytest.MonkeyPatch, *, dataset_version: str, history: Path) -> None:
    argv = [
        "versioning",
        "--coco",
        "unused-coco.json",
        "--quality-report",
        "unused-quality.json",
        "--m3-baseline",
        "unused-m3.json",
        "--observations",
        "unused-observations.json",
        "--policy",
        "unused-policy.yaml",
        "--dataset-version",
        dataset_version,
        "--history",
        str(history),
        "--output",
        "unused-output.json",
    ]
    monkeypatch.setattr("sys.argv", argv)
    main()


def _existing_release_history(tmp_path: Path, *, version: str) -> Path:
    """A minimal, schema-valid `version_history.json` ledger with one past release."""
    history_path = tmp_path / "version_history.json"
    history_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "entry": {
                            "version": version,
                            "released_at": "2026-01-01T00:00:00Z",
                            "content_hash": "deadbeef",
                            "quality_status": "pass",
                            "environments": {
                                "dev": {
                                    "provider": "minio",
                                    "status": "available",
                                    "synced_at": "2026-01-01T00:00:00Z",
                                },
                                "prod": {
                                    "provider": "s3",
                                    "status": "pending",
                                    "synced_at": None,
                                },
                            },
                            "diff_from_previous": None,
                        },
                        "snapshot": {
                            "image_count": 300,
                            "box_count": 900,
                            "per_class_counts": {"person": 300, "car": 300},
                            "small_object_percentage": 5.0,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return history_path


def test_main_rejects_a_dataset_version_that_does_not_strictly_increase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history = _existing_release_history(tmp_path, version="v1.0.0")

    with pytest.raises(ValueError, match="must be strictly greater"):
        _run_main(monkeypatch, dataset_version="v0.9.0", history=history)

    # Also rejects a *repeated* version, not just a lower one.
    with pytest.raises(ValueError, match="must be strictly greater"):
        _run_main(monkeypatch, dataset_version="v1.0.0", history=history)


def test_main_requires_v1_0_0_as_the_first_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_history = tmp_path / "version_history.json"  # deliberately never written

    with pytest.raises(ValueError, match="first dataset release must be v1.0.0"):
        _run_main(monkeypatch, dataset_version="v1.1.0", history=empty_history)


# --- main()'s Quality Gate guard --------------------------------------------
#
# `release` must not record a version whose gate is red. In the DVC DAG that is
# already implied (`split` blocks first and `release` depends on its output),
# but running the module directly must refuse on its own.


def test_main_refuses_to_release_when_the_quality_gate_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    quality_report = tmp_path / "quality.json"
    quality_report.write_text(json.dumps({"overall_status": "fail"}), encoding="utf-8")
    history = tmp_path / "version_history.json"  # first release, nothing written yet
    output = tmp_path / "versions.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "versioning",
            "--coco",
            "unused-coco.json",
            "--quality-report",
            str(quality_report),
            "--m3-baseline",
            "unused-m3.json",
            "--observations",
            "unused-observations.json",
            "--policy",
            "unused-policy.yaml",
            "--dataset-version",
            "v1.0.0",
            "--history",
            str(history),
            "--output",
            str(output),
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    assert "Quality Gate failed" in capsys.readouterr().err
    assert not history.exists()
    assert not output.exists()
