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

  mock_resource "aws_grafana_workspace" {
    defaults = {
      arn = "arn:aws:grafana:us-east-1:123456789012:/workspaces/g-0000000000"
    }
  }

  mock_resource "aws_dynamodb_table" {
    defaults = {
      arn = "arn:aws:dynamodb:us-east-1:123456789012:table/sre-lab-incidents"
    }
  }

  mock_resource "aws_lambda_function" {
    defaults = {
      arn           = "arn:aws:lambda:us-east-1:123456789012:function:mock"
      qualified_arn = "arn:aws:lambda:us-east-1:123456789012:function:mock:$LATEST"
      invoke_arn    = "arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/arn:aws:lambda:us-east-1:123456789012:function:mock/invocations"
    }
  }
}

# The incident pipeline's resources, each with its own ARN, so that the
# assertions below can tell which one a reference points to.
override_resource {
  target = aws_sqs_queue.dead_letters
  values = {
    id  = "https://sqs.us-east-1.amazonaws.com/123456789012/sre-lab-dead-letters"
    url = "https://sqs.us-east-1.amazonaws.com/123456789012/sre-lab-dead-letters"
    arn = "arn:aws:sqs:us-east-1:123456789012:sre-lab-dead-letters"
  }
}

override_resource {
  target = aws_sqs_queue.session_starts
  values = {
    id  = "https://sqs.us-east-1.amazonaws.com/123456789012/sre-lab-session-starts"
    url = "https://sqs.us-east-1.amazonaws.com/123456789012/sre-lab-session-starts"
    arn = "arn:aws:sqs:us-east-1:123456789012:sre-lab-session-starts"
  }
}

override_resource {
  target = aws_sns_topic.ops_alarms
  values = {
    arn = "arn:aws:sns:us-east-1:123456789012:sre-lab-ops-alarms"
  }
}

override_resource {
  target = aws_iam_role.intake
  values = {
    arn = "arn:aws:iam::123456789012:role/sre-lab-intake"
  }
}

override_resource {
  target = aws_lambda_function.intake
  values = {
    arn = "arn:aws:lambda:us-east-1:123456789012:function:sre-lab-intake"
  }
}

