# Terraform and provider pins for the permanent layer (REQ-112.1, REQ-131.1).
#
# The AWS provider is pinned to one exact version, the same in every root under
# infra/aws, and .terraform.lock.hcl is committed with the linux_amd64 (CI) and
# darwin_arm64 (your Mac) hashes. Change the version in every root together.
#
# The S3 backend is written in full because CI plans with no -backend-config.
# The bucket comes from infra/aws/bootstrap; confirm you own it before the first
# init (docs/runbooks/phase-1-skeleton.md, "Before any init").

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
    key          = "permanent/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
