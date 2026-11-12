# terraform test for infra/aws/permanent, with a mocked AWS provider: no
# credentials, no AWS call, no state. It evaluates what `terraform validate`
# cannot: the sensitive SSM values in the certificate, Cognito and Grafana, the
# single DNS validation record, the policies' conditions, and the alert path
# (topic policy, alert manager routing and template, rule labels). Values are synthetic.
#
# Run it with: terraform -chdir=infra/aws/permanent init -backend=false && terraform -chdir=infra/aws/permanent test

mock_provider "aws" {
  # The provider checks that policies are JSON objects; a mock returns random text.
  mock_data "aws_iam_policy_document" {
    defaults = {
      json          = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
      minified_json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }

  # ACM returns one validation option per name on the certificate.
  mock_resource "aws_acm_certificate" {
    defaults = {
      arn = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
      domain_validation_options = [
        {
          domain_name           = "rancher.example.com"
          resource_record_name  = "_0123456789abcdef.rancher.example.com."
          resource_record_type  = "CNAME"
          resource_record_value = "_fedcba9876543210.acm-validations.aws."
        },
      ]
    }
  }

  mock_resource "aws_iam_openid_connect_provider" {
    defaults = {
      arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
    }
  }

  mock_resource "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::123456789012:role/mock"
    }
  }

  mock_resource "aws_prometheus_workspace" {
    defaults = {
      id                  = "ws-00000000-0000-0000-0000-000000000000"
      arn                 = "arn:aws:aps:us-east-1:123456789012:workspace/ws-00000000-0000-0000-0000-000000000000"
      prometheus_endpoint = "https://aps-workspaces.us-east-1.amazonaws.com/workspaces/ws-00000000-0000-0000-0000-000000000000/"
    }
  }

  mock_resource "aws_sns_topic" {
    defaults = {
      arn = "arn:aws:sns:us-east-1:123456789012:sre-lab-alerts"
    }
  }

  mock_resource "aws_cloudwatch_log_group" {
    defaults = {
      arn = "arn:aws:logs:us-east-1:123456789012:log-group:mock"
    }
  }
}

override_data {
  target = data.aws_caller_identity.current
  values = {
    account_id = "123456789012"
  }
}

override_data {
  target = data.aws_partition.current
  values = {
    partition = "aws"
  }
}

override_data {
  target = data.aws_region.current
  values = {
    region = "us-east-1"
  }
}

override_data {
  target = data.aws_ssm_parameter.domain_name
  values = {
    value = "example.com"
  }
}

override_data {
  target = data.aws_ssm_parameter.cognito_user_email
  values = {
    value = "operator@example.com"
  }
}

override_data {
  target = data.aws_ssm_parameter.idc_user_id
  values = {
    value = "00000000-1111-2222-3333-444444444444"
  }
}

override_data {
  target = data.aws_route53_zone.public
  values = {
    zone_id = "Z0000000EXAMPLE"
  }
}

