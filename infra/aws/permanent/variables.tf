# GitHub's OIDC tokens for this repository name the account and the repository
# by their IDs as well as their names (GitHub's immutable subject). Trusting the
# IDs means a deleted and re-created account or repository of the same name
# cannot assume the CI plan role. Read the prefix with:
#   gh api repos/<owner>/<name>/actions/oidc/customization/sub --jq .sub_claim_prefix
variable "github_oidc_subject_prefix" {
  description = "The subject prefix of this repository's GitHub OIDC tokens, repo:<owner>@<owner ID>/<name>@<repository ID>. Its pull requests and main branch may assume the CI plan role (REQ-152.1)."
  type        = string
  default     = "repo:andrefellipe@36719048/multi-cloud-agentic-sre@1452188891"

  validation {
    condition     = can(regex("^repo:[A-Za-z0-9-]+@[0-9]+/[A-Za-z0-9._-]+@[0-9]+$", var.github_oidc_subject_prefix))
    error_message = "Give GitHub's immutable subject prefix, repo:<owner>@<owner ID>/<name>@<repository ID>, as the gh api command above prints it."
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
