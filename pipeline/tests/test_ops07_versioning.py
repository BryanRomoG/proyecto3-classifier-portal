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
# For a version *older* than the ledger's last one (or for a first release that
# isn't v1.0.0), `main()` raises before it ever reads --coco/--quality-report/
# --m3-baseline/--observations/--policy, so those can stay as placeholder
# (non-existent) paths in these tests — the ValueError fires first. Only
# --history's content matters here. A *repeated* version does read them, because
# telling "the same release again" apart from "different content under a taken
# version" requires the real inputs — those cases live in the release-identity
# section at the end of this file.


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


def test_main_rejects_a_dataset_version_lower_than_the_last_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history = _existing_release_history(tmp_path, version="v1.0.0")

    with pytest.raises(ValueError, match="must be strictly greater"):
        _run_main(monkeypatch, dataset_version="v0.9.0", history=history)

    # A *repeated* version is no longer rejected outright: it is an idempotent
    # no-op when the release is identical, and an explicit error when it is not
    # — see the release-identity section at the end of this file.


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


# --- main()'s release-identity guard: idempotent re-release vs. overwrite ----
#
# Re-stamping a version that is already in the ledger is safe *only* when it is
# literally the same release — same `content_hash`, `snapshot` and
# `quality_status`. That is the `dvc repro` case where the `release` stage re-runs
# because one of its deps changed while the dataset did not: a no-op on the
# ledger that still regenerates `versions.json`, so the stage exits 0 instead of
# failing the pipeline on a version nobody bumped. The same version over
# *different* content is exactly what the ledger exists to prevent, so it raises.
# Unlike `_run_main` above, these tests need real inputs — the identity check
# has to read them.


def _release_inputs(
    tmp_path: Path,
    *,
    coco_text: str = '{"images": [], "annotations": [], "categories": []}',
    quality_status: str = "pass",
    image_count: int = 311,
    box_count: int = 1038,
    per_class_counts: dict[str, int] | None = None,
    small_object_percentage: float = 1.35,
) -> dict[str, Path]:
    """Write real (tiny) release inputs to `tmp_path` under fixed file names."""
    files = {
        "coco": tmp_path / "coco.json",
        "quality_report": tmp_path / "quality.json",
        "m3_baseline": tmp_path / "m3_baseline.json",
        "observations": tmp_path / "observations.json",
    }
    classes = per_class_counts or {"person": 311, "car": 309}
    files["coco"].write_text(coco_text, encoding="utf-8")
    files["quality_report"].write_text(
        json.dumps({"overall_status": quality_status}), encoding="utf-8"
    )
    files["m3_baseline"].write_text(
        json.dumps(
            {
                "total_images": image_count,
                "total_annotations": box_count,
                "classes": [
                    {"category": category, "distinct_images_with_valid_box": count}
                    for category, count in classes.items()
                ],
            }
        ),
        encoding="utf-8",
    )
    files["observations"].write_text(
        json.dumps({"small_objects": small_object_percentage}), encoding="utf-8"
    )
    return files


def _run_release(
    monkeypatch: pytest.MonkeyPatch,
    *,
    dataset_version: str,
    history: Path,
    output: Path,
    inputs: dict[str, Path],
) -> None:
    """Run `main()` for real: real input files, the repo's own `quality.yaml` policy."""
    monkeypatch.setattr(
        "sys.argv",
        [
            "versioning",
            "--coco",
            str(inputs["coco"]),
            "--quality-report",
            str(inputs["quality_report"]),
            "--m3-baseline",
            str(inputs["m3_baseline"]),
            "--observations",
            str(inputs["observations"]),
            "--policy",
            str(Path(__file__).resolve().parents[1] / "quality.yaml"),
            "--dataset-version",
            dataset_version,
            "--history",
            str(history),
            "--output",
            str(output),
        ],
    )
    main()


def _recorded_versions(history: Path) -> list[str]:
    payload = json.loads(history.read_text(encoding="utf-8"))
    return [entry["entry"]["version"] for entry in payload["entries"]]


