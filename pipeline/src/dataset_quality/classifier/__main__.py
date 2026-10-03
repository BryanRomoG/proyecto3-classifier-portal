"""CLI for the T3 classifier: validate, train, run the grid, select, evaluate, predict.

Run from ``pipeline/`` with ``PYTHONPATH=src``. MLflow's destination comes from the
standard ``MLFLOW_TRACKING_URI`` (default ``sqlite:///mlflow.db`` in this directory).

    python -m dataset_quality.classifier validate-config --json '{"batch_size": 0}'
    python -m dataset_quality.classifier train --config cfg.json
    python -m dataset_quality.classifier grid-check
    python -m dataset_quality.classifier run-grid
    python -m dataset_quality.classifier list-runs
    python -m dataset_quality.classifier audit-selection
    python -m dataset_quality.classifier repro-check RUN_A RUN_B   (or --train --json '{...}')
    python -m dataset_quality.classifier audit-test
    python -m dataset_quality.classifier export-runs
    python -m dataset_quality.classifier select
    python -m dataset_quality.classifier evaluate --confirm-final-test
    python -m dataset_quality.classifier evaluate --audit
    python -m dataset_quality.classifier recompute
    python -m dataset_quality.classifier predict --checkpoint model.pt img.png
    python -m dataset_quality.classifier serve --port 8200
    python -m dataset_quality.classifier serve-inference --port 8300
    python -m dataset_quality.classifier serve-jobs --port 8400
    python -m dataset_quality.classifier release-build --version v1.0.0 --checkpoint model.pt
    python -m dataset_quality.classifier release-upload --version v1.0.0 --bucket <releases-bucket>
    python -m dataset_quality.classifier release-fetch --version v1.0.0 --bucket <releases-bucket>
    python -m dataset_quality.classifier release-verify --package-dir <package dir>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_TRACKING_URI = "sqlite:///mlflow.db"
DEFAULT_MANIFEST = Path("data/processed/classifier_split_manifest.json")
DEFAULT_GRID = Path("experiments/classifier_grid.yaml")
DEFAULT_POLICY = Path("experiments/selection_policy.yaml")
DEFAULT_RUNS_DIR = Path("artifacts/classifier/runs")
DEFAULT_SELECTED_DIR = Path("artifacts/classifier/selected")
DEFAULT_REPORT_DIR = Path("reports/classifier")
DEFAULT_RELEASE_DIR = Path("artifacts/classifier/release")
DEFAULT_RELEASE_PREFIX = "t3-classifier"
REPRO_EXPERIMENT = "t3-smoke-repro"

EXIT_INVALID = 2


def _print(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _config_payload(args: argparse.Namespace) -> object:
    if args.json is not None:
        return json.loads(args.json)
    if args.config is not None:
        return json.loads(Path(args.config).read_text(encoding="utf-8"))
    return {}


def cmd_schema(_: argparse.Namespace) -> int:
    from dataset_quality.classifier.config import json_schema

    _print(json_schema())
    return 0


def cmd_validate_config(args: argparse.Namespace) -> int:
    from dataset_quality.classifier.config import validation_errors

    errors = validation_errors(_config_payload(args))
    _print({"valid": not errors, "errors": errors})
    return EXIT_INVALID if errors else 0


def cmd_train(args: argparse.Namespace) -> int:
    from dataset_quality.classifier.config import TrainingConfig, validation_errors

    payload = _config_payload(args)
    errors = validation_errors(payload)
    if errors:
        _print({"valid": False, "errors": errors})
        return EXIT_INVALID

    from dataset_quality.classifier.training import train

    outcome = train(
        TrainingConfig.model_validate(payload),
        manifest_path=args.manifest,
        data_root=args.data_root,
        output_root=args.runs_dir,
        pipeline_root=Path.cwd(),
        experiment_name=args.experiment,
        run_name=args.run_name,
        device=args.device,
        on_epoch=lambda epoch, m: print(f"[train] epoch {epoch}: {m}", file=sys.stderr),
    )
    _print(outcome.__dict__)
    return 0


def cmd_grid_check(args: argparse.Namespace) -> int:
    from dataset_quality.classifier.experiments import GridError, coverage, load_grid

    try:
        grid = load_grid(args.grid)
    except GridError as error:
        _print({"valid": False, "errors": str(error).split("; ")})
        return EXIT_INVALID
    _print(
        {
            "valid": True,
            "experiment_name": grid.experiment_name,
            "runs": [run.name for run in grid.runs],
            "coverage": coverage([run.config for run in grid.runs]),
            "sha256": grid.sha256,
        }
    )
    return 0


def cmd_run_grid(args: argparse.Namespace) -> int:
    from mlflow.tracking import MlflowClient

    from dataset_quality.classifier.data import class_names_from_manifest, load_manifest
    from dataset_quality.classifier.experiments import load_grid, valid_runs
    from dataset_quality.classifier.training import train

    grid = load_grid(args.grid)
    loaded = load_manifest(args.manifest)
    classes = class_names_from_manifest(loaded.manifest)
    done = {
        row["grid_run"]
        for row in valid_runs(MlflowClient(), grid.experiment_name, loaded.sha256, classes)
        if row["valid"]
    }
    for run in grid.runs:
        if args.only and run.name not in args.only:
            continue
        if run.name in done and not args.rerun:
            print(f"[run-grid] {run.name}: already has a valid run, skipping", file=sys.stderr)
            continue
        print(f"[run-grid] {run.name}: training", file=sys.stderr)
        outcome = train(
            run.config,
            manifest_path=args.manifest,
            data_root=args.data_root,
            output_root=args.runs_dir,
            pipeline_root=Path.cwd(),
            experiment_name=grid.experiment_name,
            run_name=run.name,
            tags={"grid_run": run.name, "grid_file": grid.path.name, "grid_sha256": grid.sha256},
            on_epoch=lambda e, m, n=run.name: print(f"[{n}] epoch {e}: {m}", file=sys.stderr),
            device=args.device,
        )
        print(
            f"[run-grid] {run.name}: run {outcome.run_id} best epoch {outcome.best_epoch} "
            f"val_acc {outcome.best_val_accuracy:.4f}",
            file=sys.stderr,
        )
    return cmd_list_runs(args, experiment=grid.experiment_name)


def cmd_list_runs(args: argparse.Namespace, experiment: str | None = None) -> int:
    from mlflow.tracking import MlflowClient

    from dataset_quality.classifier.audit import audit_runs
    from dataset_quality.classifier.data import class_names_from_manifest, load_manifest

    loaded = load_manifest(args.manifest)
    classes = class_names_from_manifest(loaded.manifest)
    audit = audit_runs(MlflowClient(), experiment or args.experiment, loaded.sha256, classes)
    _print(audit)
    return 0 if audit["meets_rubric"] else 1


def cmd_audit_selection(args: argparse.Namespace) -> int:
    from mlflow.tracking import MlflowClient

    from dataset_quality.classifier.audit import audit_selection
    from dataset_quality.classifier.data import class_names_from_manifest, load_manifest

    loaded = load_manifest(args.manifest)
    audit = audit_selection(
        MlflowClient(),
        report_dir=args.report_dir,
        policy_path=args.policy,
        experiment_name=args.experiment,
        manifest_sha256=loaded.sha256,
        classes=class_names_from_manifest(loaded.manifest),
    )
    _print(audit)
    return 0 if audit["passes"] else 1


def cmd_repro_check(args: argparse.Namespace) -> int:
    from mlflow.tracking import MlflowClient

    from dataset_quality.classifier.audit import compare_runs

    if args.train:
        if args.experiment != REPRO_EXPERIMENT:
            print(
                f"[repro-check] --train only logs to {REPRO_EXPERIMENT!r}, never to the "
                "official experiment",
                file=sys.stderr,
            )
            return EXIT_INVALID
        from dataset_quality.classifier.config import TrainingConfig, validation_errors
        from dataset_quality.classifier.training import train

        payload = _config_payload(args)
        errors = validation_errors(payload)
        if errors:
            _print({"valid": False, "errors": errors})
            return EXIT_INVALID
        run_ids = [
            train(
                TrainingConfig.model_validate(payload),
                manifest_path=args.manifest,
                data_root=args.data_root,
                output_root=args.runs_dir,
                pipeline_root=Path.cwd(),
                experiment_name=args.experiment,
                run_name=f"repro-check-{label}",
                device=args.device,
            ).run_id
            for label in ("a", "b")
        ]
    elif args.runs and len(args.runs) == 2:
        run_ids = args.runs
    else:
        print("[repro-check] give two run IDs, or --train", file=sys.stderr)
        return EXIT_INVALID

    result = compare_runs(MlflowClient(), *run_ids, tolerance=args.tolerance)
    if args.report:
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    _print(result)
    return 0 if result["reproducible"] else 1


def cmd_audit_test(args: argparse.Namespace) -> int:
    from dataset_quality.classifier.audit import audit_test_predictions

    client = None
    if not args.no_mlflow:
        from mlflow.tracking import MlflowClient

        client = MlflowClient()
    audit = audit_test_predictions(
        report_dir=args.report_dir, manifest_path=args.manifest, client=client
    )
    _print(audit)
    return 0 if audit["matches"] else 1


def cmd_export_runs(args: argparse.Namespace) -> int:
    from dataset_quality.classifier.data import class_names_from_manifest, load_manifest
    from dataset_quality.classifier.export import export_runs

    loaded = load_manifest(args.manifest)
    snapshot = export_runs(
        experiments=args.experiments or [args.experiment],
        manifest_sha256=loaded.sha256,
        classes=class_names_from_manifest(loaded.manifest),
        report_dir=args.report_dir,
    )
    _print(
        {
            e["name"]: {"runs": e["runs"], "valid_runs": e["valid_runs"]}
            for e in snapshot["experiments"]
        }
    )
    return 0


def cmd_select(args: argparse.Namespace) -> int:
    from dataset_quality.classifier.data import class_names_from_manifest, load_manifest
    from dataset_quality.classifier.selection import SelectionError, select_candidate

    loaded = load_manifest(args.manifest)
    try:
        selection = select_candidate(
            policy_path=args.policy,
            experiment_name=args.experiment,
            manifest_sha256=loaded.sha256,
            classes=class_names_from_manifest(loaded.manifest),
            report_dir=args.report_dir,
            artifact_dir=args.selected_dir,
        )
    except SelectionError as error:
        print(f"[select] {error}", file=sys.stderr)
        return 1
    _print(selection)
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    from dataset_quality.classifier.evaluation import EvaluationError, evaluate_test

    if not args.audit and not args.confirm_final_test:
        print(
            "[evaluate] this opens the frozen test split ONCE for the selected candidate. "
            "Re-run with --confirm-final-test (or --audit to recompute an existing result).",
            file=sys.stderr,
        )
        return EXIT_INVALID
    selection = json.loads((args.report_dir / "selection.json").read_text(encoding="utf-8"))
    checkpoint = args.checkpoint or args.selected_dir / selection["run_id"] / "model.pt"
    try:
        result = evaluate_test(
            report_dir=args.report_dir,
            checkpoint=checkpoint,
            manifest_path=args.manifest,
            data_root=args.data_root,
            audit=args.audit,
        )
    except EvaluationError as error:
        print(f"[evaluate] {error}", file=sys.stderr)
        return 1
    if not args.audit:
        result = {k: v for k, v in result.items() if k != "examples"}
    _print(result)
    return 0 if not args.audit or result["matches"] else 1


def cmd_recompute(args: argparse.Namespace) -> int:
    from dataset_quality.classifier.metrics import meets_threshold, metrics_from_predictions_csv

    metrics = metrics_from_predictions_csv(args.report_dir / "test_predictions.csv")
    metrics["meets_target_0.85"] = meets_threshold(metrics["correct"], metrics["total"])
    _print(metrics)
    return 0


def cmd_predict(args: argparse.Namespace) -> int:
    from dataset_quality.classifier.predict import load_checkpoint, predict_paths

    classifier = load_checkpoint(args.checkpoint)
    predictions = predict_paths(classifier, args.images)
    _print(
        [
            {"image": str(path), **prediction.__dict__}
            for path, prediction in zip(args.images, predictions, strict=True)
        ]
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from dataset_quality.classifier.http_app import build_app

    uvicorn.run(build_app(), host=args.host, port=args.port)
    return 0


def cmd_serve_inference(args: argparse.Namespace) -> int:
    import uvicorn

    from dataset_quality.classifier.inference_http import build_inference_app

    uvicorn.run(build_inference_app(), host=args.host, port=args.port)
    return 0


def cmd_serve_jobs(args: argparse.Namespace) -> int:
    import uvicorn

    from dataset_quality.classifier.jobs_app import build_app

    uvicorn.run(build_app(), host=args.host, port=args.port)
    return 0


def cmd_release_build(args: argparse.Namespace) -> int:
    from dataset_quality.classifier.release import ReleaseError, build_package

    try:
        result = build_package(
            checkpoint=args.checkpoint,
            version=args.version,
            selection_path=args.selection,
            evaluation_path=args.evaluation,
            output_dir=args.output_dir,
            manifest_path=args.manifest if args.manifest.is_file() else None,
            requirements_path=args.requirements if args.requirements.is_file() else None,
        )
    except ReleaseError as error:
        print(f"[release-build] {error}", file=sys.stderr)
        return EXIT_INVALID
    _print(result)
    return 0


def cmd_release_verify(args: argparse.Namespace) -> int:
    from dataset_quality.classifier.release import verify_package

    result = verify_package(args.package_dir)
    _print(result)
    return 0 if result["ok"] else EXIT_INVALID


def cmd_release_upload(args: argparse.Namespace) -> int:
    from dataset_quality.classifier.release import ReleaseError, release_store, upload_package

    store = release_store(args.bucket, args.region)
    try:
        result = upload_package(
            store=store,
            package_dir=args.package_dir,
            version=args.version,
            prefix=args.prefix,
        )
    except ReleaseError as error:
        print(f"[release-upload] {error}", file=sys.stderr)
        return EXIT_INVALID
    _print(result)
    return 0


def cmd_release_record(args: argparse.Namespace) -> int:
    from datetime import UTC, datetime

    from dataset_quality.classifier.release import ReleaseError, record_release, release_store

    store = release_store(args.bucket, args.region)
    try:
        record = record_release(
            store=store,
            version=args.version,
            prefix=args.prefix,
            recorded_at=datetime.now(UTC).isoformat(),
        )
    except ReleaseError as error:
        print(f"[release-record] {error}", file=sys.stderr)
        return EXIT_INVALID
    args.output_dir.mkdir(parents=True, exist_ok=True)
    target = args.output_dir / f"{args.version}.json"
    target.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    _print({k: v for k, v in record.items() if k != "card_markdown"})
    return 0


def cmd_release_fetch(args: argparse.Namespace) -> int:
    from dataset_quality.classifier.release import fetch_package, release_store

    store = release_store(args.bucket, args.region)
    result = fetch_package(
        store=store,
        version=args.version,
        destination=args.destination,
        prefix=args.prefix,
    )
    if not result["ok"]:
        print(f"[release-fetch] integrity check failed for {args.destination}", file=sys.stderr)
    _print(result)
    return 0 if result["ok"] else EXIT_INVALID


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m dataset_quality.classifier")
    commands = parser.add_subparsers(dest="command", required=True)

    def common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
        sub.add_argument("--data-root", type=Path, default=Path("."))
        sub.add_argument("--experiment", default="t3-classifier")
        sub.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
        sub.add_argument("--selected-dir", type=Path, default=DEFAULT_SELECTED_DIR)
        sub.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)

    commands.add_parser("schema").set_defaults(handler=cmd_schema)

    for name, handler in (("validate-config", cmd_validate_config), ("train", cmd_train)):
        sub = commands.add_parser(name)
        group = sub.add_mutually_exclusive_group()
        group.add_argument("--config", type=Path)
        group.add_argument("--json")
        sub.add_argument("--run-name")
        sub.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
        common(sub)
        sub.set_defaults(handler=handler)

    sub = commands.add_parser("grid-check")
    sub.add_argument("--grid", type=Path, default=DEFAULT_GRID)
    sub.set_defaults(handler=cmd_grid_check)

    sub = commands.add_parser("run-grid")
    sub.add_argument("--grid", type=Path, default=DEFAULT_GRID)
    sub.add_argument("--only", nargs="*")
    sub.add_argument("--rerun", action="store_true")
    sub.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    common(sub)
    sub.set_defaults(handler=cmd_run_grid)

    sub = commands.add_parser("list-runs")
    common(sub)
    sub.set_defaults(handler=cmd_list_runs)

    sub = commands.add_parser("audit-selection")
    sub.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    common(sub)
    sub.set_defaults(handler=cmd_audit_selection)

    sub = commands.add_parser("repro-check")
    sub.add_argument("runs", nargs="*", help="two MLflow run IDs to compare")
    sub.add_argument("--train", action="store_true", help="train two short runs, then compare")
    group = sub.add_mutually_exclusive_group()
    group.add_argument("--config", type=Path)
    group.add_argument("--json")
    sub.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    sub.add_argument("--tolerance", type=float, default=1e-6)
    sub.add_argument("--report", type=Path)
    common(sub)
    # Short repeat runs never go into the official experiment: they would change its counts.
    sub.set_defaults(handler=cmd_repro_check, experiment=REPRO_EXPERIMENT)

    sub = commands.add_parser("audit-test")
    sub.add_argument("--no-mlflow", action="store_true", help="skip the MLflow comparison")
    common(sub)
    sub.set_defaults(handler=cmd_audit_test)

    sub = commands.add_parser("export-runs")
    sub.add_argument("--experiments", nargs="*", help="default: --experiment")
    common(sub)
    sub.set_defaults(handler=cmd_export_runs)

    sub = commands.add_parser("select")
    sub.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    common(sub)
    sub.set_defaults(handler=cmd_select)

    sub = commands.add_parser("evaluate")
    sub.add_argument("--checkpoint", type=Path)
    sub.add_argument("--audit", action="store_true")
    sub.add_argument("--confirm-final-test", action="store_true")
    common(sub)
    sub.set_defaults(handler=cmd_evaluate)

    sub = commands.add_parser("recompute")
    sub.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    sub.set_defaults(handler=cmd_recompute)

    sub = commands.add_parser("predict")
    sub.add_argument("--checkpoint", type=Path, required=True)
    sub.add_argument("images", type=Path, nargs="+")
    sub.set_defaults(handler=cmd_predict)

    sub = commands.add_parser("serve")
    sub.add_argument("--host", default="0.0.0.0")
    sub.add_argument("--port", type=int, default=int(os.environ.get("CLASSIFIER_API_PORT", 8200)))
    sub.set_defaults(handler=cmd_serve)

    sub = commands.add_parser("serve-inference")
    sub.add_argument("--host", default="0.0.0.0")
    sub.add_argument(
        "--port", type=int, default=int(os.environ.get("CLASSIFIER_INFERENCE_PORT", 8300))
    )
    sub.set_defaults(handler=cmd_serve_inference)

    sub = commands.add_parser("serve-jobs")
    sub.add_argument("--host", default="0.0.0.0")
    sub.add_argument("--port", type=int, default=int(os.environ.get("CLASSIFIER_JOBS_PORT", 8400)))
    sub.set_defaults(handler=cmd_serve_jobs)

    sub = commands.add_parser("release-build")
    sub.add_argument("--checkpoint", type=Path, required=True, help="path to the selected model.pt")
    sub.add_argument("--version", required=True, help="semantic version, e.g. v1.0.0")
    sub.add_argument("--selection", type=Path, default=DEFAULT_REPORT_DIR / "selection.json")
    sub.add_argument("--evaluation", type=Path, default=DEFAULT_REPORT_DIR / "test_evaluation.json")
    sub.add_argument("--output-dir", type=Path, default=DEFAULT_RELEASE_DIR)
    sub.add_argument(
        "--manifest", type=Path, default=DEFAULT_MANIFEST, help="70/20/10 manifest (split table)"
    )
    sub.add_argument(
        "--requirements",
        type=Path,
        default=Path("requirements-train.txt"),
        help="pinned ML extras declared as the package dependencies",
    )
    sub.set_defaults(handler=cmd_release_build)

    sub = commands.add_parser("release-verify")
    sub.add_argument("--package-dir", type=Path, required=True)
    sub.set_defaults(handler=cmd_release_verify)

    sub = commands.add_parser("release-upload")
    sub.add_argument("--package-dir", type=Path, required=True)
    sub.add_argument("--version", required=True)
    sub.add_argument(
        "--bucket", required=True, help="releases bucket, e.g. dataset-releases-prod-…"
    )
    sub.add_argument("--prefix", default=DEFAULT_RELEASE_PREFIX)
    sub.add_argument("--region", default=None)
    sub.set_defaults(handler=cmd_release_upload)

    sub = commands.add_parser("release-record")
    sub.add_argument("--version", required=True)
    sub.add_argument("--bucket", required=True)
    sub.add_argument("--prefix", default=DEFAULT_RELEASE_PREFIX)
    sub.add_argument("--region", default=None)
    sub.add_argument("--output-dir", type=Path, default=DEFAULT_REPORT_DIR / "releases")
    sub.set_defaults(handler=cmd_release_record)

    sub = commands.add_parser("release-fetch")
    sub.add_argument("--version", required=True)
    sub.add_argument("--bucket", required=True)
    sub.add_argument("--destination", type=Path, required=True)
    sub.add_argument("--prefix", default=DEFAULT_RELEASE_PREFIX)
    sub.add_argument("--region", default=None)
    sub.set_defaults(handler=cmd_release_fetch)
    return parser


def main(argv: list[str] | None = None) -> int:
    # MLflow prints an emoji when a run ends. On a Windows console code page (cp1252), with
    # output redirected (a background job, a log file), that raised UnicodeEncodeError after
    # training and left the run RUNNING. Unencodable characters are escaped instead.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    args = build_parser().parse_args(argv)
    # Commands that never touch MLflow: skip setting a tracking URI (and importing mlflow).
    no_mlflow_commands = {
        "schema",
        "validate-config",
        "grid-check",
        "recompute",
        "serve",
        "serve-inference",
        "release-build",
        "release-verify",
        "release-upload",
        "release-record",
        "release-fetch",
    }
    if args.command not in no_mlflow_commands:
        import mlflow

        mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI))
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
