# The alarms of monitoring-design.md for the intake, the ledger and the
# notifier (OD-4, REQ-140.4, REQ-120.6). The session's two alarms, start
# failures and slow session, arrive with the session starter and the runtime.
#
# Only "dead letters waiting" acts: it publishes to the operations alarm topic,
# which runs the notifier (REQ-140.2). The others are "CloudWatch only" in
# Phase 1: they show in CloudWatch and Grafana with no action, so the notifier
# never receives an alarm it has no template for (ADR-006); u4 connects them.
# Each fires on any occurrence in 5 minutes, because in a lab any error is worth
# a look (RD-5). Missing data is not breaching: no data means nothing happened.

resource "aws_cloudwatch_metric_alarm" "dead_letters_waiting" {
  alarm_name          = local.dead_letter_alarm_name
  alarm_description   = "Items wait in the dead-letter queue (LC8). Replay them with tools/lab/replay_dead_letters.py once the cause is fixed (OD-4, REQ-140.2)."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dead_letters.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.ops_alarms.arn]
}

locals {
  pipeline_alarms = {
    "intake-errors" = {
      metric      = "IntakeErrors"
      component   = "intake"
      statistic   = "Sum"
      comparison  = "GreaterThanOrEqualToThreshold"
      threshold   = 1
      description = "The intake met an unexpected error or could not save a dead-letter item (BR6.2, RD-1)."
    }
    "ledger-write-failures" = {
      metric      = "LedgerWriteFailures"
      component   = "ledger"
      statistic   = "Sum"
      comparison  = "GreaterThanOrEqualToThreshold"
      threshold   = 1
      description = "The incident table refused a write after every attempt (BR6.1, REQ-140.1)."
    }
    "notice-failures" = {
      metric      = "NoticeFailures"
      component   = "notifier"
      statistic   = "Sum"
      comparison  = "GreaterThanOrEqualToThreshold"
      threshold   = 1
      description = "A dead-letter notice did not reach Slack; check the dead-letter queue yourself (BR6.5)."
    }
    "slow-record" = {
      metric      = "AlertToRecordSeconds"
      component   = "intake"
      statistic   = "Maximum"
      comparison  = "GreaterThanThreshold"
      threshold   = 60
      description = "An alert took more than 60 seconds to reach its incident record (REQ-120.1)."
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "pipeline" {
  for_each = local.pipeline_alarms

  alarm_name          = "sre-lab-${each.key}"
  alarm_description   = each.value.description
  namespace           = "SreLab/Skeleton"
  metric_name         = each.value.metric
  dimensions          = { component = each.value.component }
  statistic           = each.value.statistic
  period              = 300
  evaluation_periods  = 1
  threshold           = each.value.threshold
  comparison_operator = each.value.comparison
  treat_missing_data  = "notBreaching"
}

# SC-1, REQ-120.5: any throttled invocation of a pipeline function.
resource "aws_cloudwatch_metric_alarm" "throttles" {
  for_each = {
    intake   = aws_lambda_function.intake.function_name
    notifier = aws_lambda_function.notifier.function_name
  }

  alarm_name          = "sre-lab-${each.key}-throttles"
  alarm_description   = "The ${each.key} function was throttled; the account's Lambda concurrency limit is the shared cap until reserved concurrency is set (SC-1)."
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"
  dimensions          = { FunctionName = each.value }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
}
