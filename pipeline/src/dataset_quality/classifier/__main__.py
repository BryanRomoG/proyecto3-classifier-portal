"""CLI for the T3 classifier: validate, train, run the grid, select, evaluate, predict.

Run from ``pipeline/`` with ``PYTHONPATH=src``. MLflow's destination comes from the
standard ``MLFLOW_TRACKING_URI`` (default ``sqlite:///mlflow.db`` in this directory).

    python -m dataset_quality.classifier validate-config --json '{"batch_size": 0}'
    python -m dataset_quality.classifier train --config cfg.json
    python -m dataset_quality.classifier grid-check
    python -m dataset_quality.classifier run-grid
    python -m dataset_quality.classifier list-runs
    python -m dataset_quality.classifier select
    python -m dataset_quality.classifier evaluate --confirm-final-test
    python -m dataset_quality.classifier evaluate --audit
    python -m dataset_quality.classifier recompute
    python -m dataset_quality.classifier predict --checkpoint model.pt img.png
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

    from dataset_quality.classifier.data import class_names_from_manifest, load_manifest
    from dataset_quality.classifier.experiments import valid_runs

    loaded = load_manifest(args.manifest)
    classes = class_names_from_manifest(loaded.manifest)
    rows = valid_runs(MlflowClient(), experiment or args.experiment, loaded.sha256, classes)
    _print(
        {
            "manifest_sha256": loaded.sha256,
            "valid_runs": sum(row["valid"] for row in rows),
            "runs": rows,
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command not in {"schema", "validate-config", "grid-check", "recompute"}:
        import mlflow

        mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI))
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
