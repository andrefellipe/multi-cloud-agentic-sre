# The alert path up to the intake: the rule group for the demo fault, the alert
# manager, and the lab topic (LC1) it publishes to (REQ-030, BR8.7, contract C1).
# The intake function and its subscription arrive with the next pull request.

# The lab topic. Only this workspace's alert manager may publish to it, and only
# over TLS (SD-2, REQ-030.1). Not encrypted at rest: alert labels are not secret,
# and a customer key would have to be shared with the alert manager (SD-6).
resource "aws_sns_topic" "lab_alerts" {
  name = "sre-lab-alerts"
}

data "aws_iam_policy_document" "lab_alerts" {
  # Confused-deputy protection: the alert manager of this workspace, in this account.
  statement {
    sid       = "AlertManagerOfTheLabWorkspace"
    actions   = ["sns:Publish", "sns:GetTopicAttributes"]
    resources = [aws_sns_topic.lab_alerts.arn]

    principals {
      type        = "Service"
      identifiers = ["aps.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_prometheus_workspace.sre_lab.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }

  statement {
    sid       = "DenyPublishWithoutTls"
    effect    = "Deny"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.lab_alerts.arn]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_sns_topic_policy" "lab_alerts" {
  arn    = aws_sns_topic.lab_alerts.arn
  policy = data.aws_iam_policy_document.lab_alerts.json
}

# The rules for the fault the skeleton demo injects. They are kept in Git with
# the platform, and checked with promtool (platform/alerts/tests/).
resource "aws_prometheus_rule_group_namespace" "demo_fault" {
  name         = "demo-fault"
  workspace_id = aws_prometheus_workspace.sre_lab.id
  data         = file("${path.module}/../../../platform/alerts/demo-fault.yaml")
}

# Routing by service and alert name, with the timing of PD-4, and a message body
# in the JSON of contract C1 (templates/alertmanager.yaml.tftpl).
resource "aws_prometheus_alert_manager_definition" "sre_lab" {
  workspace_id = aws_prometheus_workspace.sre_lab.id
  definition = templatefile("${path.module}/templates/alertmanager.yaml.tftpl", {
    lab_alerts_topic_arn = aws_sns_topic.lab_alerts.arn
    region               = local.region
  })

  depends_on = [aws_sns_topic_policy.lab_alerts]
}
