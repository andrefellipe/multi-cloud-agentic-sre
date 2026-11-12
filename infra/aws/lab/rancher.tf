# The Rancher host (LC17): one t3.large with Ubuntu 24.04, running K3s and Rancher
# at pinned versions, installed at first boot by templates/rancher-host-user-data.sh.tftpl.
# No SSH and no key pair: administration goes through Session Manager. It answers
# on 443 only to the two load balancers (network.tf). Rancher generates its own
# admin password, which the host writes to Secrets Manager; Terraform never sees it.

data "aws_iam_policy_document" "rancher_host_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "rancher_host" {
  name               = "sre-lab-rancher-host"
  description        = "Rancher host: Session Manager, and writing the generated admin password."
  assume_role_policy = data.aws_iam_policy_document.rancher_host_trust.json
}

resource "aws_iam_role_policy_attachment" "rancher_host_ssm" {
  role       = aws_iam_role.rancher_host.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# The host may write the admin password, and nothing else. It cannot read it back.
data "aws_iam_policy_document" "rancher_host" {
  statement {
    sid       = "WriteTheAdminPasswordOnly"
    actions   = ["secretsmanager:PutSecretValue"]
    resources = [aws_secretsmanager_secret.rancher_admin_password.arn]
  }
}

resource "aws_iam_role_policy" "rancher_host" {
  name   = "write-admin-password"
  role   = aws_iam_role.rancher_host.id
  policy = data.aws_iam_policy_document.rancher_host.json
}

resource "aws_iam_instance_profile" "rancher_host" {
  name = "sre-lab-rancher-host"
  role = aws_iam_role.rancher_host.name
}

locals {
  rancher_user_data = templatefile("${path.module}/templates/rancher-host-user-data.sh.tftpl", {
    region                = local.region
    rancher_hostname      = local.rancher_fqdn
    admin_secret_name     = aws_secretsmanager_secret.rancher_admin_password.name
    k3s_version           = var.k3s_version
    k3s_version_url       = replace(var.k3s_version, "+", "%2B")
    k3s_sha256            = var.k3s_sha256
    k3s_install_sha256    = var.k3s_install_script_sha256
    rancher_chart_version = var.rancher_chart_version
    rancher_chart_sha256  = var.rancher_chart_sha256
    # The host has no AWS CLI; this standard-library script writes the password.
    put_secret_value_b64 = filebase64("${path.module}/../../../tools/lab/rancher_host/put_secret_value.py")
  })
}

resource "aws_instance" "rancher" {
  ami                         = data.aws_ssm_parameter.ubuntu_ami.insecure_value
  instance_type               = var.rancher_instance_type
  subnet_id                   = aws_subnet.public[0].id
  vpc_security_group_ids      = [aws_security_group.rancher.id]
  iam_instance_profile        = aws_iam_instance_profile.rancher_host.name
  associate_public_ip_address = true
  # Compressed: cloud-init unpacks it. The rendered script holds your domain, so
  # Terraform shows it as sensitive in the plan.
  user_data_base64            = base64gzip(local.rancher_user_data)
  user_data_replace_on_change = true

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = 30
    encrypted             = true
    delete_on_termination = true

    tags = {
      Name = "sre-lab-rancher"
    }
  }

  tags = {
    Name = "sre-lab-rancher"
  }

  lifecycle {
    # Each rebuild takes the newest Ubuntu image; within one lab, a new image
    # published by Canonical does not replace the running host.
    ignore_changes = [ami]
  }

  depends_on = [
    aws_iam_role_policy.rancher_host,
    aws_secretsmanager_secret_policy.rancher_admin_password,
  ]
}
