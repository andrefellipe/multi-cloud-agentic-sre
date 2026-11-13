# The incident pipeline's stores (REQ-030 to REQ-033, REQ-140, REQ-141): the
# incident table (LC3), the session-start queue (LC4) and the dead-letter queue
# (LC8). They live in the permanent layer, so a lab teardown never reaches the
# incident history or the work waiting in the queues (REQ-131.1).

# LC3: one on-demand table for incidents, open-incident markers and inbound
# events, keyed by pk (SC-2, agents/ledger/items.py). Inbound events expire
# through the time-to-live attribute after 14 days (BR2.3). AWS-owned key at
# rest (SD-6, REQ-103.3); deletion protection and 35 days of point-in-time
# recovery protect the history (REQ-140.3).
resource "aws_dynamodb_table" "incidents" {
  name                        = "sre-lab-incidents"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "pk"
  deletion_protection_enabled = true

  attribute {
    name = "pk"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at_epoch"
    enabled        = true
  }

  point_in_time_recovery {
    enabled                 = true
    recovery_period_in_days = 35
  }
}

# LC8: kept 14 days, the most SQS allows (RD-4, REQ-140.2). It receives the
# intake's dead-letter items, the intake's on-failure records and session starts
# redriven from LC4; tools/lab/replay_dead_letters.py replays all three (BR6.6).
resource "aws_sqs_queue" "dead_letters" {
  name                      = "sre-lab-dead-letters"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

# LC4: the intake hands session starts here and returns (PD-1). A start that
# fails is received again after 30 s, 3 receives in all, then moves to LC8
# (SC-3, BR4.5). The session starter that reads it arrives with u1's last pull
# request; until then, requests wait here for a day.
resource "aws_sqs_queue" "session_starts" {
  name                       = "sre-lab-session-starts"
  visibility_timeout_seconds = 30
  message_retention_seconds  = 86400
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dead_letters.arn
    maxReceiveCount     = 3
  })
}

# Only LC4 may use LC8 as its dead-letter queue.
resource "aws_sqs_queue_redrive_allow_policy" "dead_letters" {
  queue_url = aws_sqs_queue.dead_letters.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.session_starts.arn]
  })
}

# SD-2, REQ-103.3: each queue accepts sends from the intake's role and refuses
# any request without TLS. You keep access through your own role, which the
# replay tool needs to put session starts back on LC4.
data "aws_iam_policy_document" "queue" {
  for_each = {
    dead_letters   = aws_sqs_queue.dead_letters.arn
    session_starts = aws_sqs_queue.session_starts.arn
  }

  statement {
    sid       = "IntakeSends"
    actions   = ["sqs:SendMessage"]
    resources = [each.value]

    principals {
      type        = "AWS"
      identifiers = [aws_iam_role.intake.arn]
    }
  }

  statement {
    sid       = "DenyWithoutTls"
    effect    = "Deny"
    actions   = ["sqs:*"]
    resources = [each.value]

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

resource "aws_sqs_queue_policy" "dead_letters" {
  queue_url = aws_sqs_queue.dead_letters.id
  policy    = data.aws_iam_policy_document.queue["dead_letters"].json
}

resource "aws_sqs_queue_policy" "session_starts" {
  queue_url = aws_sqs_queue.session_starts.id
  policy    = data.aws_iam_policy_document.queue["session_starts"].json
}
