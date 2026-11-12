# Amazon Managed Grafana, signing in through IAM Identity Center, with you as its
# admin (infrastructure-design Q3). Its role is defined here (customer-managed
# permissions), so what Grafana may read is visible in review: CloudWatch, and
# queries against Managed Prometheus. The dashboard comes from infra/aws/dashboards.

data "aws_iam_policy_document" "grafana_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["grafana.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:grafana:${local.region}:${local.account_id}:/workspaces/*"]
    }
  }
}

resource "aws_iam_role" "grafana" {
  name               = "sre-lab-grafana"
  description        = "Managed Grafana workspace role: read CloudWatch and query Managed Prometheus."
  assume_role_policy = data.aws_iam_policy_document.grafana_trust.json
}

resource "aws_iam_role_policy_attachment" "grafana_cloudwatch" {
  role       = aws_iam_role.grafana.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AmazonGrafanaCloudWatchAccess"
}

# What the Prometheus data source needs: find workspaces and query them. Read only.
data "aws_iam_policy_document" "grafana_prometheus" {
  statement {
    actions = [
      "aps:ListWorkspaces",
      "aps:DescribeWorkspace",
      "aps:QueryMetrics",
      "aps:GetLabels",
      "aps:GetSeries",
      "aps:GetMetricMetadata",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "grafana_prometheus" {
  name   = "managed-prometheus-read"
  role   = aws_iam_role.grafana.id
  policy = data.aws_iam_policy_document.grafana_prometheus.json
}

resource "aws_grafana_workspace" "sre_lab" {
  name                     = "sre-lab"
  description              = "Dashboards for the SRE lab: demo telemetry and the incident pipeline (REQ-024)."
  account_access_type      = "CURRENT_ACCOUNT"
  authentication_providers = ["AWS_SSO"]
  permission_type          = "CUSTOMER_MANAGED"
  role_arn                 = aws_iam_role.grafana.arn
  grafana_version          = var.grafana_version
}

resource "aws_grafana_role_association" "admin" {
  workspace_id = aws_grafana_workspace.sre_lab.id
  role         = "ADMIN"
  user_ids     = [data.aws_ssm_parameter.idc_user_id.value]
}

# The identity infra/aws/dashboards applies with: its data sources need the Admin
# role. It holds no token. You create a 30-minute token for each apply of that
# root, and it lives only in your shell (docs/runbooks/phase-1-skeleton.md).
resource "aws_grafana_workspace_service_account" "dashboards" {
  name         = "terraform-dashboards"
  grafana_role = "ADMIN"
  workspace_id = aws_grafana_workspace.sre_lab.id
}
