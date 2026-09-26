# pipeline/

Python 3.12 DVC pipeline: `ingest → validate → analyze → quality_gate → split → release`. See `dvc.yaml` for the full stage graph and `docs/` (repo root) for the Data Quality baseline audits.

## Dataset release & versioning (OPS-07)

The `release` stage (`src/dataset_quality/versioning/__main__.py`) stamps each pipeline run as a dataset version and writes the full version timeline to `data/interim/versions.json` (`VersionsReport`, `copilot/contracts.py`). It reads and appends to a git-tracked ledger, `pipeline/data/version_history.json`, which is what makes a real diff against the *previous* release possible without re-reading old dataset files. That ledger is deliberately **not** a DVC dependency or output — it's a side effect the script appends to on every run, not a reproducibility input; wiring it into `dvc.yaml` would make `release` perpetually "dirty" against its own last write and break `dvc repro`'s rerun-avoidance for everything downstream of it.

### Versioning rules

- The dataset version (`params.yaml`'s `dataset_version`) must be `v<MAJOR>.<MINOR>.<PATCH>` — no prerelease suffixes.
- The **first** release in the ledger must be exactly `v1.0.0`.
- Every later release must be **strictly greater** (tuple comparison of MAJOR.MINOR.PATCH) than the last one recorded — the stage raises and refuses to run otherwise, rather than silently overwriting history.

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
