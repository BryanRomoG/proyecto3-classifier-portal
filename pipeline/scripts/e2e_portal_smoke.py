"""End-to-end smoke test of the classifier through the running portal (rubric 7.2).

Drives the real stack (``docker compose up``) only through the portal API, with traceable
IDs at every step:

1. release   -- GET  /training/releases, /training/provenance: the approved release, its
                quality gate and the 70/20/10 manifest the job will train on.
2. job       -- POST /training/jobs (1 short epoch) -> poll until completed -> MLflow run ID;
                GET /experiments/<run>/curves must serve that run's curves.
3. evaluation-- GET  /evaluation + /evaluation/predictions: accuracy recomputed from the
                per-sample predictions must equal the reported one.
4. publish   -- download the selected model through GET /models/<run>/download, build the
                release package and publish it to a TEST bucket in MinIO (never the prod
                bucket), then read it back with ``record_release`` (HeadObject per object).
5. inference -- select the short run's model, classify a test crop and check the answer
                came from that run; restore the previous model and check that crop gets the
                same label and confidence as test_predictions.csv.

Writes the IDs and checks to ``--report``. Exit code 0 only when every check passes.

    cd pipeline
    python scripts/e2e_portal_smoke.py --portal http://localhost:8080/api \\
        --report reports/classifier/e2e_portal_smoke.json
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE / "src"))

SHORT_JOB = {
    "optimizer": "adam",
    "batchSize": 32,
    "epochs": 1,
    "learningRate": 0.0003,
    "imageSize": 96,
    "hiddenLayers": [256],
    "dropout": 0.3,
}


class Portal:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")

    def request(self, method: str, path: str, body: object | None = None) -> tuple[int, bytes]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data is not None else {},
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def json(self, method: str, path: str, body: object | None = None) -> tuple[int, object]:
        status, raw = self.request(method, path, body)
        return status, json.loads(raw) if raw else None


def _minio_store(endpoint: str, bucket: str):
    import boto3

    from dataset_quality.storage.object_store import ObjectStore

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id="minioadmin",
        aws_secret_access_key="minioadmin",
        region_name="us-east-1",
    )
    try:
        client.head_bucket(Bucket=bucket)
    except Exception:
        client.create_bucket(Bucket=bucket)
    return ObjectStore(bucket=bucket, client=client)


def run(portal: Portal, *, minio: str, bucket: str, timeout: float) -> dict:
    checks: dict[str, bool] = {}
    report: dict[str, object] = {"started_at": datetime.now(UTC).isoformat()}

    # 1. release -------------------------------------------------------------------------
    _, releases = portal.json("GET", "/training/releases")
    trainable = [r for r in releases["releases"] if r["trainable"]]
    _, provenance = portal.json("GET", "/training/provenance")
    report["release"] = {
        "dataset_version": trainable[0]["version"] if trainable else None,
        "quality_gate_status": provenance["quality_gate_status"],
        "manifest_sha256": provenance["manifest_sha256"],
        "dvc_raw_md5": provenance["dvc_raw_md5"],
    }
    checks["approved_release_with_manifest"] = bool(trainable)
    checks["quality_gate_pass"] = provenance["quality_gate_status"] == "pass"

    # 2. short training job --------------------------------------------------------------
    status, created = portal.json(
        "POST", "/training/jobs", {**SHORT_JOB, "datasetVersion": trainable[0]["version"]}
    )
    checks["job_accepted"] = status == 202
    job_id = created["id"]
    deadline = time.monotonic() + timeout
    job: dict = {}
    while time.monotonic() < deadline:
        _, job = portal.json("GET", f"/training/jobs/{job_id}")
        if job["status"] in ("completed", "failed"):
            break
        time.sleep(5)
    run_id = job.get("mlflowRunId")
    report["job"] = {
        "job_id": job_id,
        "trainer_job_id": job.get("trainerJobId"),
        "status": job.get("status"),
        "mlflow_run_id": run_id,
        "error": job.get("errorMessage"),
        "dataset_version": job.get("datasetVersion"),
        "manifest_sha256": job.get("manifestSha256"),
    }
    checks["job_completed"] = job.get("status") == "completed"
    checks["job_on_the_checked_manifest"] = (
        job.get("manifestSha256") == provenance["manifest_sha256"]
    )
    if run_id:
        status, curves = portal.request("GET", f"/experiments/{run_id}/curves")
        checks["run_curves_served"] = status == 200 and curves[:4] == b"\x89PNG"

    # 3. evaluation ----------------------------------------------------------------------
    _, evaluation = portal.json("GET", "/evaluation")
    _, predictions = portal.json("GET", "/evaluation/predictions")
    rows = predictions["predictions"]
    recomputed = sum(row["correct"] for row in rows) / len(rows)
    reported = evaluation["evaluation"]["accuracy"]
    selected_run = evaluation["selection"]["runId"]
    report["evaluation"] = {
        "selected_run_id": selected_run,
        "reported_accuracy": reported,
        "recomputed_accuracy": recomputed,
        "test_crops": len(rows),
    }
    checks["accuracy_recomputed_from_predictions"] = recomputed == reported

    # 4. test publication to MinIO -------------------------------------------------------
    from dataset_quality.classifier.release import build_package, record_release, upload_package

    status, model_bytes = portal.request("GET", f"/models/{selected_run}/download")
    checks["selected_model_downloaded"] = status == 200 and len(model_bytes) > 0
    with tempfile.TemporaryDirectory() as tmp:
        checkpoint = Path(tmp) / "model.pt"
        checkpoint.write_bytes(model_bytes)
        package = build_package(
            checkpoint=checkpoint,
            version="v0.0.1",
            selection_path=PIPELINE / "reports/classifier/selection.json",
            evaluation_path=PIPELINE / "reports/classifier/test_evaluation.json",
            output_dir=Path(tmp) / "release",
            manifest_path=PIPELINE / "data/processed/classifier_split_manifest.json",
            requirements_path=PIPELINE / "requirements-train.txt",
        )
        store = _minio_store(minio, bucket)
        upload_package(store=store, package_dir=Path(package["package_dir"]), version="v0.0.1")
        record = record_release(
            store=store, version="v0.0.1", recorded_at=datetime.now(UTC).isoformat()
        )
    report["publication"] = {
        "store": f"minio {minio}",
        "s3_uri": record["s3_uri"],
        "run_id": record["run_id"],
        "model_sha256": record["objects"]["model.pt"]["sha256"],
        "objects": len(record["objects"]),
    }
    checks["published_package_traces_to_selected_run"] = record["run_id"] == selected_run
    checks["published_model_sha256_is_selected_checkpoint"] = (
        record["objects"]["model.pt"]["sha256"] == record["checkpoint_sha256"]
    )

    # 5. inference from the portal -------------------------------------------------------
    crop = next(row for row in rows if not row["correct"])
    status, previous = portal.json("GET", "/models/selected")
    previous_run = previous["runId"] if status == 200 else selected_run
    inference: dict = {}
    if run_id:
        portal.json("POST", f"/models/{run_id}/select", {})
        _, inference = portal.json(
            "POST", "/inference/crop", {"annotationId": crop["annotationId"]}
        )
        checks["inference_used_the_short_run"] = inference["model"]["runId"] == run_id
        checks["probabilities_sum_to_one"] = (
            abs(sum(inference["probabilities"].values()) - 1.0) < 1e-4
        )
    portal.json("POST", f"/models/{previous_run}/select", {})
    _, restored = portal.json("POST", "/inference/crop", {"annotationId": crop["annotationId"]})
    expected = crop["predictedLabel"]
    checks["restored_model_matches_predictions_csv"] = (
        restored["model"]["runId"] == previous_run
        and restored["predictedClass"] == expected
        and abs(restored["confidence"] - crop["confidence"]) < 1e-3
    )
    report["inference"] = {
        "annotation_id": crop["annotationId"],
        "short_run": {"run_id": run_id, "predicted": inference.get("predictedClass")},
        "restored_model": {
            "run_id": restored["model"]["runId"],
            "predicted": restored["predictedClass"],
            "confidence": restored["confidence"],
            "csv_predicted": expected,
            "csv_confidence": crop["confidence"],
        },
    }

    report["checks"] = checks
    report["passes"] = all(checks.values())
    report["finished_at"] = datetime.now(UTC).isoformat()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--portal", default="http://localhost:8080/api")
    parser.add_argument("--minio", default="http://localhost:9000")
    parser.add_argument("--bucket", default="t3-classifier-e2e")
    parser.add_argument("--timeout", type=float, default=900.0, help="seconds for the job")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    report = run(Portal(args.portal), minio=args.minio, bucket=args.bucket, timeout=args.timeout)
    text = json.dumps(report, indent=2)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if report["passes"] else 1


if __name__ == "__main__":
    sys.exit(main())