run "permanent_matches_the_design" {
  command = plan

  # REQ-021.1: sign-in requires MFA with an authenticator app; you are the only user.
  assert {
    condition     = aws_cognito_user_pool.sre_lab.mfa_configuration == "ON" && aws_cognito_user_pool.sre_lab.software_token_mfa_configuration[0].enabled
    error_message = "The user pool must require MFA with an authenticator app."
  }

  assert {
    condition     = aws_cognito_user_pool.sre_lab.admin_create_user_config[0].allow_admin_create_user_only && aws_cognito_user_pool.sre_lab.deletion_protection == "ACTIVE"
    error_message = "Nobody may sign up, and the pool may not be deleted by accident."
  }

  assert {
    condition     = nonsensitive(aws_cognito_user.operator.attributes["email"]) == "operator@example.com" && aws_cognito_user.operator.username == "operator"
    error_message = "The operator user takes its email address from the SSM parameter."
  }

  assert {
    condition     = aws_cognito_user_pool_client.rancher.generate_secret && nonsensitive(aws_cognito_user_pool_client.rancher.callback_urls) == toset(["https://rancher.example.com/verify-auth"])
    error_message = "Rancher's app client is confidential and calls back to Rancher's /verify-auth."
  }

  assert {
    condition     = aws_cognito_user_pool_client.rancher.allowed_oauth_flows == toset(["code"])
    error_message = "Only the authorization code flow is allowed."
  }

  assert {
    condition     = nonsensitive(aws_acm_certificate.rancher.domain_name) == "rancher.example.com" && aws_acm_certificate.rancher.validation_method == "DNS"
    error_message = "The certificate covers rancher.<domain>, built from the SSM parameter, and validates through DNS."
  }

  # REQ-152.1: only this repository's pull requests and main may assume the CI role.
  assert {
    condition = toset(one([
      for condition in data.aws_iam_policy_document.ci_plan_trust.statement[0].condition :
      condition.values if condition.variable == "token.actions.githubusercontent.com:sub"
    ])) == toset(["repo:andrefellipe@36719048/multi-cloud-agentic-sre@1452188891:pull_request", "repo:andrefellipe@36719048/multi-cloud-agentic-sre@1452188891:ref:refs/heads/main"])
    error_message = "The CI plan role trusts only this repository's pull requests and main."
  }

  assert {
    condition     = aws_iam_role_policy_attachment.ci_plan_read_only.policy_arn == "arn:aws:iam::aws:policy/ReadOnlyAccess"
    error_message = "The CI plan role is read-only."
  }

  assert {
    condition = alltrue([
      for statement in data.aws_iam_policy_document.ci_plan.statement :
      statement.effect == "Deny" || statement.resources == toset(["arn:aws:s3:::multi-cloud-agentic-sre-tfstate/*.tflock"])
    ])
    error_message = "The CI plan role's only write is the state lock files."
  }

  assert {
    condition = toset(one([
      for statement in data.aws_iam_policy_document.ci_plan.statement : one(statement.condition).values
      if statement.sid == "DenyS3OutsideThisAccount"
    ])) == toset(["123456789012"])
    error_message = "The CI plan role must be refused S3 buckets of other accounts."
  }

  assert {
    condition = anytrue([
      for statement in data.aws_iam_policy_document.ci_plan.statement :
      statement.sid == "DenySecretValues" && statement.effect == "Deny" && statement.resources == toset(["*"])
      && statement.actions == toset(["secretsmanager:GetSecretValue", "secretsmanager:BatchGetSecretValue"])
    ])
    error_message = "The CI plan role must be refused every secret value."
  }

  # Decryption only through IAM Identity Center, which reading the Grafana admin needs.
  assert {
    condition = anytrue([
      for statement in data.aws_iam_policy_document.ci_plan.statement :
      statement.sid == "DenyDecryptOutsideIdentityCenter" && statement.effect == "Deny"
      && statement.actions == toset(["kms:Decrypt"]) && statement.resources == toset(["*"])
      && one(statement.condition).test == "StringNotLike" && one(statement.condition).variable == "kms:ViaService"
      && one(statement.condition).values == tolist(["sso.*.amazonaws.com"])
    ])
    error_message = "The CI plan role may decrypt only through IAM Identity Center."
  }

  # Managed Grafana, signing in through IAM Identity Center, with you as admin.
  assert {
    condition     = aws_grafana_workspace.sre_lab.authentication_providers == tolist(["AWS_SSO"]) && aws_grafana_workspace.sre_lab.grafana_version == "13.2"
    error_message = "Grafana signs in through IAM Identity Center, at the pinned version."
  }

  assert {
    condition     = aws_grafana_role_association.admin.role == "ADMIN" && nonsensitive(aws_grafana_role_association.admin.user_ids) == toset(["00000000-1111-2222-3333-444444444444"])
    error_message = "You are the Grafana admin, by your Identity Center user ID from SSM."
  }

  # Transaction Search for the agent sessions' spans.
  assert {
    condition     = aws_xray_trace_segment_destination.cloudwatch_logs.destination == "CloudWatchLogs"
    error_message = "Trace segments must go to CloudWatch Logs (Transaction Search)."
  }
}

# REQ-152.1: the CI role trusts this repository only by GitHub's IDs. A subject
# with names alone, which a re-created repository of the same name would match,
# is refused.
run "the_ci_role_refuses_a_subject_without_ids" {
  command = plan

  variables {
    github_oidc_subject_prefix = "repo:andrefellipe/multi-cloud-agentic-sre"
  }

  expect_failures = [var.github_oidc_subject_prefix]
}

run "one_validation_record_proves_the_certificate" {
  command = apply

  assert {
    condition     = aws_route53_record.rancher_validation.name == "_0123456789abcdef.rancher.example.com." && aws_route53_record.rancher_validation.type == "CNAME"
    error_message = "The validation record must come from the certificate's single validation option."
  }

  assert {
    condition     = aws_route53_record.rancher_validation.zone_id == "Z0000000EXAMPLE"
    error_message = "The validation record goes in the public zone."
  }
}

