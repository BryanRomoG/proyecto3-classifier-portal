# Generic private S3 bucket module. Deliberately name-agnostic: OPS-08
# instantiates this twice, once for `dvc-cache` and once for
# `dataset-releases`, with the immutability/versioning settings each of
# those actually needs. Nothing here hardcodes either name.

resource "aws_s3_bucket" "this" {
  bucket = var.bucket_name

  # Object Lock can only be turned on at creation time, never retrofitted —
  # has to live on this resource regardless of whether enable_object_lock
  # is actually true for a given caller.
  object_lock_enabled = var.enable_object_lock

  tags = var.tags
}

resource "aws_s3_bucket_versioning" "this" {
  bucket = aws_s3_bucket.this.id

  # Object Lock requires versioning — force it on even if a caller forgot,
  # rather than letting AWS reject the apply with an unclear error.
  versioning_configuration {
    status = var.enable_versioning || var.enable_object_lock ? "Enabled" : "Suspended"
  }
}

resource "aws_s3_bucket_object_lock_configuration" "this" {
  count  = var.enable_object_lock ? 1 : 0
  bucket = aws_s3_bucket.this.id

  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = var.object_lock_retention_days
    }
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket = aws_s3_bucket.this.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
