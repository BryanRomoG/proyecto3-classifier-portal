variable "environment" {
  description = "Environment name (dev/prod), used for naming and tags."
  type        = string
}

variable "aws_region" {
  description = "Region this network lives in — needed for the S3 Gateway Endpoint's service name."
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for the public subnets, one per AZ."
  type        = list(string)
  default     = ["10.0.0.0/24", "10.0.1.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for the private subnets, one per AZ."
  type        = list(string)
  default     = ["10.0.10.0/24", "10.0.11.0/24"]
}

variable "tags" {
  description = "Extra tags merged into every resource in this module."
  type        = map(string)
  default     = {}
}
