# CloudWatch Transaction Search, switched on once for the account
# (monitoring-design.md, "Logs and tracing"). AgentCore Observability writes the
# agent sessions' spans to CloudWatch Logs only when trace segments go there.
# The resource policy lets X-Ray write spans to the two log groups it uses.

data "aws_iam_policy_document" "transaction_search" {
  statement {
    sid     = "TransactionSearchXRayAccess"
    actions = ["logs:PutLogEvents"]
    resources = [
      "arn:${local.partition}:logs:${local.region}:${local.account_id}:log-group:aws/spans:*",
      "arn:${local.partition}:logs:${local.region}:${local.account_id}:log-group:/aws/application-signals/data:*",
    ]

    principals {
      type        = "Service"
      identifiers = ["xray.amazonaws.com"]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:xray:${local.region}:${local.account_id}:*"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_cloudwatch_log_resource_policy" "transaction_search" {
  policy_name     = "sre-lab-transaction-search"
  policy_document = data.aws_iam_policy_document.transaction_search.json
}

resource "aws_xray_trace_segment_destination" "cloudwatch_logs" {
  destination = "CloudWatchLogs"

  depends_on = [aws_cloudwatch_log_resource_policy.transaction_search]
}
