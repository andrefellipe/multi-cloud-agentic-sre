data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

data "aws_region" "current" {}

# Your personal values: plain String SSM parameters you create once, never in Git.
# Read with `value`, which Terraform treats as sensitive, so the public plan
# comment never shows them.
data "aws_ssm_parameter" "domain_name" {
  name = "/sre-lab/domain-name"
}

# Comma-separated IPv4 CIDRs, for example "203.0.113.7/32,198.51.100.0/28".
data "aws_ssm_parameter" "allowlist_cidrs" {
  name = "/sre-lab/allowlist-cidrs"
}

# Canonical's public parameter for the current Ubuntu 24.04 LTS image. The image
# ID is public, so `insecure_value` keeps it readable in the plan.
data "aws_ssm_parameter" "ubuntu_ami" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

data "aws_eks_cluster_versions" "standard" {
  version_status = "STANDARD_SUPPORT"
}

# The lab reads what it needs from the permanent layer's outputs (SC-5).
data "terraform_remote_state" "permanent" {
  backend = "s3"

  config = {
    bucket = "multi-cloud-agentic-sre-tfstate"
    key    = "permanent/terraform.tfstate"
    region = "us-east-1"
  }
}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  region     = data.aws_region.current.region

  domain_name  = data.aws_ssm_parameter.domain_name.value
  rancher_fqdn = "rancher.${local.domain_name}"

  allowlist_cidrs = [
    for cidr in split(",", data.aws_ssm_parameter.allowlist_cidrs.value) : trimspace(cidr)
    if trimspace(cidr) != ""
  ]
  # One bit leaves the sensitive value: whether the list is usable.
  allowlist_is_valid = nonsensitive(
    length(local.allowlist_cidrs) > 0 && alltrue([
      for cidr in local.allowlist_cidrs :
      can(cidrnetmask(cidr)) && try(tonumber(split("/", cidr)[1]) >= 16, false)
    ])
  )

  certificate_arn  = data.terraform_remote_state.permanent.outputs.rancher_certificate_arn
  public_zone_id   = data.terraform_remote_state.permanent.outputs.public_zone_id
  ci_plan_role_arn = "arn:${local.partition}:iam::${local.account_id}:role/${data.terraform_remote_state.permanent.outputs.ci_plan_role_name}"

  # IAM Identity Center names a permission set's role AWSReservedSSO_<set>_<suffix>.
  coding_agent_role_pattern = "arn:${local.partition}:iam::${local.account_id}:role/aws-reserved/sso.amazonaws.com/*AWSReservedSSO_${var.coding_agent_permission_set_name}_*"

  cluster_name = "sre-lab-eks"
  vpc_cidr     = "10.40.0.0/16"
  # Zone IDs name the same physical zones in every account. use1-az3 is left
  # out: EKS does not place control planes there.
  zone_ids     = ["use1-az1", "use1-az2"]
  subnet_cidrs = ["10.40.0.0/20", "10.40.16.0/20"]
}
