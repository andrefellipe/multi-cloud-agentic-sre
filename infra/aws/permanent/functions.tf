# What the pipeline's functions share: their package and their trust policy.
#
# The intake (intake.tf) and the notifier (notifier.tf) run from one package,
# which `make package` builds with tools/build/package.py before you apply. Its
# name carries the hash of the sources it is built from: agents/**/*.py,
# pyproject.toml, uv.lock and tools/build/package.py. This file computes the same
# hash, so:
# - CI plans with no package: the provider reads `filename` only when it creates
#   or updates a function, and `source_code_hash` is a value of this
#   configuration, which the provider keeps in state as given (AWS provider 6.x);
# - a plan after a real apply shows no change until those sources change;
# - after they change, the apply fails until you build the matching package,
#   instead of uploading an older one.
# Python 3.13 on arm64, outside any VPC: the functions call only AWS endpoints
# and Slack (PD-3). No reserved concurrency until the account's Lambda limit is
# raised from 10: Lambda keeps 100 unreserved (SC-1).

locals {
  repo_root = "${path.module}/../../.."

  package_source_files = sort(concat(
    tolist(fileset(local.repo_root, "agents/**/*.py")),
    ["pyproject.toml", "tools/build/package.py", "uv.lock"],
  ))
  package_source_hash = sha256(join("\n", [
    for name in local.package_source_files : "${name} ${filesha256("${local.repo_root}/${name}")}"
  ]))
  functions_package = "${local.repo_root}/build/lambda/functions-${local.package_source_hash}.zip"

  dead_letter_alarm_name = "sre-lab-dead-letters-waiting"
  slack_webhook_secret   = "sre-lab/slack-webhook-url"
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}
