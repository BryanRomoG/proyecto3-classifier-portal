terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Deliberately local state: this is the one root that creates the S3
  # bucket + DynamoDB table every *other* root's remote backend depends on.
  # It can't depend on the thing it's creating (chicken-and-egg) — applied
  # once, by hand, before environments/dev and environments/prod configure
  # their own `backend "s3" {}` blocks against these resources.
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "dataset-quality-pipeline"
      Environment = "shared"
      ManagedBy   = "terraform"
      Purpose     = "terraform-state-backend"
    }
  }
}
