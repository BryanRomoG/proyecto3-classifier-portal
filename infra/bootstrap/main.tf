data "aws_caller_identity" "current" {}

# The bucket every environment's `backend "s3" {}` block points at.
# Versioning is Terraform's own recommended state-recovery mechanism — a bad
# apply or manual edit can be rolled back to a previous state version.
module "tfstate" {
  source = "../modules/storage"

  bucket_name        = "dataset-quality-tfstate-${data.aws_caller_identity.current.account_id}"
  enable_versioning  = true
  enable_object_lock = false

  tags = {
    Purpose = "terraform-state"
  }
}

# State locking so two concurrent `terraform apply` runs can't corrupt each
# other's state. PAY_PER_REQUEST — this table sees at most a few writes per
# apply, provisioned capacity would just be a fixed cost for no benefit.
resource "aws_dynamodb_table" "tflock" {
  name         = "dataset-quality-tflock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = {
    Purpose = "terraform-state-locking"
  }
}
