# terraform test for infra/aws/bootstrap, with a mocked AWS provider: no
# credentials, no AWS call, no state. It checks the state bucket's settings and
# the two denials of its policy. Values are synthetic.
#
# Run it with: terraform -chdir=infra/aws/bootstrap init -backend=false && terraform -chdir=infra/aws/bootstrap test

mock_provider "aws" {
  # The provider checks that a bucket policy is JSON; a mock returns random text.
  mock_data "aws_iam_policy_document" {
    defaults = {
      json          = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
      minified_json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }

  mock_resource "aws_s3_bucket" {
    defaults = {
      arn = "arn:aws:s3:::multi-cloud-agentic-sre-tfstate"
    }
  }
}

override_data {
  target = data.aws_caller_identity.current
  values = {
    account_id = "123456789012"
  }
}

override_data {
  target = data.aws_partition.current
  values = {
    partition = "aws"
  }
}

run "state_bucket_is_private_versioned_and_encrypted" {
  command = apply

  assert {
    condition     = aws_s3_bucket.state.bucket == "multi-cloud-agentic-sre-tfstate"
    error_message = "The bucket name must match the backend blocks of every root."
  }

  assert {
    condition     = aws_s3_bucket_versioning.state.versioning_configuration[0].status == "Enabled"
    error_message = "The state bucket must be versioned."
  }

  assert {
    condition     = one(one(aws_s3_bucket_server_side_encryption_configuration.state.rule).apply_server_side_encryption_by_default).sse_algorithm == "AES256"
    error_message = "The state bucket must use SSE-S3."
  }

  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.state.block_public_acls,
      aws_s3_bucket_public_access_block.state.block_public_policy,
      aws_s3_bucket_public_access_block.state.ignore_public_acls,
      aws_s3_bucket_public_access_block.state.restrict_public_buckets,
    ])
    error_message = "All public access must be blocked."
  }

  assert {
    condition     = aws_s3_bucket_ownership_controls.state.rule[0].object_ownership == "BucketOwnerEnforced"
    error_message = "ACLs must be disabled."
  }
}

run "policy_requires_tls_and_refuses_the_coding_agent" {
  command = plan

  assert {
    condition = one([
      for statement in data.aws_iam_policy_document.state.statement : statement
      if statement.sid == "DenyRequestsWithoutTls"
      ]).effect == "Deny" && toset(one([
        for statement in data.aws_iam_policy_document.state.statement : one(statement.condition).values
        if statement.sid == "DenyRequestsWithoutTls"
    ])) == toset(["false"])
    error_message = "Requests without TLS must be denied."
  }

  # REQ-013.1: the coding agent's read-only role may not read or change state objects.
  assert {
    condition = toset(one([
      for statement in data.aws_iam_policy_document.state.statement : one(statement.condition).values
      if statement.sid == "DenyStateObjectsToCodingAgent"
      ])) == toset([
      "arn:aws:iam::123456789012:role/aws-reserved/sso.amazonaws.com/*AWSReservedSSO_SreLabReadOnly_*",
    ])
    error_message = "The deny must match the coding agent's IAM Identity Center role in this account."
  }

  assert {
    condition = contains(one([
      for statement in data.aws_iam_policy_document.state.statement : statement.actions
      if statement.sid == "DenyStateObjectsToCodingAgent"
    ]), "s3:GetObject*")
    error_message = "Reading state objects must be denied to the coding agent."
  }
}
