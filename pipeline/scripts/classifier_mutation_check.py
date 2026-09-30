"""T3-4.2 / rubric 7.1: break each critical classifier rule and check the suite fails.

Works on an isolated copy: ``src/``, ``tests/``, ``experiments/`` and ``pyproject.toml`` are
copied to a temporary directory, so the repository is never modified. It first runs the
suite unmutated (it must pass), then applies one mutant at a time -- an exact, single-
occurrence text replacement that breaks one rule -- runs the tests, and restores the
original file before the next mutant. A mutant is *killed* when the suite fails.

    cd pipeline
    python scripts/classifier_mutation_check.py --report reports/classifier/mutation_check.json

Each mutant runs its most relevant test file first, then the rest of ``tests/classifier``,
with ``-x``: a killed mutant stops at the first failure, a
surviving one runs the whole suite. Exit code 0 only when every mutant is killed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
CLASSIFIER = Path("src/dataset_quality/classifier")
TESTS = Path("tests/classifier")


@dataclass(frozen=True)
class Mutant:
    name: str
    rule: str
    file: Path
    original: str
    mutated: str
    first_tests: str


MUTANTS = [
    Mutant(
        "keep-last-epoch",
        "early stopping restores the best epoch's weights, not the last",
        CLASSIFIER / "early_stopping.py",
        "    model.load_state_dict(best_state)\n",
        "    pass  # mutant: keep the last epoch's weights\n",
        "test_t3_classifier_early_stopping.py",
    ),
    Mutant(
        "ignore-min-delta",
        "an improvement smaller than min_delta does not count",
        CLASSIFIER / "early_stopping.py",
        "return value < self.best_value - self.min_delta",
        "return value < self.best_value",
        "test_t3_classifier_early_stopping.py",
    ),
    Mutant(
        "transposed-matrix",
        "confusion matrix rows are the true class, columns the predicted class",
        CLASSIFIER / "metrics.py",
        "matrix[truth][predicted] += 1",
        "matrix[predicted][truth] += 1",
        "test_t3_classifier_metrics.py",
    ),
    Mutant(
        "rounded-threshold",
        "the 85% target is compared without rounding",
        CLASSIFIER / "metrics.py",
        "return total > 0 and correct / total >= threshold",
        "return total > 0 and round(correct / total, 2) >= threshold",
        "test_t3_classifier_metrics.py",
    ),
    Mutant(
        "unsealed-test",
        "the test split cannot be read before the final evaluation",
        CLASSIFIER / "data.py",
        'if split == "test" and not allow_test:',
        "if False:  # mutant: test split readable by anyone",
        "test_t3_classifier_data.py",
    ),
    Mutant(
        "augmented-validation",
        "augmentation only touches train; validation is deterministic",
        CLASSIFIER / "data.py",
        '        eval_transform(image_size),\n        split="val",',
        '        train_transform(image_size, augment=augment),\n        split="val",',
        "test_t3_classifier_data.py",
    ),
    Mutant(
        "ignore-duplicate-leakage",
        "a manifest whose duplicate-group leakage check failed is refused",
        CLASSIFIER / "data.py",
        'if manifest.leakage_check.status != "pass" or manifest.leakage_check.leaked_pairs:',
        "if False:  # mutant: accept leaked duplicate groups",
        "test_t3_classifier_data.py",
    ),
    Mutant(
        "shared-source-image",
        "a source image cannot be in two splits",
        CLASSIFIER / "data.py",
        "            other = seen_images.setdefault(image_id, section.name)\n"
        "            if other != section.name:",
        "            other = seen_images.setdefault(image_id, section.name)\n"
        "            if False:  # mutant: same original image in two splits",
        "test_t3_classifier_data.py",
    ),
    Mutant(
        "no-optimizer-step",
        "one optimizer step per minibatch actually updates the weights",
        CLASSIFIER / "training.py",
        "            self.optimizer.step()\n",
        "            pass  # mutant: no optimizer step\n",
        "test_t3_classifier_training.py",
    ),
    Mutant(
        "reversed-class-map",
        "the reloaded model uses the checkpoint's own class map",
        CLASSIFIER / "predict.py",
        'class_names = list(checkpoint["class_names"])',
        'class_names = sorted(checkpoint["class_names"], reverse=True)',
        "test_t3_classifier_training.py",
    ),
    Mutant(
        "wrong-preprocessing",
        "inference uses the checkpoint's evaluation preprocessing",
        CLASSIFIER / "predict.py",
        "transform=eval_transform(config.image_size),",
        "transform=eval_transform(config.image_size // 4),",
        "test_t3_classifier_training.py",
    ),
    Mutant(
        "second-test-evaluation",
        "the test is evaluated only once (repeat only as a non-overwriting audit)",
        CLASSIFIER / "evaluation.py",
        "if report_path.exists() and not audit:",
        "if False:  # mutant: allow a second final evaluation",
        "test_t3_classifier_selection_evaluation.py",
    ),
    Mutant(
        "swapped-checkpoint",
        "the evaluated checkpoint is exactly the selected one",
        CLASSIFIER / "evaluation.py",
        'if _sha256(checkpoint) != selection["checkpoint_sha256"]:',
        "if False:  # mutant: evaluate any checkpoint",
        "test_t3_classifier_selection_evaluation.py",
    ),
    Mutant(
        "select-after-test",
        "selection is refused once the test was opened",
        CLASSIFIER / "selection.py",
        "if (report_dir / EVALUATION_REPORT).exists():",
        "if False:  # mutant: re-select after seeing the test",
        "test_t3_classifier_selection_evaluation.py",
    ),
    Mutant(
        "select-on-test-metric",
        "the selection policy may only use validation metrics",
        CLASSIFIER / "selection.py",
        'if not metric.startswith(("best_val_", "val_")):',
        "if False:  # mutant: any metric, test included",
        "test_t3_classifier_experiments.py",
    ),
    Mutant(
        "identical-weights-count",
        "a run with the same final weights as another is not a new valid run",
        CLASSIFIER / "experiments.py",
        "if not reasons and final_weights in seen_weights:",
        "if False:  # mutant: identical weights count as a new run",
        "test_t3_classifier_training.py",
    ),
    Mutant(
        "constant-hyperparameter",
        "the grid must vary each of the seven hyperparameters",
        CLASSIFIER / "experiments.py",
        "        if len(distinct) < 2:\n",
        "        if False:  # mutant: constant hyperparameters allowed\n",
        "test_t3_classifier_experiments.py",
    ),
    Mutant(
        "unknown-field-ignored",
        "an unknown training parameter is rejected, not silently ignored",
        CLASSIFIER / "config.py",
        '    """A complete, validated training job description."""\n\n'
        '    model_config = ConfigDict(extra="forbid")',
        '    """A complete, validated training job description."""\n\n'
        '    model_config = ConfigDict(extra="ignore")',
        "test_t3_classifier_config.py",
    ),
]


def _pytest(workdir: Path, first: str | None) -> tuple[int, str, float]:
    # Explicit file list, relevant file first: pytest drops a file argument's siblings when
    # the same run also names their directory, so "file + directory" would run one file only.
    files = sorted(p.name for p in (workdir / TESTS).glob("test_*.py"))
    ordered = ([first] if first else []) + [name for name in files if name != first]
    command = [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider"]
    command += [str(TESTS / name) for name in ordered]
    env = {**os.environ, "PYTHONPATH": str(workdir / "src"), "CLASSIFIER_TESTS_REQUIRED": "1"}
    started = time.monotonic()
    completed = subprocess.run(
        command, cwd=workdir, env=env, capture_output=True, text=True, check=False
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    return completed.returncode, lines[-1] if lines else "", time.monotonic() - started


def _copy_pipeline(target: Path) -> None:
    for name in ("src", "tests", "experiments"):
        shutil.copytree(
            PIPELINE / name, target / name, ignore=shutil.ignore_patterns("__pycache__")
        )
    shutil.copy2(PIPELINE / "pyproject.toml", target / "pyproject.toml")


def run(mutants: list[Mutant]) -> dict:
    with tempfile.TemporaryDirectory(prefix="classifier-mutants-") as tmp:
        workdir = Path(tmp)
        _copy_pipeline(workdir)

        code, summary, seconds = _pytest(workdir, None)
        baseline = {"passed": code == 0, "summary": summary, "seconds": round(seconds, 1)}
        print(f"[baseline] {'PASS' if code == 0 else 'FAIL'}: {summary}", file=sys.stderr)
        if code != 0:
            return {"baseline": baseline, "mutants": [], "all_killed": False}

        results = []
        for mutant in mutants:
            path = workdir / mutant.file
            original = path.read_text(encoding="utf-8")
            occurrences = original.count(mutant.original)
            if occurrences != 1:
                raise SystemExit(
                    f"{mutant.name}: expected 1 occurrence in {mutant.file}, found {occurrences}"
                )
            path.write_text(original.replace(mutant.original, mutant.mutated), encoding="utf-8")
            try:
                code, summary, seconds = _pytest(workdir, mutant.first_tests)
            finally:
                path.write_text(original, encoding="utf-8")
            killed = code != 0
            verdict = "KILLED" if killed else "SURVIVED"
            print(f"[{mutant.name}] {verdict}: {summary}", file=sys.stderr)
            results.append(
                {
                    "name": mutant.name,
                    "rule": mutant.rule,
                    "file": mutant.file.as_posix(),
                    "original": mutant.original.strip(),
                    "mutated": mutant.mutated.strip(),
                    "killed": killed,
                    "pytest_summary": summary,
                    "seconds": round(seconds, 1),
                }
            )
    return {
        "baseline": baseline,
        "mutants": results,
        "killed": sum(r["killed"] for r in results),
        "total": len(results),
        "all_killed": all(r["killed"] for r in results),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", type=Path, help="write the JSON result here")
    parser.add_argument("--only", nargs="*", help="mutant names to run (default: all)")
    args = parser.parse_args(argv)

    selected = [m for m in MUTANTS if not args.only or m.name in args.only]
    result = run(selected)
    result["ran_at"] = datetime.now(UTC).isoformat()
    result["python"] = sys.version.split()[0]
    if args.report:
        args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("killed", "total", "all_killed") if k in result}))
    return 0 if result["all_killed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
