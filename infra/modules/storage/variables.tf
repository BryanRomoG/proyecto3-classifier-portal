variable "bucket_name" {
  description = "Globally-unique S3 bucket name. Callers decide the real name — this module doesn't invent one."
  type        = string
}

variable "enable_versioning" {
  type    = bool
  default = false
}

variable "enable_object_lock" {
  description = <<-EOT
    S3 Object Lock (WORM) — for buckets that must never be silently altered or
    deleted, e.g. published dataset releases. NOT for working caches: Object
    Lock blocks deletion until the retention period expires, which would
    break routine garbage collection on a cache bucket. Must be set at bucket
    creation time — cannot be enabled on an existing bucket.
  EOT
  type        = bool
  default     = false
}

variable "object_lock_retention_days" {
  description = "Default retention period (days) for objects, when enable_object_lock is true."
  type        = number
  default     = 90
}

variable "tags" {
  description = "Extra tags merged into every resource in this module."
  type        = map(string)
  default     = {}
}
