# pipeline/

Python 3.12 DVC pipeline: `ingest → validate → analyze → quality_gate → crop → classifier_split → split → release`, where `crop` is the T3-1.1 stage (see "COCO crops (T3-1.1)") that feeds the classifier, and `classifier_split` is the T3-1.2 stage (see "Classifier split manifest (T3-1.2)") that groups those crops leak-free into a *new* 70/20/10 manifest. See `dvc.yaml` for the full stage graph and `docs/` (repo root) for the Data Quality baseline audits.

## COCO crops (T3-1.1)

The `crop` stage (`src/dataset_quality/crops/`) turns the valid bounding boxes of the
frozen target classes (`m3.target_categories` in `params.yaml`: `person`, `car`) into
classifier-ready PNG crops. It sits after `quality_gate` and, like `split`, reads the
persisted `quality.json`: an `overall_status` of `fail` aborts the stage with exit code 1
and writes nothing. It does not touch `data/interim/coco.json` or the inherited 70/15/15
split outputs; the new 70/20/10 manifest is T3-1.2's.

```bash
# from pipeline/, with MariaDB + MinIO populated (see "Needs a populated backend")
PYTHONPATH=src dvc repro crop

# the stage's own command, verbatim
PYTHONPATH=src python -m dataset_quality.crops \
  data/interim/coco.json \
  --quality-report data/interim/quality.json \
  --dataset-version v1.0.0 \
  --category person --category car \
  --crops-root data/processed/crops \
  --manifest-output data/processed/crops_manifest.json \
  --exclusions-output data/processed/crop_exclusions.json
```

### What it produces

| Artifact | Contents |
|---|---|
| `data/processed/crops/<category>/<annotation_id>.png` | one deterministic RGB PNG per valid box, named by COCO annotation id |
| `data/processed/crops_manifest.json` | `dataset_version`, the COCO `coco_sha256`, the target classes, counts per class, and one record per crop: `annotation_id`, `source_image_id`, `source_file_name`, `category_id`/`category_name`, the COCO `bbox`, the integer limits used (`x_min`/`y_min`/`x_max`/`y_max`), `crop_width`/`crop_height`, `relative_path` (relative to `pipeline/`) and `png_sha256` |
| `data/processed/crop_exclusions.json` | every rejected annotation: `annotation_id` when it exists, image/category, the *original* `bbox` value, and stable `reasons` |

Pixel limits are `floor` for `x`/`y` and `ceil` for `x + width`/`y + height`, computed only
after the box has been validated against the size COCO declares *and* against the size PIL
actually decodes. Each crop record carries both pairs of dimensions
(`source_image_width`/`height` from COCO, `observed_image_width`/`height` from PIL), so a
source whose real size disagrees with COCO is visible instead of silently mis-cropped.

Reproducibility: no timestamps, host paths or filesystem-dependent ordering are recorded,
records are sorted by ids, and the three outputs are staged next to their final paths and
published only after the whole run succeeded -- so a second run over the same COCO, params
and stored objects produces byte-identical JSON and PNGs, and a failed run never leaves a
partial `crops/` tree next to the previous release's JSON.
`pipeline/data/processed/.gitignore` lists the three artifacts only (all DVC outputs);
`dvc.lock` and the stage definition stay tracked.

### Exclusion rules

A rejected box is data, not a crash: the annotation is recorded and every other crop is
still produced, so the run never aborts on the first bad box.

