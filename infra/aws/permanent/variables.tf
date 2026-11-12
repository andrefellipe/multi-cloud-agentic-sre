variable "github_repository" {
  description = "The GitHub repository, as owner/name, whose pull requests and main branch may assume the CI plan role (REQ-152.1)."
  type        = string
  default     = "andrefellipe/multi-cloud-agentic-sre"

  validation {
    condition     = can(regex("^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$", var.github_repository))
    error_message = "Give the repository as owner/name."
  }
}

variable "state_bucket_name" {
  description = "The Terraform state bucket from infra/aws/bootstrap; the CI plan role may write lock files there."
  type        = string
  default     = "multi-cloud-agentic-sre-tfstate"
}

variable "cognito_domain_prefix" {
  description = "Prefix of the Cognito hosted sign-in domain (<prefix>.auth.us-east-1.amazoncognito.com). It is public and must be unused in the Region."
  type        = string
  default     = "multi-cloud-agentic-sre"

  validation {
    condition     = can(regex("^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", var.cognito_domain_prefix)) && !can(regex("aws|amazon|cognito", var.cognito_domain_prefix))
    error_message = "Use lowercase letters, digits and hyphens, without aws, amazon or cognito."
  }
}

variable "operator_username" {
  description = "Cognito user name of the human operator. The email address stays in the SSM parameter /sre-lab/cognito-user-email."
  type        = string
  default     = "operator"
}

variable "grafana_version" {
  description = "Managed Grafana version, pinned. 13.2 is the newest that grafana:ListVersions offered in us-east-1 on 2026-11-11."
  type        = string
  default     = "13.2"
}
