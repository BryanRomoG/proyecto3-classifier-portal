variable "environment" {
  description = "Environment name (dev/prod), used for naming and tags."
  type        = string
}

variable "tags" {
  description = "Extra tags merged into every resource in this module."
  type        = map(string)
  default     = {}
}
