variable "state_bucket_name" {
  description = "Name of the Terraform state bucket. It must match the bucket in every root's backend block. The name is public, so check that you own it before any init (README.md)."
  type        = string
  default     = "multi-cloud-agentic-sre-tfstate"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.state_bucket_name))
    error_message = "A bucket name is 3 to 63 lowercase letters, digits and hyphens."
  }
}

variable "coding_agent_permission_set_name" {
  description = "IAM Identity Center permission set the coding agent signs in with (read-only). Its role is denied the state objects, because state can hold configuration secrets (REQ-013.1)."
  type        = string
  default     = "SreLabReadOnly"

  validation {
    condition     = can(regex("^[A-Za-z0-9+=,.@_-]{1,32}$", var.coding_agent_permission_set_name))
    error_message = "A permission set name is 1 to 32 characters: letters, digits and +=,.@_-"
  }
}

variable "noncurrent_version_days" {
  description = "Days an overwritten or deleted state version is kept, to roll state back."
  type        = number
  default     = 90

  validation {
    condition     = var.noncurrent_version_days >= 30
    error_message = "Keep old state versions for at least 30 days."
  }
}
