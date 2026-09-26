variable "github_org" {
  type    = string
  default = "White-eclipse1"
}

variable "github_repo" {
  type    = string
  default = "Proyecto-02-dataset-Quality"
}

variable "role_name" {
  description = "Name for the IAM role GitHub Actions assumes."
  type        = string
}

variable "allowed_branches" {
  description = "Branches allowed to assume this role, scoped tightly by design (least privilege). workflow_dispatch's sub claim uses the branch it was dispatched from, so this must include whatever branch triggers the OIDC-check workflow."
  type        = list(string)
  default     = ["main"]
}

variable "managed_policy_arns" {
  description = "Permissions attached to the role. Empty by default — sts:GetCallerIdentity needs no permissions at all, so this stays empty until a later ticket (OPS-06/07/08) needs the role to actually do something, added incrementally rather than granted upfront."
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Extra tags merged into every resource in this module."
  type        = map(string)
  default     = {}
}
