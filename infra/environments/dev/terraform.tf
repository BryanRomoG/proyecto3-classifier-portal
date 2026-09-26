terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  # Backend blocks can't use variables/data sources — must be static
  # literals — so the account ID is hardcoded here directly. Not a secret,
  # just a config value, same as bucket names elsewhere in this repo.
  # Created by infra/bootstrap/ (see infra/README.md for the one-time
  # `terraform init -migrate-state` step).
  backend "s3" {
    bucket         = "dataset-quality-tfstate-685538571046"
    key            = "dev/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "dataset-quality-tflock"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "dataset-quality-pipeline"
      Environment = "dev"
      ManagedBy   = "terraform"
    }
  }
}