override_resource {
  target = aws_lambda_function.notifier
  values = {
    arn = "arn:aws:lambda:us-east-1:123456789012:function:sre-lab-notifier"
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

  # Beyond ReadOnlyAccess, the role may write the state lock files and list the
  # Grafana service accounts, nothing else. That list's resource is known only
  # at apply, so the run alert_path_and_telemetry_match_the_design checks it.
  assert {
    condition = alltrue([
      for statement in data.aws_iam_policy_document.ci_plan.statement :
      statement.effect == "Deny" ? true : (
        statement.sid == "ListGrafanaServiceAccounts"
        ? statement.actions == toset(["grafana:ListWorkspaceServiceAccounts"])
        : statement.resources == toset(["arn:aws:s3:::multi-cloud-agentic-sre-tfstate/*.tflock"])
      )
    ])
    error_message = "The CI plan role's only write is the state lock files, and its only other grant is listing the Grafana service accounts."
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

  # REQ-152.1: CI's plan refreshes that service account by listing the workspace's
  # service accounts, which the CI plan role may do for this workspace only.
  assert {
    condition = anytrue([
      for statement in data.aws_iam_policy_document.ci_plan.statement :
      statement.sid == "ListGrafanaServiceAccounts" && statement.effect != "Deny"
      && statement.actions == toset(["grafana:ListWorkspaceServiceAccounts"])
      && statement.resources == toset(["arn:aws:grafana:us-east-1:123456789012:/workspaces/g-0000000000"])
    ])
    error_message = "The CI plan role may list the service accounts of the sre-lab Grafana workspace only."
  }
}

# The incident pipeline: table, queues, intake, notifier and alarms (u1 PR 3).
run "incident_pipeline_matches_the_design" {
  command = apply

  # REQ-140.3, SC-2: one on-demand table keyed by pk, protected, with expiring inbound events.
  assert {
    condition = (
      aws_dynamodb_table.incidents.billing_mode == "PAY_PER_REQUEST"
      && aws_dynamodb_table.incidents.hash_key == "pk"
      && aws_dynamodb_table.incidents.deletion_protection_enabled
      && one(aws_dynamodb_table.incidents.point_in_time_recovery).enabled
      && one(aws_dynamodb_table.incidents.point_in_time_recovery).recovery_period_in_days == 35
      && one(aws_dynamodb_table.incidents.ttl).attribute_name == "expires_at_epoch"
      && one(aws_dynamodb_table.incidents.ttl).enabled
    )
    error_message = "The incident table must be on demand, keyed by pk, deletion-protected, with 35 days of recovery and the event TTL."
  }

  # REQ-140.2, SC-3: dead letters kept 14 days; session starts retried 3 times, then dead-lettered.
  assert {
    condition = (
      aws_sqs_queue.dead_letters.message_retention_seconds == 1209600
      && aws_sqs_queue.dead_letters.sqs_managed_sse_enabled
      && aws_sqs_queue.session_starts.visibility_timeout_seconds == 30
      && aws_sqs_queue.session_starts.message_retention_seconds == 86400
      && aws_sqs_queue.session_starts.sqs_managed_sse_enabled
      && jsondecode(aws_sqs_queue.session_starts.redrive_policy) == {
        deadLetterTargetArn = "arn:aws:sqs:us-east-1:123456789012:sre-lab-dead-letters"
        maxReceiveCount     = 3
      }
      && jsondecode(aws_sqs_queue_redrive_allow_policy.dead_letters.redrive_allow_policy).sourceQueueArns == ["arn:aws:sqs:us-east-1:123456789012:sre-lab-session-starts"]
    )
    error_message = "The queues must follow SC-3: 14 days for dead letters, 30 s visibility and 3 receives for session starts."
  }

  # SD-2, REQ-103.3: each queue takes sends from the intake's role and refuses any request without TLS.
  assert {
    condition = alltrue([
      for document in values(data.aws_iam_policy_document.queue) : (
        one([for s in document.statement : one(s.principals).identifiers if s.sid == "IntakeSends"]) == toset(["arn:aws:iam::123456789012:role/sre-lab-intake"])
        && one([for s in document.statement : one(s.condition).values if s.sid == "DenyWithoutTls"]) == tolist(["false"])
      )
    ])
    error_message = "Each queue's policy must allow the intake's sends and deny requests without TLS."
  }

  # PD-3, SC-1, REQ-130.3: Python 3.13 on arm64, the sizes of PD-3, and the reserved caps.
  assert {
    condition = (
      aws_lambda_function.intake.handler == "agents.intake.handler.handler"
      && aws_lambda_function.intake.memory_size == 512 && aws_lambda_function.intake.timeout == 60
      && aws_lambda_function.notifier.handler == "agents.notifier.handler.handler"
      && aws_lambda_function.notifier.memory_size == 256 && aws_lambda_function.notifier.timeout == 30
      && aws_lambda_function.intake.reserved_concurrent_executions == 10
      && aws_lambda_function.notifier.reserved_concurrent_executions == 2
      && alltrue([
        for function in [aws_lambda_function.intake, aws_lambda_function.notifier] :
        function.runtime == "python3.13" && function.architectures == tolist(["arm64"])
      ])
    )
    error_message = "The functions must match PD-3 and reserve the caps of SC-1: 10 for the intake, 2 for the notifier."
  }

  # Both functions run from the package named after the hash of its sources, which CI computes without a package.
  assert {
    condition = (
      length(aws_lambda_function.intake.source_code_hash) == 64
      && aws_lambda_function.notifier.source_code_hash == aws_lambda_function.intake.source_code_hash
      && aws_lambda_function.notifier.filename == aws_lambda_function.intake.filename
      && endswith(aws_lambda_function.intake.filename, "/build/lambda/functions-${aws_lambda_function.intake.source_code_hash}.zip")
      && output.functions_package == "functions-${aws_lambda_function.intake.source_code_hash}.zip"
    )
    error_message = "The functions must use the package named after their sources' hash."
  }

  # RD-1, SC-1: 2 platform retries, 10 minutes at most, then the dead-letter queue; the notifier retries nothing.
  assert {
    condition = (
      aws_lambda_function_event_invoke_config.intake.maximum_retry_attempts == 2
      && aws_lambda_function_event_invoke_config.intake.maximum_event_age_in_seconds == 600
      && one(one(aws_lambda_function_event_invoke_config.intake.destination_config).on_failure).destination == "arn:aws:sqs:us-east-1:123456789012:sre-lab-dead-letters"
      && aws_lambda_function_event_invoke_config.notifier.maximum_retry_attempts == 0
      && length(aws_lambda_function_event_invoke_config.notifier.destination_config) == 0
    )
    error_message = "The intake's failures must reach the dead-letter queue after 2 retries; the notifier must not retry."
  }

  # REQ-030.1, SD-2: the lab topic runs the intake, the operations topic runs the notifier, and nothing else may.
  assert {
    condition = (
      aws_sns_topic_subscription.intake.protocol == "lambda"
      && aws_sns_topic_subscription.intake.topic_arn == "arn:aws:sns:us-east-1:123456789012:sre-lab-alerts"
      && aws_sns_topic_subscription.intake.endpoint == "arn:aws:lambda:us-east-1:123456789012:function:sre-lab-intake"
      && aws_lambda_permission.intake_from_lab_topic.principal == "sns.amazonaws.com"
      && aws_lambda_permission.intake_from_lab_topic.source_arn == "arn:aws:sns:us-east-1:123456789012:sre-lab-alerts"
      && aws_sns_topic_subscription.notifier.topic_arn == "arn:aws:sns:us-east-1:123456789012:sre-lab-ops-alarms"
      && aws_sns_topic_subscription.notifier.endpoint == "arn:aws:lambda:us-east-1:123456789012:function:sre-lab-notifier"
      && aws_lambda_permission.notifier_from_ops_alarms.source_arn == "arn:aws:sns:us-east-1:123456789012:sre-lab-ops-alarms"
    )
    error_message = "Each function must be subscribed to its topic, and invocable by that topic only."
  }

  assert {
    condition = aws_lambda_function.intake.environment[0].variables == tomap({
      LAB_TOPIC_ARN           = "arn:aws:sns:us-east-1:123456789012:sre-lab-alerts"
      INCIDENT_TABLE_NAME     = "sre-lab-incidents"
      SESSION_START_QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/sre-lab-session-starts"
      DEAD_LETTER_QUEUE_URL   = "https://sqs.us-east-1.amazonaws.com/123456789012/sre-lab-dead-letters"
    })
    error_message = "The intake must be wired to the lab topic, the table and the two queues."
  }

  # SD-1, REQ-102.1: the intake reads and updates the incident table and sends to the two queues, nothing else.
  assert {
    condition = (
      { for s in data.aws_iam_policy_document.intake.statement : s.sid => s.actions } == {
        IncidentTable                   = toset(["dynamodb:GetItem", "dynamodb:UpdateItem"])
        SessionStartAndDeadLetterQueues = toset(["sqs:SendMessage"])
        OwnLogs                         = toset(["logs:CreateLogStream", "logs:PutLogEvents"])
      }
      && one([for s in data.aws_iam_policy_document.intake.statement : s.resources if s.sid == "IncidentTable"]) == toset(["arn:aws:dynamodb:us-east-1:123456789012:table/sre-lab-incidents"])
      && one([for s in data.aws_iam_policy_document.intake.statement : s.resources if s.sid == "SessionStartAndDeadLetterQueues"]) == toset(["arn:aws:sqs:us-east-1:123456789012:sre-lab-session-starts", "arn:aws:sqs:us-east-1:123456789012:sre-lab-dead-letters"])
    )
    error_message = "The intake's role must follow SD-1: GetItem and UpdateItem on the table, SendMessage on the two queues."
  }

  # REQ-102.1: no write action on a wildcard resource in either function's role.
  assert {
    condition = alltrue(flatten([
      for document in [data.aws_iam_policy_document.intake, data.aws_iam_policy_document.notifier] : [
        for s in document.statement :
        !contains(s.resources, "*") || alltrue([for action in s.actions : can(regex("^[a-z0-9-]+:(Get|List|Describe)", action))])
      ]
    ]))
    error_message = "No write action may have a * resource (REQ-102.1)."
  }

  # REQ-103.1, BR6.4: the notifier may read the Slack secret's value, named by its ARN pattern, and only that secret.
  assert {
    condition = (
      one([for s in data.aws_iam_policy_document.notifier.statement : s.resources if s.sid == "SlackWebhookSecret"]) == toset(["arn:aws:secretsmanager:us-east-1:123456789012:secret:sre-lab/slack-webhook-url-??????"])
      && one([for s in data.aws_iam_policy_document.notifier.statement : s.actions if s.sid == "SlackWebhookSecret"]) == toset(["secretsmanager:GetSecretValue"])
      && aws_lambda_function.notifier.environment[0].variables["SLACK_WEBHOOK_SECRET_ID"] == "sre-lab/slack-webhook-url"
      && aws_lambda_function.notifier.environment[0].variables["DEAD_LETTER_ALARM_NAME"] == aws_cloudwatch_metric_alarm.dead_letters_waiting.alarm_name
    )
    error_message = "The notifier must name the Slack secret only, and read its value at send time."
  }

  # SD-2: only this account's CloudWatch alarms publish to the operations topic, over TLS.
  assert {
    condition = (
      one(data.aws_iam_policy_document.ops_alarms.statement[0].principals).identifiers == toset(["cloudwatch.amazonaws.com"])
      && {
        for condition in data.aws_iam_policy_document.ops_alarms.statement[0].condition :
        condition.variable => toset(condition.values)
        } == {
        "aws:SourceArn"     = toset(["arn:aws:cloudwatch:us-east-1:123456789012:alarm:*"])
        "aws:SourceAccount" = toset(["123456789012"])
      }
      && data.aws_iam_policy_document.ops_alarms.statement[1].effect == "Deny"
    )
    error_message = "The operations topic must take publishes from this account's alarms only, over TLS."
  }

  # OD-4, REQ-140.2: one visible dead letter for a minute raises the alarm that runs the notifier.
  assert {
    condition = (
      aws_cloudwatch_metric_alarm.dead_letters_waiting.namespace == "AWS/SQS"
      && aws_cloudwatch_metric_alarm.dead_letters_waiting.metric_name == "ApproximateNumberOfMessagesVisible"
      && aws_cloudwatch_metric_alarm.dead_letters_waiting.dimensions == tomap({ QueueName = "sre-lab-dead-letters" })
      && aws_cloudwatch_metric_alarm.dead_letters_waiting.period == 60
      && aws_cloudwatch_metric_alarm.dead_letters_waiting.evaluation_periods == 1
      && aws_cloudwatch_metric_alarm.dead_letters_waiting.threshold == 1
      && aws_cloudwatch_metric_alarm.dead_letters_waiting.comparison_operator == "GreaterThanOrEqualToThreshold"
      && aws_cloudwatch_metric_alarm.dead_letters_waiting.treat_missing_data == "notBreaching"
      && aws_cloudwatch_metric_alarm.dead_letters_waiting.alarm_actions == toset(["arn:aws:sns:us-east-1:123456789012:sre-lab-ops-alarms"])
    )
    error_message = "The dead-letter alarm must follow OD-4 and publish to the operations topic."
  }

  # OD-4, REQ-140.4: the other alarms are CloudWatch only in Phase 1, on any occurrence in 5 minutes.
  assert {
    condition = (
      {
        for alarm in aws_cloudwatch_metric_alarm.pipeline : alarm.metric_name => alarm.dimensions["component"]
        } == {
        IntakeErrors         = "intake"
        LedgerWriteFailures  = "ledger"
        NoticeFailures       = "notifier"
        AlertToRecordSeconds = "intake"
      }
      && aws_cloudwatch_metric_alarm.pipeline["slow-record"].threshold == 60
      && aws_cloudwatch_metric_alarm.pipeline["slow-record"].comparison_operator == "GreaterThanThreshold"
      && alltrue([
        for alarm in concat(values(aws_cloudwatch_metric_alarm.pipeline), values(aws_cloudwatch_metric_alarm.throttles)) :
        length(coalesce(alarm.alarm_actions, toset([]))) == 0 && alarm.period == 300 && alarm.treat_missing_data == "notBreaching"
      ])
      && toset([for alarm in aws_cloudwatch_metric_alarm.throttles : alarm.dimensions["FunctionName"]]) == toset(["sre-lab-intake", "sre-lab-notifier"])
    )
    error_message = "The pipeline and throttle alarms must follow OD-4: no action in Phase 1, 5-minute periods."
  }

  # OD-2: the functions' log groups keep 14 days.
  assert {
    condition = (
      aws_cloudwatch_log_group.intake.name == "/aws/lambda/sre-lab-intake"
      && aws_cloudwatch_log_group.notifier.name == "/aws/lambda/sre-lab-notifier"
      && aws_cloudwatch_log_group.intake.retention_in_days == 14
      && aws_cloudwatch_log_group.notifier.retention_in_days == 14
    )
    error_message = "The functions' log groups must keep 14 days."
  }
}
