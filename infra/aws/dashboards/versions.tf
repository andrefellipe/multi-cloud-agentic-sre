# Terraform and provider pins for the dashboards root (REQ-112.1, REQ-024.1).
#
# The Grafana provider is pinned to one exact version, and .terraform.lock.hcl is
# committed with the linux_amd64 (CI) and darwin_arm64 (your Mac) hashes. This
# root needs no AWS provider: it reads the permanent layer's state through the S3
# backend, with the credentials of your shell.
#
# CI formats and validates this root but never plans it: planning needs a
# Grafana token, which only you create, at apply time (cicd-pipeline.md).

terraform {
  required_version = "~> 1.17.1"

  required_providers {
    grafana = {
      source  = "grafana/grafana"
      version = "4.54.0"
    }
  }

  backend "s3" {
    bucket       = "multi-cloud-agentic-sre-tfstate"
    key          = "dashboards/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