| Reason | Meaning |
|---|---|
| `malformed_annotation` | the `annotations[]` entry is not a JSON object, or has no usable positive integer `id` |
| `malformed_bbox` | `bbox` is missing, or is not an array of exactly four values |
| `non_numeric_bbox` | `bbox` contains a non-numeric value (booleans included) |
| `non_finite_bbox` | `bbox` contains `NaN` or an infinity (serialized as `null`, since JSON has no `NaN`) |
| `nonpositive_width` / `nonpositive_height` | degenerate box: `width <= 0` or `height <= 0` |
| `negative_origin` | `x < 0` or `y < 0` |
| `origin_outside_image` | `x >= width` or `y >= height` of the declared image |
| `exceeds_image_bounds` | `x + width > width` or `y + height > height` of the declared image |
| `unknown_category` | `category_id` is not declared in `categories`, so the class cannot be resolved |
| `unknown_image` | `image_id` is not declared in `images` |
| `real_dimension_mismatch` | PIL's size differs from the declared size (also listed once per image in `dimension_mismatches`) |
| `exceeds_real_image_bounds` | the box fits the declared grid but not the real pixel grid |

Annotations of non-target classes are **not** errors: they are counted once in the summary's
`ignored_non_target` and never listed as exclusions. The summary also reports
`exclusions_by_reason`, `excluded_target_boxes` and `unresolvable_annotations`, so the
counters can be audited against each other.

Structural damage (a missing `images`/`categories`/`annotations` array, an image without a
positive id or size, duplicate ids) and an unusable target configuration (an undeclared or
duplicated target category, or a name that cannot be a directory) abort the stage instead:
those are not per-box data problems.

### Failure modes (fail closed)

- Quality Gate `fail`: exit 1, no crops, no JSON.
- A missing `images` row, a blank `storage_key`, an unreachable object or an undecodable
  image raises `CropSourceUnavailableError` / `CropSourceDecodeError`: the stage fails
  visibly instead of reporting a smaller crop set.
- Nothing is published until the run is complete: the PNGs and both JSON artifacts are
  built under temporary sibling paths inside `data/processed/`, and only then are the
  three outputs replaced together (`crops/` first, the JSON last, so the manifest is
  never newer than the tree it describes). A failed run therefore leaves the previous
  release byte-for-byte as it was, and removes its own temporaries -- it never leaves a
  partially regenerated `crops/` next to the previous manifest.
- The manifest only ever records the final `data/processed/...` paths; the staging names
  are an implementation detail of the run and never appear in an artifact.
- The count invariants (`crops + excluded_target_boxes == target_annotations`, and the
  total splitting into target, ignored non-target and unresolvable annotations) are
  re-checked before anything is serialized or published.

### Needs a populated backend

`crop` reads real image bytes, so it needs MariaDB and MinIO/S3 populated for the release
under test: an `images.storage_key` for every image id referenced by a target-class box, and
the matching object in the source bucket (`object_store_bucket`, default `image-annotations`).
COCO image ids are the backend's `images.id` -- the same relation the `analyze` stage already
relies on. On a clean clone, populate both with `./scripts/restore-env.sh` (repo root) before
running the stage; without that data it fails loudly rather than emitting a partial crop set.

## Classifier split manifest (T3-1.2)

The `classifier_split` stage (`src/dataset_quality/classifier_splits/`) builds the **new**
70/20/10 manifest for the classifier crops. It does not replace or modify the inherited
`split` stage: `params.yaml`'s `split` block (0.70/0.15/0.15) and its outputs stay exactly
as they were. The grouping algorithm is not reimplemented either — the canonical COCO, a
`SplitConfig(classifier_split.train, val, test, seed)` and `duplicate_pairs.json` are
handed to the inherited `dataset_quality.splits.generate_splits`, which keeps every image
and every transitive duplicate component in a single split. Each `crops_manifest.json`
record is then placed in the split of its `source_image_id`, so each source image and each
crop appears exactly once and no group can cross train/val/test.

```bash
# from pipeline/, after `crop` has produced data/processed/crops_manifest.json
PYTHONPATH=src dvc repro classifier_split

# the stage's own command, verbatim
PYTHONPATH=src python -m dataset_quality.classifier_splits \
  data/interim/coco.json \
  --crops-manifest data/processed/crops_manifest.json \
  --duplicate-pairs data/interim/duplicate_pairs.json \
  --dataset-version v1.0.0 \
  --train 0.70 --val 0.20 --test 0.10 --seed 42 \
  --output data/processed/classifier_split_manifest.json
```

