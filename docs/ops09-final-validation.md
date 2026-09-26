# OPS-09 — Final infrastructure, DVC, CI and security validation

Evidence for [issue #48](https://github.com/White-eclipse1/Proyecto-02-dataset-Quality/issues/48), run against the release-candidate commit on `main`: **`459ae56`** (`docs(ops07): correct the DEV evidence transcript after the CRLF dvc.lock fix`). `git status` clean, local `main` matches `origin/main` exactly at this commit.

## Required commands

| Command | Result |
| --- | --- |
| `ruff check .` | `All checks passed!` |
| `ruff format --check .` | `50 files already formatted` |
| `pytest` | `105 passed` |
| `dvc dag` | Full 7-node graph renders (`coco-dataset.json.dvc → ingest → validate → analyze → quality_gate → split → release`), no cycles |
| `dvc repro` (1st, after `dvc pull -r dev`) | All 6 stages `didn't change, skipping` — `Data and pipelines are up to date.` |
| `dvc repro` (2nd) | Identical — all 6 stages skipped, `Data and pipelines are up to date.` |
| `dvc status` | `Data and pipelines are up to date.` |
| `dvc status -r dev` | `Cache and remote 'dev' are in sync.` |
| `terraform fmt -check -recursive infra/` | Exit 0, no output (clean) |
| `terraform init -backend=false && terraform validate` (`environments/dev`) | `Success! The configuration is valid.` |
| `terraform init -backend=false && terraform validate` (`environments/prod`) | `Success! The configuration is valid.` |
| GitHub Actions CI on this commit | **Pipeline CI: success** ([run 35410069256](https://github.com/White-eclipse1/Proyecto-02-dataset-Quality/actions/runs/35410069256)) |

All commands run inside the `pipeline` Compose profile (real MinIO + the real 311-image annotated dataset, not seed data) or via the official `hashicorp/terraform:1.9.8` image — same mechanism as `.github/workflows/pipeline-ci.yml` / `terraform.yml`, not a hand-rolled substitute.

`dvc repro` run twice with no rerun either time is the direct evidence for Section 6's own acceptance test — see [pipeline/README.md](../pipeline/README.md#prod-remote-and-hash-consistency-ops-07) for the full transcript and how a real bug in this exact check (stale CRLF hashes for two `release`-stage deps) was caught and fixed before this commit.

## Security checks (full `git log --all` history, not just `HEAD`)

| Check | Command | Result |
| --- | --- | --- |
| Real `.env` files tracked | `git ls-files \| grep -E '(^\|/)\.env(\..+)?$' \| grep -v '\.example$'` | Empty — only `.env.example`/`.env.production.example` are tracked, never a real `.env` |
| `.tfstate` tracked | `git ls-files \| grep -E '\.tfstate'` | Empty |
| Data files tracked (`.jpg`/`.png`/`.parquet`) | `git ls-files \| grep -E '\.(jpg\|png\|parquet)$'` | Empty |
| AWS access/secret keys | `git log --all -S 'AKIA'` | 4 commits matched as of `ff8dfe0`; every match reviewed, all false positives, and the count is expected to keep growing — see below |
| LLM API keys (Anthropic/OpenAI-shaped) | `git log --all -p \| grep -inE "sk-ant-...\|sk-...\|ANTHROPIC_API_KEY=...sk-\|OPENAI_API_KEY=...sk-"` | Empty |
| MinIO / MariaDB credentials | `git log --all -p` for `MINIO_ROOT_PASSWORD`/`MINIO_SECRET_KEY`/`MARIADB_ROOT_PASSWORD`/`DB_PASSWORD` values | Only local-dev placeholders ever appear (`minioadmin`, `password`, `minio_secure_password`, `app_secure_password`) — no value distinct from what `.env.example` already documents publicly |

### The `AKIA` matches — reviewed individually, none is a real key

- `11d312b` (*Add Terraform CI: fmt/validate/credential-grep...*) — adds `terraform.yml`'s own check, which greps *for* the literal string `AKIA` to block real keys. The match is the detector, not a leak.
- `1936ab1` (*Revert "Merge pull request #1..."*) and `9311394` (*feat: import project 1 portal...*) — both contain the same line, a documented audit command in a notes/README file: `` git log --all -p | grep -inE "AKIA[0-9A-Z]{16}|..." ``. It's someone's own security-audit recipe, later reverted with the rest of that import — not a credential.
- `ff8dfe0` (*OPS-09: final infrastructure, DVC, CI and security validation*) — this very document. The table above names the literal string `AKIA` to state which pattern was searched for, so the file recording the audit turns up in the audit's own grep. Review reported this as "the doc says 3, it's 4 now" — correct, and it will keep happening: `-S` matches any commit that changes how many times the string appears, so **every future edit to this section adds another match**, including the commit that fixed the count. A raw number here is stale by construction.

So the durable statement is the rule, not the tally: **every commit matching `AKIA` is either the CI detector that greps for it (`terraform.yml`) or a document naming the pattern it searched for.** No match is, or has been, a credential. To re-audit, run `git log --all -S 'AKIA' --oneline` and check each hit against that rule rather than against a count written down here.

No static AWS credential (`aws_secret_access_key`, `aws-access-key-id`, a literal `AKIA…` key) was found anywhere in history — consistent with `terraform.yml`'s own CI gate, which fails the build on exactly this pattern.

## Clean-clone startup (M1) — found broken by an external evaluation audit, fixed in APP-10

The commands above all ran against an already-populated working tree (this machine's `pipeline/data/interim/` had real output from prior runs). A separate, independent audit against the official course evaluation rubric caught something none of the commands above exercise: **a genuinely fresh clone never produces a working dashboard**, because:

1. `pipeline/data/interim/*.json` (the files `backend` reads for the Quality/Splits/Versions screens) are gitignored — correct, they're pipeline output, not source — but that means they simply don't exist after `git clone`.
2. The documented fix, `docker compose --profile pipeline run --rm pipeline dvc repro`, **did not actually fix it**: the `pipeline` service had no `volumes:` entry for `data/interim`, so `dvc repro`'s output was written only inside that `--rm` container's own writable layer and destroyed the moment the container exited. `backend`'s bind mount of `./pipeline/data/interim` (read-only) never saw anything. The six Dataset Quality screens loaded without error but with no data — a silent failure, not a crash, which is why it wasn't caught by `pytest`/CI (those don't exercise the Compose networking/volume layer at all).

**Where the fix lives**: this branch originally carried the Compose change itself (`volumes: - ./pipeline/data/interim:/app/data/interim` on the `pipeline` service). It was removed here because APP-10 (PR #55) independently adds the same mount, wider: `./pipeline/data:/app/data`, read-write, which also persists `data/version_history.json` (rewritten by the `release` stage, outside `interim/`) and the `dvc pull` output in `data/raw/`. Both edits land in the same `pipeline` service block, and git merges them without a conflict into a service with **two** `volumes:` keys — which `docker compose config` then rejects outright (`mapping key "volumes" already defined`), breaking `docker compose up` for everyone. One mount had to win; APP-10's is the more complete one, and its Copilot service depends on it. What stays in this PR is the root `README.md` update (both the "Levantar el stack" section and the DVC section) documenting the real, working order: run the pipeline profile once, then `docker compose up`.

**Re-verified for real**, in this same session, against the mount as it stood on this branch: ran `docker compose --profile pipeline run --rm pipeline sh -c "dvc pull -r dev --force && dvc repro"` — host-side `pipeline/data/interim/*.json` timestamps updated immediately after the `--rm` container exited (confirmed via `ls -la`), and the live `/versions` screen (no backend/frontend restart) picked up the real `v1.0.0` release data on the next request — proving the persistence path genuinely works end to end, not just that the command exits 0. APP-10's mount is a strict superset of the path exercised here (`./pipeline/data` contains `./pipeline/data/interim`), so that evidence carries over; re-running it once #55 is on `main` is still the cheap confirmation.

This does not change any of the Required Commands results above (all of those already ran inside the `pipeline` profile directly, which was never affected by this bug) — it specifically closes the gap between "the pipeline can produce correct output" (already true) and "a fresh clone's Web App can actually see that output" (false until the mount lands via #55).

## Clean-clone data bootstrap (M1, second finding) — raised in review, fixed here

A second review pass caught what the section above still assumed: the fix for *where `dvc repro`'s output goes* does nothing about *where the input comes from*. On a genuinely clean machine:

1. `minio_data` is a named Compose volume, so MinIO starts **empty**; `minio-init` runs `mc mb --ignore-existing local/dvc-cache`, which creates the bucket but never populates it.
2. The raw dataset is not in git — only the pointer `pipeline/data/raw/coco-dataset.json.dvc` (md5 `0ac4ecd…`, 345 KB). So `dvc pull -r dev` has nothing to pull, and the flow this document recommended could not run at all.
3. Nothing in the repo could rebuild it either: the only COCO producer is the backend's `GET /export/coco`, and the automatic seed (`backend/src/data/seed.ts`) inserts **2 sample images** and 3 categories — not the 311 annotated ones. A from-scratch export would carry a different md5 than `dvc.lock` records, and `analyze` would fail the `min_images_per_class: 300` gate anyway.

The evidence in this document was therefore produced on an already-populated environment — this machine's local DVC cache holds the blob (`pipeline/.dvc/cache/files/md5/0a/c4ecdbbd5a9b3144624ec86009b9e7`). The commands and their results stand; what was missing was any way for a second machine to reach that same starting state.

**Fixed**: the environment that produced release `v1.0.0` is published as a GitHub Release asset ([`v1.0.0-data`](https://github.com/White-eclipse1/Proyecto-02-dataset-Quality/releases/tag/v1.0.0-data), `dq-env-bundle-v1.0.0.zip`, ~496 MiB) — the 311 real images, the release's DVC cache, and the MariaDB dump (313 rows in `images`, 1038 in `annotations`). `scripts/restore-env.sh` downloads it, extracts it to a gitignored `.dq-env-bundle/`, and delegates to the bundle's own `restore.sh`, which uploads the objects to MinIO, loads the dump and verifies the counts, failing closed if they don't match. The root `README.md` documents it as the first step of the clean-clone flow, ahead of `dvc repro`. The asset deliberately lives on the Release, not in git: the dataset is versioned with DVC, which is also what the rubric requires.

**Executed for real, from empty volumes**: `./scripts/restore-env.sh` exits 0 and the whole documented chain works. The run used an isolated Compose project (`COMPOSE_PROJECT_NAME=dqclean`) after `docker compose down -v`, so `dqclean_mariadb_data` and `dqclean_minio_data` were created brand new (`select count(*) from images` returned **0** before the restore). The developer's own stack was only stopped, never removed, and was restarted afterwards with its data intact; the `dqclean` project and volumes were deleted at the end.

| Step | Result |
| --- | --- |
| SHA-256 of the downloaded asset | matches the pinned digest `04b30b87…`, checked before extracting; marker written after |
| Bundle's `restore.sh` contract | takes the repo dir as `$1` and validates it holds `docker-compose.yml` — matches what the wrapper passes |
| Objects in MinIO | 311 (expected 311) |
| Rows in `images` | 313 (expected 313 = 311 + 2 seed) |
| Rows in `annotations` | 1038 (expected 1038) |
| `dvc pull -r dev` after restore | **resolves** — `9 files fetched` from the freshly restored MinIO |
| `dvc repro` after pull | all 7 nodes `didn't change, skipping` — `Data and pipelines are up to date.` |
| `pipeline/data/interim/*.json` on the host | all 8 present after the `--rm` container exited (APP-10's mount working) |
| `GET /quality-report` (backend) | real data: `dataset_version: v1.0.0`, `overall_status: pass`, `min_images_per_class` observed 309 |
| `GET /health` on `copilot:8100` and through nginx `/copilot-api/` | `{"status":"ok"}` both ways |
| `GET /copilot` (the SPA route) | HTTP 200 — the nginx/React-Router collision APP-10 fixed stays fixed |
| `POST /copilot-api/query` with no `ANTHROPIC_API_KEY` | clean `503` with a fixed message, no traceback |

That answers the question left open above: the bundle's `restore.sh` mirrors **two** buckets, `image-annotations` and `dvc-cache`, which is why `dvc pull -r dev` resolves afterwards. It also runs `docker compose up -d` itself and waits for both MariaDB and the backend-created schema before loading the dump, so it is safe to run whether or not the stack is already up.

**Bundle reuse is verified too**: after extracting, the script stores the verified SHA-256 in `.dq-env-bundle/.sha256-verificado`, and a later run only reuses the directory if that marker equals the pinned digest. A directory without the marker (an install made by the previous, unverified version of the script) or with a different digest is discarded and downloaded again, so the bundle's `restore.sh` is never executed unless it came out of a ZIP that passed the check. The clean run above hit exactly that path: the machine had a legacy `.dq-env-bundle/` with no marker, and the script re-downloaded, verified (`OK: 04b30b87…`) and re-extracted it before restoring. A scratch-copy test also confirmed that a legacy directory (no marker), a wrong marker and a matching marker behave as described, with a planted `restore.sh` never executing in the first two.

## Acceptance criteria (issue #48)

- [x] Ruff passes.
- [x] Formatting passes.
- [x] Pytest passes.
- [x] DVC pipeline passes.
- [x] Second DVC reproduction is idempotent.
- [x] Terraform validates.
- [x] CI is green.
- [x] No secrets found in repository history.
- [x] No prohibited files tracked.

All checks green on `459ae56`, plus the clean-clone (M1) gap found above (fix delivered by APP-10 / PR #55). Release candidate technically approved as of this branch's HEAD — pending human review before OPS-10 (issue #49) proceeds, which also needs APP-10/DQ-09/DQ-10 closed independently of this ticket.
