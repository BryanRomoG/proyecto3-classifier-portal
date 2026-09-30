"""Check that a restored MLflow store (``dvc pull``) still holds the classifier evidence.

Stdlib only, against the MLflow REST API, so it runs on a clean clone that has just done
``dvc pull -r prod mlflow-data.dvc`` and ``docker compose up -d mlflow`` -- no torch, no
MLflow client, and no need for the DVC-generated manifest that ``list-runs`` reads.

Every expected value comes from the committed reports, never from this file:

* ``reports/classifier/selection.json`` -- the 10 ranked valid runs with their
  ``best_val_accuracy``, the selected run and its checkpoint SHA-256;
* ``reports/classifier/test_evaluation.json`` -- the final test metrics.

Checks: each ranked run exists, is FINISHED and has the same validation metric; the selected
run carries its selection tags; its ``model.pt`` downloads with exactly the recorded SHA-256;
its ``test_*`` metrics equal the committed evaluation. Read-only: nothing is written to MLflow.

    cd pipeline
    python scripts/verify_mlflow_restore.py --tracking-uri http://localhost:5000 \
        --report reports/classifier/mlflow_restore_check.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPORTS = Path(__file__).resolve().parents[1] / "reports" / "classifier"


def _get(base: str, endpoint: str, **query: str) -> bytes:
    url = f"{base.rstrip('/')}{endpoint}?{urllib.parse.urlencode(query)}"
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def _run(base: str, run_id: str) -> dict:
    try:
        run = json.loads(_get(base, "/api/2.0/mlflow/runs/get", run_id=run_id))["run"]
    except urllib.error.HTTPError:
        return {"status": "MISSING", "metrics": {}, "tags": {}}
    data = run["data"]
    return {
        "status": run["info"]["status"],
        "metrics": {m["key"]: m["value"] for m in data.get("metrics", [])},
        "tags": {t["key"]: t["value"] for t in data.get("tags", [])},
    }


def verify(base: str) -> dict:
    selection = json.loads((REPORTS / "selection.json").read_text(encoding="utf-8"))
    evaluation = json.loads((REPORTS / "test_evaluation.json").read_text(encoding="utf-8"))
    checks: dict[str, bool] = {}

    ranked = []
    for entry in selection["ranking"]:
        run = _run(base, entry["run_id"])
        ok = (
            run["status"] == "FINISHED"
            and run["metrics"].get("best_val_accuracy") == entry["best_val_accuracy"]
        )
        ranked.append({"run_id": entry["run_id"], "run_name": entry["run_name"], "ok": ok})
    checks["ten_ranked_runs_restored"] = len(ranked) == 10 and all(r["ok"] for r in ranked)

    selected = _run(base, selection["run_id"])
    checks["selected_run_tags"] = (
        selected["tags"].get("selected_candidate") == "true"
        and selected["tags"].get("selected_at") == selection["selected_at"]
        and selected["tags"].get("checkpoint_sha256") == selection["checkpoint_sha256"]
    )

    try:
        checkpoint = _get(base, "/get-artifact", path="model.pt", run_uuid=selection["run_id"])
    except urllib.error.HTTPError:
        checkpoint = b""
    checkpoint_sha256 = hashlib.sha256(checkpoint).hexdigest() if checkpoint else None
    checks["selected_checkpoint_sha256"] = checkpoint_sha256 == selection["checkpoint_sha256"]

    expected = {
        "test_total": evaluation["total"],
        "test_correct": evaluation["correct"],
        "test_accuracy": evaluation["accuracy"],
        "test_macro_f1": evaluation["macro_f1"],
    }
    checks["test_metrics_match_evaluation"] = all(
        selected["metrics"].get(key) == value for key, value in expected.items()
    )

    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "tracking_uri": base,
        "ranked_runs": ranked,
        "selected_run_id": selection["run_id"],
        "selected_checkpoint_sha256": checkpoint_sha256,
        "selected_checkpoint_bytes": len(checkpoint),
        "test_metrics": {key: selected["metrics"].get(key) for key in expected},
        "checks": checks,
        "passes": all(checks.values()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tracking-uri", default="http://localhost:5000")
    parser.add_argument("--report", type=Path, help="also write the JSON result here")
    args = parser.parse_args(argv)

    result = verify(args.tracking_uri)
    text = json.dumps(result, indent=2)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["passes"] else 1


if __name__ == "__main__":
    sys.exit(main())
