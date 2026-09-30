"""Where a run's data came from: DVC release -> quality gate -> 70/20/10 manifest (M2).

Everything here is read from versioned files, never typed in by hand: the DVC pointer of
the raw COCO file (its md5), the quality report the crops were gated on, and the manifest's
own SHA-256 plus the provenance hashes it already carries.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from dataset_quality.classifier.data import LoadedManifest

DVC_POINTER = Path("data/raw/coco-dataset.json.dvc")
QUALITY_REPORT = Path("data/interim/quality.json")


def dataset_lineage(loaded: LoadedManifest, pipeline_root: Path) -> dict[str, str]:
    manifest = loaded.manifest
    lineage = {
        "dataset_version": manifest.dataset_version,
        "manifest_file": loaded.path.name,
        "manifest_sha256": loaded.sha256,
        "manifest_seed": str(manifest.seed),
        "manifest_proportions": (
            f"{manifest.proportions.train}/{manifest.proportions.val}/{manifest.proportions.test}"
        ),
        "coco_sha256": manifest.provenance.coco_sha256,
        "crops_manifest_sha256": manifest.provenance.crops_manifest_sha256,
        "duplicate_pairs_sha256": manifest.provenance.duplicate_pairs_sha256,
        "dvc_raw_md5": "unknown",
        "quality_gate_status": "unknown",
        "quality_gate_dataset_version": "unknown",
    }

    pointer = pipeline_root / DVC_POINTER
    if pointer.is_file():
        outs = (yaml.safe_load(pointer.read_text(encoding="utf-8")) or {}).get("outs") or []
        if outs and outs[0].get("md5"):
            lineage["dvc_raw_md5"] = str(outs[0]["md5"])

    report = pipeline_root / QUALITY_REPORT
    if report.is_file():
        payload = json.loads(report.read_text(encoding="utf-8"))
        lineage["quality_gate_status"] = str(payload.get("overall_status", "unknown"))
        lineage["quality_gate_dataset_version"] = str(payload.get("dataset_version", "unknown"))
    return lineage
