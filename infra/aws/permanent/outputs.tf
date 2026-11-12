# Read by infra/aws/lab through terraform_remote_state, and by you. Outputs that
# carry your domain or an account-bearing ARN are sensitive, so the public plan
# comment never prints them; read one with `terraform output -raw <name>`.

output "rancher_url" {
  description = "Rancher's address, https://rancher.<domain>."
  value       = local.rancher_url
  sensitive   = true
}

output "rancher_certificate_arn" {
  description = "The validated ACM certificate for rancher.<domain>, used by both load balancers."
  value       = aws_acm_certificate_validation.rancher.certificate_arn
  sensitive   = true
}

output "public_zone_id" {
  description = "The public hosted zone of your domain."
  value       = data.aws_route53_zone.public.zone_id
}

output "cognito_user_pool_id" {
  description = "The user pool Rancher signs in through."
  value       = aws_cognito_user_pool.sre_lab.id
}

output "cognito_sign_in_domain" {
  description = "The hosted sign-in domain of the user pool."
  value       = "https://${aws_cognito_user_pool_domain.sre_lab.domain}.auth.${local.region}.amazoncognito.com"
}

output "grafana_url" {
  description = "The Managed Grafana workspace."
  value       = "https://${aws_grafana_workspace.sre_lab.endpoint}"
}

output "ci_plan_role_arn" {
  description = "Store this as the repository secret AWS_PLAN_ROLE_ARN; the workflow masks the account ID it carries."
  value       = aws_iam_role.ci_plan.arn
  sensitive   = true
}

output "ci_plan_role_name" {
  description = "Name of the CI plan role; infra/aws/lab refuses it the Rancher secrets."
  value       = aws_iam_role.ci_plan.name
}