### What it validates and produces

Before generating anything, the stage refuses inputs that do not provably describe each
other: the crops manifest's `dataset_version` must match, its `coco_sha256` must equal the
SHA-256 of the canonical COCO file, every crop must reference an image the COCO declares,
and both `annotation_id` and `relative_path` must be unique. A `duplicate_pairs.json` entry
pointing at an unknown image id fails inside the inherited generator itself. After
generating, it also re-checks that the assignment is an exact partition and that zero
duplicate pairs leaked across splits.

`data/processed/classifier_split_manifest.json` is deterministic — no timestamps, no
absolute paths, ids sorted — and records: the SHA-256 provenance of all three inputs, the
seed, the 70/20/10 proportions, the ordered `image_ids` and crops per split, image/crop
counts per split and category, and the leakage result (pairs checked, zero leaked). It
never reads or exposes any model prediction or metric. `pipeline/data/processed/.gitignore`
lists this artifact only; `dvc.lock` and the stage definition stay tracked.

## Classifier: training, MLflow runs, selection and final test (T3-1.3 … T3-3.3)

`src/dataset_quality/classifier/` trains the image classifier on the T3-1.2 manifest. It
reads **only train and validation**; the test split is sealed (`split_records` raises
`SealedTestSplitError`) until `evaluate` runs on a candidate already selected by
validation.

| Piece | File | What it guarantees |
|---|---|---|
| Config (7 searched hyperparameters + fixed ones) | `config.py` | strict pydantic model; invalid values rejected before a job exists (`validate-config`, `schema`) |
| CNN | `model.py` | ResNet-18 (`ResNet18_Weights.IMAGENET1K_V1` backbone, head from scratch) or a from-scratch LeNet-style CNN; head = `hidden_layers` + `dropout`; weight origin and trainable layers declared |
| Data | `data.py` | manifest re-checked for leakage (crops, images, duplicate groups); random augmentation only on train; val/test/inference share one deterministic preprocessing |
| Seeds | `reproducibility.py`, `data.SeededEpochSampler` | separate `init` / `augmentation` / `shuffle` seeds + the manifest's partition seed; library versions and git commit recorded |
| Loop | `training.py` | one `optimizer.step()` per minibatch; per-epoch train/val loss+accuracy to MLflow; `status.json` rewritten per epoch |
| Early stopping | `early_stopping.py` | `monitor` / `patience` / `min_delta`; always restores the **best** epoch's weights |
| 10 runs | `experiments.py`, `experiments/classifier_grid.yaml` | grid refused unless ≥ 10 runs, no duplicates, each of the 7 hyperparameters with ≥ 2 values |
| Selection | `selection.py`, `experiments/selection_policy.yaml` | pre-declared validation metric; refuses after the test was opened |
| Final test | `evaluation.py`, `metrics.py` | one-time evaluation (explicit `--confirm-final-test`), per-sample predictions CSV, matrix (rows = true), accuracy, macro F1, per-class P/R/F1, majority baseline, most confused pair; `--audit` recomputes without overwriting |
| Inference | `predict.py` | reloads a checkpoint in a clean process with its class map and preprocessing |

Setup (on top of the normal pipeline install):

```bash
pip install -r requirements-train.txt --extra-index-url https://download.pytorch.org/whl/cpu
# NVIDIA GPU: same versions from .../whl/cu128 instead; `train`/`run-grid` take --device auto|cpu|cuda
docker compose up -d mlflow                       # from the repo root: MLflow on :5000
export MLFLOW_TRACKING_URI=http://localhost:5000  # without it the CLI falls back to sqlite:///mlflow.db
```

The `mlflow` Compose service keeps its SQLite store and the proxied artifacts in
`pipeline/mlflow-data/` (git-ignored), so the runs survive `docker compose down`.

