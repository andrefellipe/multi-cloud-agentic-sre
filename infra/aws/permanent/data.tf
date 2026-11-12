data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

data "aws_region" "current" {}

# Your personal values: plain String SSM parameters you create once, never in Git
# (infrastructure-specification.md). They are read with `value`, which Terraform
# treats as sensitive, so the public plan comment never shows them. The
# allow-list parameter is read by infra/aws/lab, the only root that uses it.
data "aws_ssm_parameter" "domain_name" {
  name = "/sre-lab/domain-name"
}

data "aws_ssm_parameter" "cognito_user_email" {
  name = "/sre-lab/cognito-user-email"
}

data "aws_ssm_parameter" "idc_user_id" {
  name = "/sre-lab/idc-user-id"
}

# The public hosted zone of your domain, created when you registered it.
data "aws_route53_zone" "public" {
  name         = local.domain_name
  private_zone = false
}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  region     = data.aws_region.current.region

  # Built from the SSM value, never from the zone's name, so it stays sensitive.
  domain_name  = data.aws_ssm_parameter.domain_name.value
  rancher_fqdn = "rancher.${local.domain_name}"
  rancher_url  = "https://${local.rancher_fqdn}"
}