def test_main_same_version_same_release_is_an_idempotent_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    history = tmp_path / "version_history.json"
    output = tmp_path / "versions.json"
    inputs = _release_inputs(tmp_path)

    _run_release(
        monkeypatch,
        dataset_version="v1.0.0",
        history=history,
        output=output,
        inputs=inputs,
    )
    ledger_after_first_release = history.read_text(encoding="utf-8")
    output_after_first_release = output.read_text(encoding="utf-8")
    capsys.readouterr()  # drop the first run's stdout/stderr

    # The derived artifact is gone: stamping the same release again has to
    # succeed, append nothing, and regenerate versions.json from the ledger.
    output.unlink()
    _run_release(
        monkeypatch,
        dataset_version="v1.0.0",
        history=history,
        output=output,
        inputs=inputs,
    )
    stderr = capsys.readouterr().err

    assert _recorded_versions(history) == ["v1.0.0"]
    # Byte-for-byte unchanged — `released_at` included, not just "still one entry".
    assert history.read_text(encoding="utf-8") == ledger_after_first_release
    assert output.read_text(encoding="utf-8") == output_after_first_release
    assert "already recorded" in stderr


def test_main_same_version_with_different_content_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history = tmp_path / "version_history.json"
    output = tmp_path / "versions.json"

    _run_release(
        monkeypatch,
        dataset_version="v1.0.0",
        history=history,
        output=output,
        inputs=_release_inputs(tmp_path),
    )
    recorded_ledger = history.read_text(encoding="utf-8")
    recorded_output = output.read_text(encoding="utf-8")

    # Same version, same COCO bytes, different snapshot.
    with pytest.raises(ValueError, match="snapshot"):
        _run_release(
            monkeypatch,
            dataset_version="v1.0.0",
            history=history,
            output=output,
            inputs=_release_inputs(tmp_path, per_class_counts={"person": 311, "car": 305}),
        )

    # Same version, same snapshot, different COCO bytes.
    with pytest.raises(ValueError, match="content_hash"):
        _run_release(
            monkeypatch,
            dataset_version="v1.0.0",
            history=history,
            output=output,
            inputs=_release_inputs(tmp_path, coco_text='{"images": [], "annotations": []}'),
        )

    # Same version, same bytes and snapshot, a different Quality Gate status.
    with pytest.raises(ValueError, match="quality_status"):
        _run_release(
            monkeypatch,
            dataset_version="v1.0.0",
            history=history,
            output=output,
            inputs=_release_inputs(tmp_path, quality_status="warn"),
        )

    # None of the three rejected re-releases touched the ledger or the artifact.
    assert history.read_text(encoding="utf-8") == recorded_ledger
    assert output.read_text(encoding="utf-8") == recorded_output


def test_main_higher_version_appends_exactly_one_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history = tmp_path / "version_history.json"
    output = tmp_path / "versions.json"
    inputs = _release_inputs(tmp_path)

    _run_release(
        monkeypatch,
        dataset_version="v1.0.0",
        history=history,
        output=output,
        inputs=inputs,
    )
    first_entry = json.loads(history.read_text(encoding="utf-8"))["entries"][0]

    # Same inputs, bumped version: the idempotency rule must not swallow a real
    # release — exactly one entry is appended and the earlier one is untouched.
    _run_release(
        monkeypatch,
        dataset_version="v1.1.0",
        history=history,
        output=output,
        inputs=inputs,
    )
    entries = json.loads(history.read_text(encoding="utf-8"))["entries"]

    assert [entry["entry"]["version"] for entry in entries] == ["v1.0.0", "v1.1.0"]
    assert entries[0] == first_entry
    assert entries[0]["entry"]["diff_from_previous"] is None
    assert entries[1]["entry"]["diff_from_previous"] == {
        "images_added": 0,
        "boxes_added": 0,
        "classes_left_minimum": [],
        "small_object_ratio_change_pct": 0.0,
    }
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["current_version"] == "v1.1.0"
    assert [version["version"] for version in report["versions"]] == [
        "v1.0.0",
        "v1.1.0",
    ]