Runbook, from `pipeline/` with `PYTHONPATH=src`, **in this order** (the order is the
protocol: selection is written before the test is ever read):

```bash
# 0. the manifest must exist (DVC): data/processed/classifier_split_manifest.json
PYTHONPATH=src dvc repro classifier_split

# 1. check the grid, then smoke-test one short run
python -m dataset_quality.classifier grid-check
python -m dataset_quality.classifier train --json '{"max_epochs": 2}' --run-name smoke

# 2. T3-2.5 reproducibility: same config twice -> same epoch1_order_sha256 / final_state_sha256
#    (result, per device: reports/classifier/reproducibility.md)
python -m dataset_quality.classifier train --json '{"max_epochs": 2}' --run-name repro-a
python -m dataset_quality.classifier train --json '{"max_epochs": 2}' --run-name repro-b

# 3. T3-3.1 the 10 official runs (resumable: runs that already have a valid run are skipped)
python -m dataset_quality.classifier run-grid
python -m dataset_quality.classifier list-runs          # valid run IDs, params, val metrics

# 4. T3-3.2 select by validation -> reports/classifier/selection.json (commit it!)
python -m dataset_quality.classifier select

# 5. T3-3.3 open the test ONCE -> reports/classifier/test_* (commit them)
python -m dataset_quality.classifier evaluate --confirm-final-test

# audit at any time (never overwrites): recompute from checkpoint and from the CSV alone
python -m dataset_quality.classifier evaluate --audit
python -m dataset_quality.classifier recompute
```

Checkpoints, per-run artifacts and the local MLflow store are git-ignored
(`artifacts/`, `mlflow.db`, `mlruns/`, `*.pt`); the evidence that must be versioned —
`reports/classifier/selection.json`, `test_evaluation.json`, `test_predictions.csv`,
`confusion_matrix.png` — is small and committed, in that chronological order.

Device: `--device auto` (default) uses CUDA when available; weights are initialised on CPU
and the checkpoint is always saved on CPU. The device, GPU name and CUDA/cuDNN versions are
logged per run, and all official runs must share one device.

Known non-determinism: on CPU with `num_workers=0` repeated runs are bit-identical (the
tests assert equal final weight hashes). On GPU some cuDNN kernels are not deterministic;
`torch.use_deterministic_algorithms(True, warn_only=True)` is set and the device is
recorded in `environment.json`.

## Dataset release & versioning (OPS-07)

The `release` stage (`src/dataset_quality/versioning/__main__.py`) stamps each pipeline run as a dataset version and writes the full version timeline to `data/interim/versions.json` (`VersionsReport`, `copilot/contracts.py`). It reads and appends to a git-tracked ledger, `pipeline/data/version_history.json`, which is what makes a real diff against the *previous* release possible without re-reading old dataset files. That ledger is deliberately **not** a DVC dependency or output — it's a side effect the script appends to on every run, not a reproducibility input; wiring it into `dvc.yaml` would make `release` perpetually "dirty" against its own last write and break `dvc repro`'s rerun-avoidance for everything downstream of it.

### Versioning rules

