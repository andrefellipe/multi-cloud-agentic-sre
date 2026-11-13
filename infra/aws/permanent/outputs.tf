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

output "prometheus_workspace_id" {
  description = "The Managed Prometheus workspace. Read by infra/aws/lab for the Collector's role, and set once in platform/otel-collector/values-aws.yaml."
  value       = aws_prometheus_workspace.sre_lab.id
}

output "prometheus_endpoint" {
  description = "The workspace's Prometheus endpoint; infra/aws/dashboards points Grafana at it."
  value       = aws_prometheus_workspace.sre_lab.prometheus_endpoint
}

output "lab_alerts_topic_arn" {
  description = "The lab topic (LC1) the alert manager publishes to; the intake subscribes to it."
  value       = aws_sns_topic.lab_alerts.arn
  sensitive   = true
}

output "demo_log_group_name" {
  description = "The demo's log group; infra/aws/lab lets the Collector write to it."
  value       = aws_cloudwatch_log_group.demo.name
}

output "grafana_workspace_id" {
  description = "The Managed Grafana workspace, for creating the dashboards root's short-lived token."
  value       = aws_grafana_workspace.sre_lab.id
}

output "grafana_dashboards_service_account_id" {
  description = "The Grafana service account infra/aws/dashboards applies with."
  value       = aws_grafana_workspace_service_account.dashboards.service_account_id
}

output "incident_table_name" {
  description = "The incident table (LC3)."
  value       = aws_dynamodb_table.incidents.name
}

output "dead_letter_queue_url" {
  description = "The dead-letter queue (LC8), for the check after each demo; its URL carries the account ID."
  value       = aws_sqs_queue.dead_letters.url
  sensitive   = true
}

output "session_start_queue_url" {
  description = "The session-start queue (LC4); its URL carries the account ID."
  value       = aws_sqs_queue.session_starts.url
  sensitive   = true
}

output "intake_function_name" {
  description = "The intake function (LC2), which the replay tool invokes."
  value       = aws_lambda_function.intake.function_name
}

output "notifier_function_name" {
  description = "The notifier function (LC9)."
  value       = aws_lambda_function.notifier.function_name
}

output "functions_package" {
  description = "The package `make package` must have built under build/lambda/ before an apply: named after the hash of its sources."
  value       = basename(local.functions_package)
}
