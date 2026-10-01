data "aws_caller_identity" "current" {}

# --- Applied for real (see infra/README.md) ---

module "github_oidc" {
  source = "../../modules/github-oidc"

  role_name        = "github-actions-dataset-quality-dev"
  allowed_branches = ["main"]

  tags = {
    Environment = "dev"
  }
}

# --- Validate-only below: not applied yet, no AWS spend until OPS-08 needs it running ---

module "network" {
  source = "../../modules/network"

  environment = "dev"
  vpc_cidr    = var.vpc_cidr
  aws_region  = var.aws_region

  tags = {
    Environment = "dev"
  }
}

module "compute" {
  source = "../../modules/compute"

  environment = "dev"

  tags = {
    Environment = "dev"
  }
}

module "data" {
  source = "../../modules/data"

  environment         = "dev"
  vpc_id              = module.network.vpc_id
  vpc_cidr            = module.network.vpc_cidr
  private_subnet_ids  = module.network.private_subnet_ids
  multi_az            = false
  instance_class      = "db.t4g.micro"
  skip_final_snapshot = true

  tags = {
    Environment = "dev"
  }
}

# Applied for real (see infra/README.md). DEV's actual DVC remote is still
# MinIO (see pipeline/.dvc/config) — wiring DVC itself to this bucket is
# OPS-07's job, not this ticket's. `dev`/`prod` currently share one AWS
# account, so the environment must be part of the bucket name — otherwise
# both environments compute the same global S3 name and the second `apply`
# collides with the first (caught in OPS-08 PR review).
module "dvc_cache" {
  source = "../../modules/storage"

  bucket_name        = "dvc-cache-dev-${data.aws_caller_identity.current.account_id}"
  enable_versioning  = true
  enable_object_lock = false

  tags = {
    Environment = "dev"
  }
}

module "dataset_releases" {
  source = "../../modules/storage"

  bucket_name        = "dataset-releases-dev-${data.aws_caller_identity.current.account_id}"
  enable_versioning  = true
  enable_object_lock = true

  tags = {
    Environment = "dev"
  }
}

# --- OPS-07: scoped S3 permissions for the release-to-PROD workflow ---
#
# The one real OIDC role lives here (this environment's github_oidc module),
# and this project has a single AWS account for now, so it's also the role
# that publishes to PROD's buckets, not a separate prod-account role. The
# github-oidc module only supports attaching pre-made AWS-managed policy
# ARNs (see its main.tf) — there's no inline-policy mechanism there, so a
# customer-managed policy scoped to exactly these 4 real bucket ARNs (never
# a broad managed policy like AmazonS3FullAccess) is defined and attached
# here instead. `role = "github-actions-dataset-quality-dev"` is the same
# literal already passed as this module's own `role_name` input above.
data "aws_iam_policy_document" "release_publish" {
  statement {
    sid     = "ListReleaseBuckets"
    effect  = "Allow"
    actions = ["s3:ListBucket"]
    resources = [
      module.dvc_cache.bucket_arn,
      module.dataset_releases.bucket_arn,
      "arn:aws:s3:::dvc-cache-prod-${data.aws_caller_identity.current.account_id}",
      "arn:aws:s3:::dataset-releases-prod-${data.aws_caller_identity.current.account_id}",
    ]
  }

  statement {
    sid     = "ReadWriteReleaseObjects"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:PutObject"]
    resources = [
      "${module.dvc_cache.bucket_arn}/*",
      "${module.dataset_releases.bucket_arn}/*",
      "arn:aws:s3:::dvc-cache-prod-${data.aws_caller_identity.current.account_id}/*",
      "arn:aws:s3:::dataset-releases-prod-${data.aws_caller_identity.current.account_id}/*",
    ]
  }
}

resource "aws_iam_policy" "release_publish" {
  name        = "dataset-quality-release-publish"
  description = "Least-privilege S3 access for the release workflow: dvc-cache/dataset-releases in dev and prod only."
  policy      = data.aws_iam_policy_document.release_publish.json
}

resource "aws_iam_role_policy_attachment" "release_publish" {
  role       = "github-actions-dataset-quality-dev"
  policy_arn = aws_iam_policy.release_publish.arn
}

# --- Project 3: separate OIDC role for the classifier-portal repo ---
#
# Project 3 is its own repository (BryanRomoG/proyecto3-classifier-portal)
# and needs its own GitHub Actions -> AWS trust. The existing role/provider
# above are left exactly as they are. The `github-oidc` module bundles the
# OIDC provider and its role into one unit, and an AWS account can only have
# one GitHub OIDC provider per URL — so a second module call would try to
# create a duplicate provider. The new role is therefore declared directly
# here and reuses the provider already created by `module.github_oidc` via
# its `oidc_provider_arn` output.
#
# The trust `sub` condition mirrors the exact format the module documents
# (see modules/github-oidc/main.tf): GitHub appends immutable numeric IDs
# after `@` (repo:OWNER@OWNER_ID/REPO@REPO_ID:ref:...). Both IDs are fixed
# here to the values returned by GitHub, so renaming/recreating a repository
# cannot inherit this trust. Scoped to Project 3's repo on `main` only.
data "aws_iam_policy_document" "classifier_portal_assume_role" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [module.github_oidc.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "repo:BryanRomoG@178322887/proyecto3-classifier-portal@1387653048:ref:refs/heads/main"
      ]
    }
  }
}

resource "aws_iam_role" "classifier_portal" {
  name               = "github-actions-classifier-portal"
  assume_role_policy = data.aws_iam_policy_document.classifier_portal_assume_role.json

  tags = {
    Environment = "dev"
  }
}

# Same least-privilege S3 policy the pipeline role uses — attached to the new
# role rather than widened into a new/broader policy.
resource "aws_iam_role_policy_attachment" "classifier_portal_release_publish" {
  role       = aws_iam_role.classifier_portal.name
  policy_arn = aws_iam_policy.release_publish.arn
}
