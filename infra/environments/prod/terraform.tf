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

  # Same bootstrap bucket/table as dev for now (single AWS account in this
  # project) — a real multi-account rollout would point this at prod's own
  # account's backend instead. Different `key` keeps the two state files
  # separate regardless. See dev/terraform.tf for why this can't use a
  # variable/data source.
  backend "s3" {
    bucket         = "dataset-quality-tfstate-685538571046"
    key            = "prod/terraform.tfstate"
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
      Environment = "prod"
      ManagedBy   = "terraform"
    }
  }
}
