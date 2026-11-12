# terraform test for infra/aws/lab, with a mocked AWS provider: no credentials, no
# AWS call, no state. It evaluates what `terraform validate` cannot: the sensitive
# SSM values flowing into resources, the rendered user data, the remote state,
# the preconditions, and the Collector's role. Every value below is synthetic.
#
# Run it with: terraform -chdir=infra/aws/lab init -backend=false && terraform -chdir=infra/aws/lab test

mock_provider "aws" {
  # The provider checks that policies are JSON objects; a mock returns random text.
  mock_data "aws_iam_policy_document" {
    defaults = {
      json          = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
      minified_json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
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

override_data {
  target = data.aws_region.current
  values = {
    region = "us-east-1"
  }
}

override_data {
  target = data.aws_ssm_parameter.domain_name
  values = {
    value = "example.com"
  }
}

override_data {
  target = data.aws_ssm_parameter.allowlist_cidrs
  values = {
    value = "203.0.113.7/32, 198.51.100.0/28"
  }
}

override_data {
  target = data.aws_ssm_parameter.ubuntu_ami
  values = {
    insecure_value = "ami-0123456789abcdef0"
  }
}

override_data {
  target = data.aws_eks_cluster_versions.standard
  values = {
    cluster_versions = [
      { cluster_version = "1.35" },
      { cluster_version = "1.36" },
      { cluster_version = "1.37" },
    ]
  }
}

override_data {
  target = data.terraform_remote_state.permanent
  values = {
    outputs = {
      rancher_certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
      public_zone_id          = "Z0000000EXAMPLE"
      ci_plan_role_name       = "sre-lab-ci-terraform-plan"
      prometheus_workspace_id = "ws-00000000-0000-0000-0000-000000000000"
      demo_log_group_name     = "/sre-lab/otel-demo"
    }
  }
}

run "lab_matches_the_design" {
  command = plan

  # REQ-020: the pinned version in standard support; private API plus the allow-list.
  assert {
    condition     = aws_eks_cluster.lab.version == "1.36" && aws_eks_cluster.lab.upgrade_policy[0].support_type == "STANDARD"
    error_message = "EKS must run the pinned standard-support version and never enter extended support."
  }

  assert {
    condition     = aws_eks_cluster.lab.vpc_config[0].endpoint_private_access && aws_eks_cluster.lab.vpc_config[0].endpoint_public_access
    error_message = "The EKS API is private, with public access for the allow-list only."
  }

  assert {
    condition     = nonsensitive(aws_eks_cluster.lab.vpc_config[0].public_access_cidrs == toset(["203.0.113.7/32", "198.51.100.0/28"]))
    error_message = "The EKS public endpoint must be limited to the allow-list, split and trimmed."
  }

  assert {
    condition     = nonsensitive(aws_security_group_rule.public_alb_https_from_allowlist.cidr_blocks == tolist(["203.0.113.7/32", "198.51.100.0/28"]))
    error_message = "The public load balancer must accept HTTPS from the allow-list only."
  }

  # REQ-020.1: IMDSv2 with a hop limit of 1 on the nodes and the Rancher host.
  assert {
    condition     = aws_launch_template.eks_nodes.metadata_options[0].http_tokens == "required" && aws_launch_template.eks_nodes.metadata_options[0].http_put_response_hop_limit == 1
    error_message = "EKS nodes must require IMDSv2 with a hop limit of 1."
  }

  assert {
    condition     = aws_instance.rancher.metadata_options[0].http_tokens == "required" && aws_instance.rancher.metadata_options[0].http_put_response_hop_limit == 1
    error_message = "The Rancher host must require IMDSv2 with a hop limit of 1."
  }

  assert {
    condition     = aws_instance.rancher.root_block_device[0].encrypted && aws_launch_template.eks_nodes.block_device_mappings[0].ebs[0].encrypted == "true"
    error_message = "Volumes must be encrypted (SD-6)."
  }

  assert {
    condition     = aws_eks_node_group.default.ami_type == "AL2023_ARM_64_STANDARD" && aws_eks_node_group.default.scaling_config[0].desired_size == 2
    error_message = "Two Graviton nodes run the arm64 image."
  }

  # REQ-021.1: TLS 1.2 or later, the permanent layer's certificate, and a health
  # check on Rancher's /healthz.
  assert {
    condition     = alltrue([for listener in aws_lb_listener.rancher_https : listener.ssl_policy == "ELBSecurityPolicy-TLS13-1-2-2021-06"])
    error_message = "Both listeners must allow TLS 1.2 and 1.3 only."
  }

  assert {
    condition     = nonsensitive(aws_lb_listener.rancher_https["public"].certificate_arn) == "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
    error_message = "The listeners must use the certificate from the permanent layer."
  }

  assert {
    condition     = alltrue([for group in aws_lb_target_group.rancher : group.health_check[0].path == "/healthz" && group.health_check[0].protocol == "HTTPS" && group.port == 443])
    error_message = "Targets are Rancher on 443, checked on /healthz over HTTPS."
  }

  assert {
    condition     = aws_lb.rancher["internal"].internal && !aws_lb.rancher["public"].internal
    error_message = "One internet-facing and one internal load balancer."
  }

  # Split horizon: the same name in the public zone and in a private zone of the VPC.
  assert {
    condition     = nonsensitive(aws_route53_record.rancher_public.name) == "rancher.example.com" && aws_route53_record.rancher_public.zone_id == "Z0000000EXAMPLE"
    error_message = "rancher.<domain> must be built from the SSM parameter and live in the public zone."
  }

  assert {
    condition     = nonsensitive(aws_route53_zone.rancher_private.name) == "rancher.example.com"
    error_message = "The private zone must carry rancher.<domain> for the VPC."
  }

  # The rendered user data pins K3s and the Rancher chart by version and SHA-256.
  assert {
    condition = alltrue([
      for expected in [
        "hostname: rancher.example.com",
        "readonly K3S_VERSION='v1.36.6+k3s1'",
        "readonly K3S_VERSION_URL='v1.36.6%2Bk3s1'",
        "66ceb8e67edfa547195135d74783bfadc2ecc04a91059e90ae5f70a3dbc98c15",
        "46177d4c99440b4c0311b67233823a8e8a2fc09693f6c89af1a7161e152fbfad",
        "343888c66421a9f5666b562cdfeca751d63da994edbe7b1b36752f8ffcf5ecd4",
        "chart: https://%%{KUBERNETES_API}%/static/charts/rancher-2.15.3.tgz",
        "readonly ADMIN_SECRET='sre-lab/rancher-admin-password'",
        "agentTLSMode: system-store",
        "tls: external",
      ] : strcontains(nonsensitive(local.rancher_user_data), expected)
    ])
    error_message = "The user data must carry the pinned versions, their SHA-256 and the Rancher settings."
  }

  # The Rancher secrets: no value in Terraform, gone at teardown without a recovery window.
  assert {
    condition     = aws_secretsmanager_secret.rancher_agent_token.recovery_window_in_days == 0 && aws_secretsmanager_secret.rancher_admin_password.recovery_window_in_days == 0
    error_message = "Lab secrets are deleted at teardown so the next rebuild can create them again."
  }

  # REQ-013.1: the coding agent's read-only role and the CI role are refused the values.
  assert {
    condition = toset(one(data.aws_iam_policy_document.refuse_secret_reads.statement[0].condition).values) == toset([
      "arn:aws:iam::123456789012:role/aws-reserved/sso.amazonaws.com/*AWSReservedSSO_SreLabReadOnly_*",
      "arn:aws:iam::123456789012:role/sre-lab-ci-terraform-plan",
    ])
    error_message = "The Rancher secrets must refuse the coding agent's read-only role and the CI plan role."
  }

  assert {
    condition     = data.aws_iam_policy_document.rancher_host.statement[0].actions == toset(["secretsmanager:PutSecretValue"])
    error_message = "The Rancher host may only write the admin password."
  }

  # REQ-024, SD-1: the Collector's service account, and only it, gets the Collector's role.
  assert {
    condition     = aws_eks_pod_identity_association.collector.namespace == "observability" && aws_eks_pod_identity_association.collector.service_account == "otel-collector"
    error_message = "The role belongs to the service account observability/otel-collector, which platform/otel-collector creates."
  }

  assert {
    condition = (
      one(data.aws_iam_policy_document.collector_trust.statement[0].principals).identifiers == toset(["pods.eks.amazonaws.com"])
      && toset(data.aws_iam_policy_document.collector_trust.statement[0].actions) == toset(["sts:AssumeRole", "sts:TagSession"])
    )
    error_message = "Only EKS Pod Identity may assume the Collector's role."
  }

  assert {
    condition = [for statement in data.aws_iam_policy_document.collector.statement : statement.sid] == [
      "RemoteWriteToTheLabWorkspace",
      "WriteTheDemoLogGroup",
      "WriteTraceSpansInThisRegion",
    ]
    error_message = "The Collector may write metrics, demo logs and trace spans, and nothing else."
  }

  assert {
    condition = (
      data.aws_iam_policy_document.collector.statement[0].actions == toset(["aps:RemoteWrite"])
      && data.aws_iam_policy_document.collector.statement[0].resources == toset(["arn:aws:aps:us-east-1:123456789012:workspace/ws-00000000-0000-0000-0000-000000000000"])
      && data.aws_iam_policy_document.collector.statement[1].actions == toset(["logs:PutLogEvents"])
      && data.aws_iam_policy_document.collector.statement[1].resources == toset(["arn:aws:logs:us-east-1:123456789012:log-group:/sre-lab/otel-demo:log-stream:*"])
    )
    error_message = "Metrics go to the lab workspace and logs to the demo's log group only."
  }

  # X-Ray has no resource-level permissions for writing spans, so the statement is held to the Region.
  assert {
    condition = (
      data.aws_iam_policy_document.collector.statement[2].actions == toset(["xray:PutTraceSegments"])
      && one(data.aws_iam_policy_document.collector.statement[2].condition).variable == "aws:RequestedRegion"
      && one(data.aws_iam_policy_document.collector.statement[2].condition).values == tolist(["us-east-1"])
    )
    error_message = "Trace spans may be written in us-east-1 only."
  }
}

run "collector_role_waits_for_the_permanent_outputs" {
  command = plan

  # The permanent layer as it is before PR 2 is applied: none of the new outputs.
  override_data {
    target = data.terraform_remote_state.permanent
    values = {
      outputs = {
        rancher_certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
        public_zone_id          = "Z0000000EXAMPLE"
        ci_plan_role_name       = "sre-lab-ci-terraform-plan"
      }
    }
  }

  # The plan warns instead of failing, so CI can plan this root before you apply permanent.
  expect_failures = [check.permanent_layer_has_the_collector_destinations]

  assert {
    condition     = [for statement in data.aws_iam_policy_document.collector.statement : statement.sid] == ["WriteTraceSpansInThisRegion"]
    error_message = "Without the permanent layer's outputs, the role gets no metrics or logs permission."
  }
}

run "x86_node_fallback_uses_the_x86_image" {
  command = plan

  variables {
    node_instance_type = "t3.large"
  }

  assert {
    condition     = aws_eks_node_group.default.ami_type == "AL2023_x86_64_STANDARD"
    error_message = "A t3 node group needs the x86 image."
  }
}

run "version_out_of_standard_support_is_refused" {
  command = plan

  variables {
    kubernetes_version = "1.33"
  }

  expect_failures = [aws_eks_cluster.lab]
}

run "open_allow_list_is_refused" {
  command = plan

  override_data {
    target = data.aws_ssm_parameter.allowlist_cidrs
    values = {
      value = "0.0.0.0/0"
    }
  }

  expect_failures = [
    aws_eks_cluster.lab,
    aws_security_group_rule.public_alb_https_from_allowlist,
  ]
}
