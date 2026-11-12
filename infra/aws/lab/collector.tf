# The platform Collector's AWS identity (LC18, REQ-024, SD-1, SD-10). EKS Pod
# Identity gives the service account observability/otel-collector this role, so
# the Collector holds no key. The Fleet bundle platform/otel-collector creates
# that service account. The role may write the demo's telemetry and nothing else:
# - metrics to the lab's Managed Prometheus workspace;
# - logs to the demo's log group;
# - trace spans to X-Ray, which has no resource-level permissions for writing
#   spans, so that one statement is limited to this Region instead. SD-1 lets
#   every role write its own logs, metrics and traces.
#
# The workspace and the log group are in the permanent layer. Until it is applied
# with them, this root plans the role without those two permissions and warns
# (check block below), so a plan never fails because of the order of applies.

locals {
  collector_namespace       = "observability"
  collector_service_account = "otel-collector"

  prometheus_workspace_id = try(data.terraform_remote_state.permanent.outputs.prometheus_workspace_id, null)
  demo_log_group_name     = try(data.terraform_remote_state.permanent.outputs.demo_log_group_name, null)
}

data "aws_iam_policy_document" "collector_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }

    # Only pods of the lab cluster, in this account.
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_eks_cluster.lab.arn]
    }
  }
}

resource "aws_iam_role" "collector" {
  name               = "sre-lab-otel-collector"
  description        = "Platform OpenTelemetry Collector (EKS Pod Identity): write the demo's metrics, logs and traces."
  assume_role_policy = data.aws_iam_policy_document.collector_trust.json
}

data "aws_iam_policy_document" "collector" {
  dynamic "statement" {
    for_each = local.prometheus_workspace_id == null ? [] : [local.prometheus_workspace_id]

    content {
      sid       = "RemoteWriteToTheLabWorkspace"
      actions   = ["aps:RemoteWrite"]
      resources = ["arn:${local.partition}:aps:${local.region}:${local.account_id}:workspace/${statement.value}"]
    }
  }

  dynamic "statement" {
    for_each = local.demo_log_group_name == null ? [] : [local.demo_log_group_name]

    content {
      sid       = "WriteTheDemoLogGroup"
      actions   = ["logs:PutLogEvents"]
      resources = ["arn:${local.partition}:logs:${local.region}:${local.account_id}:log-group:${statement.value}:log-stream:*"]
    }
  }

  statement {
    sid       = "WriteTraceSpansInThisRegion"
    actions   = ["xray:PutTraceSegments"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [local.region]
    }
  }
}

resource "aws_iam_role_policy" "collector" {
  name   = "write-demo-telemetry"
  role   = aws_iam_role.collector.id
  policy = data.aws_iam_policy_document.collector.json
}

# The association can exist before Fleet creates the service account. Pods get
# the credentials when they start, so the lab is applied before Fleet deploys.
resource "aws_eks_pod_identity_association" "collector" {
  cluster_name    = aws_eks_cluster.lab.name
  namespace       = local.collector_namespace
  service_account = local.collector_service_account
  role_arn        = aws_iam_role.collector.arn

  depends_on = [aws_eks_addon.pod_identity_agent]
}

check "permanent_layer_has_the_collector_destinations" {
  assert {
    condition     = local.prometheus_workspace_id != null && local.demo_log_group_name != null
    error_message = "The permanent layer has no prometheus_workspace_id or demo_log_group_name output yet, so the Collector's role is planned without its metrics and logs permissions. Apply infra/aws/permanent from main, then plan and apply this root again."
  }
}
