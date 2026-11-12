# The CI plan role (LC14): GitHub Actions assumes it through OIDC, so no cloud key
# is stored in GitHub (REQ-152.1, SD-10). Only this repository's pull requests and
# its main branch may assume it, named by GitHub's IDs as well as by name
# (var.github_oidc_subject_prefix). It can read the account and write nothing but
# the state lock files; it is refused secret values and any S3 bucket that another
# account owns, which matters because the state bucket's name is public.
# After the first apply, store the role's ARN as the repository secret
# AWS_PLAN_ROLE_ARN (docs/runbooks/phase-1-skeleton.md).

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "ci_plan_trust" {
  statement {
    sid     = "GitHubActionsPullRequestsAndMain"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "${var.github_oidc_subject_prefix}:pull_request",
        "${var.github_oidc_subject_prefix}:ref:refs/heads/main",
      ]
    }
  }
}

resource "aws_iam_role" "ci_plan" {
  name                 = "sre-lab-ci-terraform-plan"
  description          = "Read-only role for terraform plan in GitHub Actions (LC14, REQ-152.1)."
  assume_role_policy   = data.aws_iam_policy_document.ci_plan_trust.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy_attachment" "ci_plan_read_only" {
  role       = aws_iam_role.ci_plan.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/ReadOnlyAccess"
}

data "aws_iam_policy_document" "ci_plan" {
  # The S3 backend's lock is a <key>.tflock object next to each state file.
  statement {
    sid       = "StateLockFilesOnly"
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = ["arn:${local.partition}:s3:::${var.state_bucket_name}/*.tflock"]
  }

  # A bucket of the same name in another account can never be read or written.
  # A request whose bucket owner is unknown is refused as well: the negated
  # operator holds when the key is absent, which is the safe side here.
  statement {
    sid       = "DenyS3OutsideThisAccount"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = ["*"]

    condition {
      test     = "StringNotEquals"
      variable = "s3:ResourceAccount"
      values   = [local.account_id]
    }
  }

  # ReadOnlyAccess grants none of these today; the explicit deny keeps it so.
  statement {
    sid    = "DenySecretValues"
    effect = "Deny"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:BatchGetSecretValue",
      "kms:Decrypt",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "ci_plan" {
  name   = "terraform-plan"
  role   = aws_iam_role.ci_plan.id
  policy = data.aws_iam_policy_document.ci_plan.json
}
