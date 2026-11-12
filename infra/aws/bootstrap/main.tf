# The Terraform state bucket (infrastructure-specification.md, "State bucket").
# Versioned, encrypted with SSE-S3, closed to the public, reachable only over TLS,
# and closed to the coding agent's read-only role (REQ-013.1): state can hold
# configuration secrets, such as the Cognito app client's secret.

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  # IAM Identity Center names a permission set's role AWSReservedSSO_<set>_<suffix>,
  # under /aws-reserved/sso.amazonaws.com/ (with a Region segment for some
  # Identity Center Regions). The account comes from the caller, never from Git.
  coding_agent_role_pattern = "arn:${local.partition}:iam::${local.account_id}:role/aws-reserved/sso.amazonaws.com/*AWSReservedSSO_${var.coding_agent_permission_set_name}_*"
}

resource "aws_s3_bucket" "state" {
  bucket = var.state_bucket_name

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Old state versions are kept long enough to roll back, then removed, so the
# lock files that every plan and apply writes do not pile up for ever.
resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_days
    }

    expiration {
      expired_object_delete_marker = true
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.state]
}

data "aws_iam_policy_document" "state" {
  statement {
    sid       = "DenyRequestsWithoutTls"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]

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

  # REQ-013.1: the coding agent may list the bucket but never read or change a
  # state object. aws:PrincipalArn is always present on signed requests.
  statement {
    sid    = "DenyStateObjectsToCodingAgent"
    effect = "Deny"
    actions = [
      "s3:GetObject*",
      "s3:PutObject*",
      "s3:DeleteObject*",
      "s3:RestoreObject",
    ]
    resources = ["${aws_s3_bucket.state.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:PrincipalArn"
      values   = [local.coding_agent_role_pattern]
    }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = data.aws_iam_policy_document.state.json

  depends_on = [aws_s3_bucket_public_access_block.state]
}
