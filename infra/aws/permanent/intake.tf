# The intake function (LC2): the lab topic's subscriber, which turns alert
# notifications into incident changes (REQ-030 to REQ-033, REQ-035, REQ-140,
# REQ-141). Code: agents/intake/.

# SD-1: reads and conditional updates on the incident table, and nothing else
# there. Every ledger write is an Update entry of a transaction, so the role
# needs no PutItem, DeleteItem or Scan (agents/ledger/items.py). Sends go to the
# session-start queue and the dead-letter queue only; the second also takes the
# function's on-failure records, which Lambda sends with this role.
resource "aws_iam_role" "intake" {
  name               = "sre-lab-intake"
  description        = "Intake function (LC2): apply alerts to the incident table, hand off session starts, dead-letter failures."
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

data "aws_iam_policy_document" "intake" {
  statement {
    sid       = "IncidentTable"
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.incidents.arn]
  }

  statement {
    sid       = "SessionStartAndDeadLetterQueues"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.session_starts.arn, aws_sqs_queue.dead_letters.arn]
  }

  statement {
    sid       = "OwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.intake.arn}:*"]
  }
}

resource "aws_iam_role_policy" "intake" {
  name   = "intake"
  role   = aws_iam_role.intake.id
  policy = data.aws_iam_policy_document.intake.json
}

# OD-2: 14 days, like every pipeline log group.
resource "aws_cloudwatch_log_group" "intake" {
  name              = "/aws/lambda/sre-lab-intake"
  retention_in_days = 14
}

resource "aws_lambda_function" "intake" {
  function_name    = "sre-lab-intake"
  description      = "EventIntake (LC2): alert notifications from the lab topic into incident records."
  role             = aws_iam_role.intake.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "agents.intake.handler.handler"
  filename         = local.functions_package
  source_code_hash = local.package_source_hash
  memory_size      = 512
  timeout          = 60
  # SC-1, REQ-130.3: at most 10 at once, so a storm cannot run up cost or
  # overload the incident table; about 15 times the burst of REQ-120.5.
  reserved_concurrent_executions = 10

  environment {
    variables = {
      LAB_TOPIC_ARN           = aws_sns_topic.lab_alerts.arn
      INCIDENT_TABLE_NAME     = aws_dynamodb_table.incidents.name
      SESSION_START_QUEUE_URL = aws_sqs_queue.session_starts.url
      DEAD_LETTER_QUEUE_URL   = aws_sqs_queue.dead_letters.url
    }
  }

  depends_on = [aws_cloudwatch_log_group.intake, aws_iam_role_policy.intake]
}

# RD-1, SC-1: SNS invokes the function asynchronously. A crash or a timeout is
# retried twice by the platform; after that, or after 10 minutes, the event goes
# to the dead-letter queue, so no alert waits hours in Lambda's internal queue.
resource "aws_lambda_function_event_invoke_config" "intake" {
  function_name                = aws_lambda_function.intake.function_name
  maximum_retry_attempts       = 2
  maximum_event_age_in_seconds = 600

  destination_config {
    on_failure {
      destination = aws_sqs_queue.dead_letters.arn
    }
  }
}

# SD-2, REQ-030.1: only the lab topic may invoke the intake; the intake also
# checks the topic of every message (BR1.1).
resource "aws_lambda_permission" "intake_from_lab_topic" {
  statement_id  = "LabTopicOnly"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.intake.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.lab_alerts.arn
}

resource "aws_sns_topic_subscription" "intake" {
  topic_arn = aws_sns_topic.lab_alerts.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.intake.arn

  depends_on = [aws_lambda_permission.intake_from_lab_topic]
}
