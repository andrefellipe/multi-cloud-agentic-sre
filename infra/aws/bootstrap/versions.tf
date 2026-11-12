# Terraform and provider pins for the bootstrap root (REQ-112.1).
#
# The AWS provider is pinned to one exact version, the same in every root under
# infra/aws, and .terraform.lock.hcl is committed with the linux_amd64 (CI) and
# darwin_arm64 (your Mac) hashes.
#
# This root creates the bucket its own backend points at. The first apply runs
# with local state, through a backend_override.tf you create and delete again;
# README.md has the steps, including the ownership check before any init.

terraform {
  required_version = "~> 1.17.1"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.73.0"
    }
  }

  backend "s3" {
    bucket       = "multi-cloud-agentic-sre-tfstate"
    key          = "bootstrap/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