run "alert_path_and_telemetry_match_the_design" {
  command = apply

  # REQ-030.1, SD-2: only this workspace's alert manager publishes to the lab topic.
  assert {
    condition = (
      one(data.aws_iam_policy_document.lab_alerts.statement[0].principals).identifiers == toset(["aps.amazonaws.com"])
      && toset(data.aws_iam_policy_document.lab_alerts.statement[0].actions) == toset(["sns:Publish", "sns:GetTopicAttributes"])
    )
    error_message = "Only the Managed Prometheus service may publish to the lab topic."
  }

  assert {
    condition = {
      for condition in data.aws_iam_policy_document.lab_alerts.statement[0].condition :
      condition.variable => toset(condition.values)
      } == {
      "aws:SourceArn"     = toset(["arn:aws:aps:us-east-1:123456789012:workspace/ws-00000000-0000-0000-0000-000000000000"])
      "aws:SourceAccount" = toset(["123456789012"])
    }
    error_message = "The topic accepts the alert manager of this workspace in this account only (confused-deputy protection)."
  }

  assert {
    condition = (
      data.aws_iam_policy_document.lab_alerts.statement[1].effect == "Deny"
      && one(data.aws_iam_policy_document.lab_alerts.statement[1].condition).variable == "aws:SecureTransport"
      && one(data.aws_iam_policy_document.lab_alerts.statement[1].condition).values == tolist(["false"])
    )
    error_message = "The lab topic must refuse publishing without TLS (SD-2)."
  }

  # PD-4: grouped by service and alert name, 10 s wait, 15 s interval, 1 h repeat, to the lab topic only.
  assert {
    condition = (
      yamldecode(yamldecode(aws_prometheus_alert_manager_definition.sre_lab.definition).alertmanager_config).route.group_by == ["service", "alertname"]
      && yamldecode(yamldecode(aws_prometheus_alert_manager_definition.sre_lab.definition).alertmanager_config).route.group_wait == "10s"
      && yamldecode(yamldecode(aws_prometheus_alert_manager_definition.sre_lab.definition).alertmanager_config).route.group_interval == "15s"
      && yamldecode(yamldecode(aws_prometheus_alert_manager_definition.sre_lab.definition).alertmanager_config).route.repeat_interval == "1h"
    )
    error_message = "The alert manager routing must follow PD-4."
  }

  assert {
    condition = (
      one(yamldecode(yamldecode(aws_prometheus_alert_manager_definition.sre_lab.definition).alertmanager_config).receivers).name == "lab-topic"
      && one(one(yamldecode(yamldecode(aws_prometheus_alert_manager_definition.sre_lab.definition).alertmanager_config).receivers).sns_configs).topic_arn == "arn:aws:sns:us-east-1:123456789012:sre-lab-alerts"
      && one(one(yamldecode(yamldecode(aws_prometheus_alert_manager_definition.sre_lab.definition).alertmanager_config).receivers).sns_configs).sigv4.region == "us-east-1"
      && one(one(yamldecode(yamldecode(aws_prometheus_alert_manager_definition.sre_lab.definition).alertmanager_config).receivers).sns_configs).send_resolved
    )
    error_message = "The only receiver is the lab topic, signed for us-east-1, with resolved alerts sent too."
  }

  # Contract C1: the message body is the JSON template, with RFC 3339 times.
  assert {
    condition = alltrue([
      for expected in [
        "define \"sns.default.message\"",
        "define \"sns.default.subject\"",
        "$alert.Labels.SortedPairs",
        "$alert.StartsAt.UTC.Format \"2006-01-02T15:04:05.999999999Z07:00\"",
        "\"fingerprint\": \"{{ $alert.Fingerprint }}\"",
      ] : strcontains(yamldecode(aws_prometheus_alert_manager_definition.sre_lab.definition).template_files.default_template, expected)
    ])
    error_message = "The SNS message must be the contract C1 JSON template."
  }

  # BR8.7: the demo-fault rule sets severity and service; cluster and cloud come from its series.
  assert {
    condition = (
      aws_prometheus_rule_group_namespace.demo_fault.name == "demo-fault"
      && yamldecode(aws_prometheus_rule_group_namespace.demo_fault.data).groups[0].rules[0].labels == { severity = "critical", service = "payment" }
      && strcontains(yamldecode(aws_prometheus_rule_group_namespace.demo_fault.data).groups[0].rules[0].expr, "sum by (cluster, cloud)")
    )
    error_message = "The demo-fault rule must carry the labels of contract C1 (BR8.7)."
  }

  # REQ-130.2: demo logs kept 3 days; the workspace logs its own errors.
  assert {
    condition = (
      aws_cloudwatch_log_group.demo.name == "/sre-lab/otel-demo"
      && aws_cloudwatch_log_group.demo.retention_in_days == 3
      && aws_cloudwatch_log_stream.demo_eks.name == "sre-lab-eks"
      && aws_cloudwatch_log_stream.demo_eks.log_group_name == "/sre-lab/otel-demo"
    )
    error_message = "The demo's logs go to /sre-lab/otel-demo, stream sre-lab-eks, kept 3 days."
  }

  assert {
    condition = (
      aws_prometheus_workspace.sre_lab.alias == "sre-lab"
      && aws_prometheus_workspace.sre_lab.logging_configuration[0].log_group_arn == "arn:aws:logs:us-east-1:123456789012:log-group:mock:*"
      && startswith(aws_cloudwatch_log_group.prometheus.name, "/aws/vendedlogs/prometheus/")
    )
    error_message = "The workspace logs its alert manager and rule errors to its own log group."
  }

  # The dashboards root applies as this service account, with a token made at apply time.
  assert {
    condition     = aws_grafana_workspace_service_account.dashboards.grafana_role == "ADMIN" && aws_grafana_workspace_service_account.dashboards.name == "terraform-dashboards"
    error_message = "The dashboards service account needs the Admin role for its data sources."
  }
}