- The dataset version (`params.yaml`'s `dataset_version`) must be `v<MAJOR>.<MINOR>.<PATCH>` — no prerelease suffixes.
- The **first** release in the ledger must be exactly `v1.0.0`.
- A version **strictly greater** (tuple comparison of MAJOR.MINOR.PATCH) than the last one recorded appends exactly one new entry to the ledger and regenerates `data/interim/versions.json`.
- A version **lower** than the last one recorded is rejected — the stage raises before writing anything.
- Re-stamping the **same** version is allowed *only* as an idempotent no-op: when `content_hash`, `snapshot` and `quality_status` are all identical to the recorded release, the stage exits 0, appends nothing (the ledger is left byte-for-byte as it was) and regenerates `data/interim/versions.json` from it. That is what makes a `dvc repro` that re-runs `release` — because a dependency of the stage changed while the dataset itself did not — a no-op instead of a crash. The same version over *different* content, snapshot or gate status is rejected with an explicit error naming the field(s) that differ: bump `dataset_version` instead of silently overwriting history.

### Reading a `VersionDiff` — sign convention

Each release after the first carries a `diff_from_previous` (`VersionDiff` in `copilot/contracts.py`) comparing it to the release immediately before it. **These numbers are signed deltas, not absolute counts** — read them like a bank statement, not a summary:

| Field | Meaning |
|---|---|
| `images_added` | `current_image_count − previous_image_count`. **Negative means images were removed**, not "0 added, N missing" — there is no separate `images_removed` field; the sign carries the direction. |
| `boxes_added` | Same idea, for total bounding-box annotations. Negative = fewer boxes than last release. |
| `classes_left_minimum` | Category names that **newly** dropped below `quality.yaml`'s real `min_images_per_class` threshold *in this release* — i.e. they were at or above it last release and are below it now. This is a regression signal, not a snapshot: a class that has been below the threshold for several releases in a row is **not** re-listed every time, only on the release where it first crosses down. A class recovering back above the threshold isn't listed either (there's no `classes_left_minimum`-equivalent for the reverse direction — check two consecutive `per_class` snapshots directly if that's needed). |
| `small_object_ratio_change_pct` | `current_small_object_percentage − previous_small_object_percentage`, in percentage **points** (e.g. `10.0 → 13.5` reports `3.5`, not a ratio-of-ratios like `1.35`). Negative means small objects became relatively less common. |

Worked example (from a real end-to-end test run of the `release` stage): image count went 300 → 290, annotations 700 → 690, category `person`'s distinct-image count went 305 → 295 (crossing below the 300 threshold), `car` went 310 → 312 (stayed above), small-object percentage went 10.0 → 13.5. The resulting diff was:

```json
{
  "images_added": -10,
  "boxes_added": -10,
  "classes_left_minimum": ["person"],
  "small_object_ratio_change_pct": 3.5
}
```

### PROD remote and hash consistency (OPS-07)

`pipeline/.dvc/config` has two remotes: `dev` (MinIO, `s3://dvc-cache`) and `prod` (real AWS S3, `s3://dvc-cache-prod-<account_id>`) — `dev` is untouched by this ticket, still MinIO. DVC's cache is content-addressed (each object's key is its own hash), so pushing the same local cache to both remotes produces byte-identical objects in both **by construction** — not a re-serialization or re-compression on the way to S3, a plain `cp` of the same content-addressed blob.

This isn't just the theoretical argument: it was run for real, end to end, against the real 311-image annotated dataset (loaded into MariaDB + MinIO from the team's EC2 instance — not seed/synthetic data).

**DEV — run locally** (`docker compose --profile pipeline run --rm pipeline sh -c '...'`, real MinIO, real dataset), including `dvc repro` run twice to demonstrate real rerun-avoidance (Section 6's own acceptance test):

```
$ dvc pull -r dev
A       data/interim/coco.json
A       data/interim/duplicate_pairs.json
A       data/interim/m3_baseline.json
A       data/interim/observations.json
A       data/interim/quality.json
A       data/interim/split_assignment.json
A       data/interim/splits.json
A       data/interim/versions.json
A       data/raw/coco-dataset.json
9 files fetched and 9 files added

$ dvc repro
'data/raw/coco-dataset.json.dvc' didn't change, skipping
Stage 'ingest' didn't change, skipping
Stage 'validate' didn't change, skipping
Stage 'analyze' didn't change, skipping
Stage 'quality_gate' didn't change, skipping
Stage 'split' didn't change, skipping
Running stage 'release':
> ...
Updating lock file 'dvc.lock'

$ dvc repro
'data/raw/coco-dataset.json.dvc' didn't change, skipping
Stage 'ingest' didn't change, skipping
Stage 'validate' didn't change, skipping
Stage 'analyze' didn't change, skipping
Stage 'quality_gate' didn't change, skipping
Stage 'split' didn't change, skipping
Stage 'release' didn't change, skipping
Data and pipelines are up to date.

$ dvc push -r dev
1 file pushed

$ dvc status -r dev
Cache and remote 'dev' are in sync.

$ dvc status
Data and pipelines are up to date.

$ md5sum dvc.lock
fe50f93bfde715311f4a11a2ceeaac74  dvc.lock
```

`release` re-runs on the first `dvc repro` in the transcript above (not "skipped" like the other five stages) because the `dvc.lock` being pulled at that point still had stale hashes for two of `release`'s own dependencies (`versioning/__main__.py`/`models.py` — a Docker-build/line-ending artifact from earlier in this branch's history, fixed in a follow-up commit; the files themselves never actually differed). With that fixed, a fully fresh `dvc pull -r dev` + `dvc repro` skips **all six** stages immediately — confirmed separately, same dataset, same remote:

