variable "environment" {
  description = "Environment name (dev/prod), used for naming and tags."
  type        = string
}

variable "vpc_id" {
  type = string
}

variable "vpc_cidr" {
  description = "VPC CIDR block, used to scope the RDS security group's ingress rule."
  type        = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "multi_az" {
  description = "Whether RDS runs Multi-AZ. false for dev, true for prod."
  type        = bool
  default     = false
}

variable "instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "allocated_storage_gb" {
  type    = number
  default = 20
}

variable "engine_version" {
  description = "MariaDB engine version."
  type        = string
  default     = "10.11"
}

variable "db_name" {
  type    = string
  default = "image_repo"
}

variable "db_username" {
  type    = string
  default = "admin"
}

variable "skip_final_snapshot" {
  description = "true for dev (disposable), false for prod."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Extra tags merged into every resource in this module."
  type        = map(string)
  default     = {}
}
