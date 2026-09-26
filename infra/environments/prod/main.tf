data "aws_caller_identity" "current" {}

# Everything in this environment is validate-only for now — no real PROD
# apply exists yet. `dev`'s environment is fully applied for real (see
# infra/README.md); prod assumes its own separate AWS account eventually,
# but for now shares dev's single account, hence the bucket names below
# being environment-qualified.

module "github_oidc" {
  source = "../../modules/github-oidc"

  role_name        = "github-actions-dataset-quality-prod"
  allowed_branches = ["main"]

  tags = {
    Environment = "prod"
  }
}

module "network" {
  source = "../../modules/network"

  environment = "prod"
  vpc_cidr    = var.vpc_cidr
  aws_region  = var.aws_region

  tags = {
    Environment = "prod"
  }
}

module "compute" {
  source = "../../modules/compute"

  environment = "prod"

  tags = {
    Environment = "prod"
  }
}

module "data" {
  source = "../../modules/data"

  environment         = "prod"
  vpc_id              = module.network.vpc_id
  vpc_cidr            = module.network.vpc_cidr
  private_subnet_ids  = module.network.private_subnet_ids
  multi_az            = true
  instance_class      = "db.t4g.small"
  skip_final_snapshot = false

  tags = {
    Environment = "prod"
  }
}

# dvc-cache: DVC's own content-addressed cache. Versioned (protects against
# accidental overwrites) but NOT Object Lock — dvc gc needs to be able to
# delete orphaned cache objects, which Object Lock would block.
#
# `dev`/`prod` currently share one AWS account, so the environment must be
# part of the bucket name — otherwise both environments compute the same
# global S3 name and the second `apply` collides with the first (caught in
# OPS-08 PR review).
module "dvc_cache" {
  source = "../../modules/storage"

  bucket_name        = "dvc-cache-prod-${data.aws_caller_identity.current.account_id}"
  enable_versioning  = true
  enable_object_lock = false

  tags = {
    Environment = "prod"
  }
}

# dataset-releases: finalized, published dataset versions. These should
# never be silently altered or deleted, so Object Lock (WORM) is appropriate
# here in a way it isn't for dvc-cache above.
module "dataset_releases" {
  source = "../../modules/storage"

  bucket_name        = "dataset-releases-prod-${data.aws_caller_identity.current.account_id}"
  enable_versioning  = true
  enable_object_lock = true

  tags = {
    Environment = "prod"
  }
}
