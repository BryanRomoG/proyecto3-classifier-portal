# Infrastructure (OPS-05 foundation, completed in OPS-08, extended in OPS-07)

Terraform for the dataset-quality pipeline's AWS infrastructure. Laid out as reusable modules under `modules/`, composed per environment under `environments/{dev,prod}`.

## Modules

| Module | What it is | Status |
|---|---|---|
| `network` | VPC across 2 AZs, public + private subnets, IGW, route tables, S3 VPC Gateway Endpoint (added in OPS-08, attached to the private route table — no NAT gateway needed for S3 traffic). | **Applied for real in dev** |
| `compute` | ECS Fargate cluster + task execution IAM role. No task definitions yet — those need an actual container image, which is out of OPS-08's scope (confirmed against issue #31 directly). | **Applied for real in dev** (cluster + role only, no running tasks) |
| `data` | RDS MariaDB in the private subnets. Master credentials are managed natively by RDS's Secrets Manager integration (`manage_master_user_password = true`) rather than a hand-rolled secret. | **Applied for real in dev** (`db.t4g.micro`, single-AZ) |
| `storage` | Generic private S3 bucket module (name/versioning/Object Lock as inputs — Object Lock added in OPS-08, opt-in and off by default). Instantiated for the real `dvc-cache-<env>-<account_id>` (versioned only) and `dataset-releases-<env>-<account_id>` (versioned + Object Lock — a working cache can't be WORM, a published release should be) buckets, plus `infra/bootstrap`'s state bucket. The environment is part of the bucket name — `dev`/`prod` currently share one AWS account, so without it both environments would compute the same global S3 name and the second `apply` would collide with the first (caught in OPS-08 PR review). | **Applied for real in dev and prod** (targeted `dvc_cache`/`dataset_releases` apply in prod, OPS-07), plus `infra/bootstrap`'s state bucket |
| `github-oidc` | GitHub Actions → AWS trust via OIDC: an `aws_iam_openid_connect_provider` plus an `aws_iam_role` whose trust policy only accepts tokens whose `sub` claim matches this exact repo on an allowed branch. No static AWS keys anywhere. The role starts with **zero** attached permissions (`managed_policy_arns = []`) — `sts:GetCallerIdentity` needs none, and later tickets (OPS-06/07/08) add permissions incrementally as they're actually needed, instead of granting broad access upfront. | **Applied for real in dev** |

## What's actually deployed vs. what's just validated

**All five modules are applied for real in `environments/dev`**, by Diego, in **AWS CloudShell** (already authenticated in-browser — no local access keys were ever created): the full VPC/subnet/routing/S3-endpoint stack, the ECS cluster + task execution role, the RDS instance (`db.t4g.micro`, single-AZ), both real S3 buckets (`dvc-cache-dev-<account_id>`, `dataset-releases-dev-<account_id>`), and the GitHub OIDC provider/role (OPS-05). `infra/bootstrap`'s state bucket + DynamoDB lock table are applied for real too, and `environments/dev`'s state has been migrated onto that S3 backend — confirmed with `terraform state list` (31 resources) and a clean `terraform plan` (`No changes. Your infrastructure matches the configuration.`) run directly against the real backend, not assumed from the code alone.

The bucket names above are environment-qualified (`-dev-`/`-prod-`) precisely because `dev` and `prod` share one AWS account for now: without the environment segment both environments' `storage` module calls would compute the identical global S3 bucket name, and applying the second environment would fail trying to create a bucket the first environment's state already owns. This was caught in OPS-08 PR review and fixed before `prod` was ever applied — `dev`'s buckets were renamed (`terraform apply` destroys and recreates them under the new name; safe here since nothing had been pushed into them yet, DVC's DEV remote is still MinIO).

Wiring DVC to these buckets, giving the OIDC role S3 permissions, and the DEV/PROD content-hash comparison were deliberately left out of OPS-08 — that's [OPS-07](https://github.com/White-eclipse1/Proyecto-02-dataset-Quality/issues/30)'s explicit scope, and it's what the section below covers.

`prod` assumes a separate AWS account eventually, which is why it has its own `github-oidc` provider/role rather than sharing dev's (a single AWS account can only have one GitHub OIDC provider per URL; two independent accounts each need their own). Its `network`/`compute`/`data` stay validate-only. Its `dvc_cache`/`dataset_releases` storage modules **are applied for real as of OPS-07** — confirmed with `aws s3api list-buckets`: `dvc-cache-prod-<account_id>` and `dataset-releases-prod-<account_id>` both exist. Everything else in `prod` is still just `terraform fmt`/`init -backend=false`/`validate`, nothing else `apply`'d. Its state lives in the *same* bootstrap bucket as dev only because this project has one AWS account total right now — a real multi-account rollout would give prod its own backend entirely.

## OPS-07: PROD S3 remote and the release workflow