```
$ dvc pull -r dev
9 files fetched and 9 files added

$ dvc repro
'data/raw/coco-dataset.json.dvc' didn't change, skipping
Stage 'ingest' didn't change, skipping
Stage 'validate' didn't change, skipping
Stage 'analyze' didn't change, skipping
Stage 'quality_gate' didn't change, skipping
Stage 'split' didn't change, skipping
Stage 'release' didn't change, skipping
Data and pipelines are up to date.
```

**PROD — real AWS S3, no static credentials.** A local `dvc push -r prod` was deliberately **not** run from a developer machine for this evidence: that would need a real long-lived AWS access key sitting on a laptop, which is exactly what the OIDC setup (`infra/modules/github-oidc`, Section 9) exists to avoid — and a static key anywhere in this repo's history is an automatic 0 on that section plus a security finding (Section 9, M2). PROD's evidence instead comes from `.github/workflows/release.yml` (`workflow_dispatch`, OIDC-authenticated, no `aws-access-key-id` anywhere): a real run against `main` right after this merged, writing and reading back a marker object in the real PROD buckets through the OIDC-assumed role.

> Run: [`35409085077`](https://github.com/White-eclipse1/Proyecto-02-dataset-Quality/actions/runs/35409085077) — `main`, `workflow_dispatch`, **success**
>
> ```
> Assuming role with OIDC
> Authenticated as assumedRoleId AROAZ7HKIOMTITRLK3PH4:GitHubActions
>
> [Write and read back a marker object in dataset-releases-prod]
> upload: ./proof.txt to s3://dataset-releases-prod-685538571046/_release-workflow-check/oidc-proof.txt
> download: s3://dataset-releases-prod-685538571046/_release-workflow-check/oidc-proof.txt to ./downloaded.txt
> Real PutObject + GetObject via the OIDC role succeeded against dataset-releases-prod-685538571046.
>
> [Write and read back a marker object in dvc-cache-prod]
> upload: ./proof.txt to s3://dvc-cache-prod-685538571046/_release-workflow-check/oidc-proof.txt
> download: s3://dvc-cache-prod-685538571046/_release-workflow-check/oidc-proof.txt to ./downloaded.txt
> Real PutObject + GetObject via the OIDC role succeeded against dvc-cache-prod-685538571046.
>
> [Confirm the role has no access outside the 4 scoped buckets]
> Confirmed: access denied outside the scoped release buckets, as expected.
> ```

Since DVC's cache is content-addressed, the `dvc.lock` above is the actual guarantee of DEV/PROD consistency: the same `md5` in `dvc.lock` names the same object in both `s3://dvc-cache` (MinIO) and `s3://dvc-cache-prod-<account_id>` (S3) — there is no second, independent hash to "go out of sync," only one object identity referenced from two remotes. The `release.yml` run above is the evidence that the OIDC role can actually reach and read/write those PROD buckets for real, and *only* those buckets — the same role and the same 4-bucket-scoped policy that a real `dvc push -r prod` would use.
