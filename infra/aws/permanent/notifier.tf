# The notifier (LC9) and the operations alarm topic that runs it (LC10): the
# one Slack message of Phase 1, the dead-letter notice (REQ-033, REQ-140.2,
# BR6.3 to BR6.5, ADR-006). Code: agents/notifier/.

# LC10. Only CloudWatch alarms of this account may publish to it, and only over
# TLS (SD-2). Not encrypted at rest: alarm messages hold no secret (SD-6).
resource "aws_sns_topic" "ops_alarms" {
  name = "sre-lab-ops-alarms"
}

data "aws_iam_policy_document" "ops_alarms" {
  statement {
    sid       = "AlarmsOfThisAccount"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.ops_alarms.arn]

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:cloudwatch:${local.region}:${local.account_id}:alarm:*"]
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
    resources = [aws_sns_topic.ops_alarms.arn]

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

resource "aws_sns_topic_policy" "ops_alarms" {
  arn    = aws_sns_topic.ops_alarms.arn
  policy = data.aws_iam_policy_document.ops_alarms.json
}

# SD-1, SD-5:
# - the Slack webhook secret, which you created as sre-lab/slack-webhook-url, is
#   named by its ARN pattern only: Secrets Manager adds six random characters to
#   a secret's ARN. Nothing here reads the secret, not even its metadata, so a
#   plan never touches it; the notifier reads its value at send time (BR6.4);
# - the dead-letter queue's attributes, for the item count of the notice;
# - GetMetricData, for the oldest item's age. That metric is not in the queue's
#   attributes, and CloudWatch grants metric reads on "*" only. A read, so SD-1's
#   rule against "*" on write actions holds.
resource "aws_iam_role" "notifier" {
  name               = "sre-lab-notifier"
  description        = "Notifier (LC9): read the Slack webhook secret and the dead-letter queue's count and age."
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

data "aws_iam_policy_document" "notifier" {
  statement {
    sid       = "SlackWebhookSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:${local.partition}:secretsmanager:${local.region}:${local.account_id}:secret:${local.slack_webhook_secret}-??????"]
  }

  statement {
    sid       = "DeadLetterCount"
    actions   = ["sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.dead_letters.arn]
  }

  statement {
    sid       = "OldestDeadLetterAge"
    actions   = ["cloudwatch:GetMetricData"]
    resources = ["*"]
  }

  statement {
    sid       = "OwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.notifier.arn}:*"]
  }
}

resource "aws_iam_role_policy" "notifier" {
  name   = "notifier"
  role   = aws_iam_role.notifier.id
  policy = data.aws_iam_policy_document.notifier.json
}

resource "aws_cloudwatch_log_group" "notifier" {
  name              = "/aws/lambda/sre-lab-notifier"
  retention_in_days = 14
}

resource "aws_lambda_function" "notifier" {
  function_name    = "sre-lab-notifier"
  description      = "Notifier (LC9): the fixed Slack notice when dead letters wait (ADR-006)."
  role             = aws_iam_role.notifier.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "agents.notifier.handler.handler"
  filename         = local.functions_package
  source_code_hash = local.package_source_hash
  memory_size      = 256
  timeout          = 30

  environment {
    variables = {
      DEAD_LETTER_QUEUE_URL   = aws_sqs_queue.dead_letters.url
      DEAD_LETTER_ALARM_NAME  = local.dead_letter_alarm_name
      SLACK_WEBHOOK_SECRET_ID = local.slack_webhook_secret
    }
  }

  depends_on = [aws_cloudwatch_log_group.notifier, aws_iam_role_policy.notifier]
}

# The notifier makes its own 3 posts and never raises (BR6.5), so the platform
# retries nothing: a retry could only repeat a notice. It has no on-failure
# destination, which would put its own failures on the queue it reports.
resource "aws_lambda_function_event_invoke_config" "notifier" {
  function_name          = aws_lambda_function.notifier.function_name
  maximum_retry_attempts = 0
}

resource "aws_lambda_permission" "notifier_from_ops_alarms" {
  statement_id  = "OpsAlarmTopicOnly"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.notifier.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.ops_alarms.arn
}

resource "aws_sns_topic_subscription" "notifier" {
  topic_arn = aws_sns_topic.ops_alarms.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.notifier.arn

  depends_on = [aws_lambda_permission.notifier_from_ops_alarms]
}