**PROD DVC remote:** `pipeline/.dvc/config` has a `prod` remote (`s3://dvc-cache-prod-<account_id>`, real AWS S3) alongside the untouched `dev` remote (MinIO). DVC's cache is content-addressed, so pushing the same local cache to both remotes produces byte-identical objects by construction — see `pipeline/README.md`'s "PROD remote and hash consistency" section for the real verification procedure and why it's a local, not CI, step (GitHub-hosted runners can't reach docker-compose's MinIO).

**OIDC S3 permissions — applied for real:** the `github-oidc` module only supports attaching pre-made AWS-managed policy ARNs (`for_each` over `managed_policy_arns`) — there's no inline-policy mechanism in it. Since we need a *custom*, tightly-scoped policy (not an AWS-managed one), `environments/dev/main.tf` defines its own `aws_iam_policy` (built from an `aws_iam_policy_document` data source, scoped to exactly `s3:ListBucket`/`GetObject`/`PutObject` on the 4 real bucket ARNs — `dvc-cache`/`dataset-releases` × `dev`/`prod` — never a broad managed policy) and attaches it directly to the same real role via `aws_iam_role_policy_attachment`. dev's role is the one used for both environments' buckets since this project has a single AWS account right now. Confirmed with `aws iam list-attached-role-policies --role-name github-actions-dataset-quality-dev`: `dataset-quality-release-publish` is attached.

**`.github/workflows/release.yml`** (`workflow_dispatch`-only, same reasoning as `aws-oidc-check`): proves the new IAM policy actually works — writes and reads back a real marker object in both PROD buckets via the OIDC-assumed role, then confirms the role is *denied* access to an out-of-scope bucket (the Terraform state bucket), as evidence the policy is neither too narrow nor too broad. It deliberately does not attempt `dvc push -r prod` itself — see the workflow file's own comment for why.

**PROD storage buckets, applied for real:** same "apply for real when it's free" call as bootstrap/OIDC/dev's buckets — a targeted apply (not a full `prod` apply; `network`/`compute`/`data` stay untouched, no new RDS/ECS spend):
```bash
# In AWS CloudShell, already authenticated:
cd Proyecto-02-dataset-Quality/infra/environments/prod
terraform init
terraform apply -target=module.dvc_cache -target=module.dataset_releases
```

Since `dev` runs real billable resources (RDS, an ECS cluster, S3), destroy it after grading if it's not needed to stay up (`terraform destroy` from `environments/dev`, run the same way as the applies above).

## `infra/bootstrap/`

A separate, tiny root — not an environment — that exists to solve one bootstrapping problem: Terraform can't store its own state in an S3 bucket that Terraform itself hasn't created yet. It creates just the state bucket (versioned — Terraform's own state-recovery mechanism) and a DynamoDB table for locking, and deliberately keeps **local** state itself, since this is the one piece of infrastructure that can't depend on the remote backend it's creating. `environments/dev` and `environments/prod` each have a `backend "s3" {}` block pointing at these resources (account ID hardcoded — backend blocks can't use variables or data sources, so this can't be `${data.aws_caller_identity...}` the way bucket names elsewhere are).

## One-time setup for whoever picks this up next

1. **Bootstrap the state backend, then migrate both environments onto it** (already done for account `685538571046` / `us-east-1`):
   ```bash
   # In AWS CloudShell, already authenticated:
   git clone <repo> && cd Proyecto-02-dataset-Quality/infra/bootstrap
   terraform init
   terraform apply

   cd ../environments/dev
   terraform init -migrate-state
   cd ../../environments/prod
   terraform init -migrate-state
   ```
   `dev`'s migration is done and verified (`terraform state list` shows all 31 resources, `terraform plan` reports `No changes`). `prod` has never been applied, so its migration just moves an effectively-empty state file; still worth doing, for consistency and to prove the backend config is genuinely correct for both — pending as of this writing.

2. **Bootstrap the dev OIDC role** (already done for account `685538571046` / `us-east-1`, kept here for reference or for re-running against a different account):
   ```bash
   # In AWS CloudShell, already authenticated:
   git clone <repo> && cd Proyecto-02-dataset-Quality/infra/environments/dev
   terraform init
   terraform apply -target=module.github_oidc
   terraform output -raw github_oidc_role_arn   # (add this output if not already present)
   ```
3. **Add the resulting role ARN as a GitHub Actions repository variable** named `AWS_ROLE_ARN`: repo Settings → Secrets and variables → Actions → Variables tab → New repository variable. It's an ARN, not a secret, so a variable (not a secret) is the right place for it.
4. Manually run the **`aws-oidc-check`** workflow (Actions tab → Terraform → Run workflow) and confirm the `aws sts get-caller-identity` step succeeds — that's the end-to-end proof the trust policy is correctly scoped.
5. When a future ticket needs the role to actually do something (push to S3, deploy ECS, etc.), extend `managed_policy_arns` on the `github_oidc` module call rather than widening the trust policy — keep permissions additive and specific to what's actually used.
