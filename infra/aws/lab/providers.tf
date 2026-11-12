provider "aws" {
  region = "us-east-1"

  # REQ-131.1: everything here is billed by the hour and removed at teardown (SC-5).
  default_tags {
    tags = local.default_tags
  }
}

locals {
  default_tags = {
    project           = "multi-cloud-agentic-sre"
    layer             = "lab"
    "teardown-policy" = "destroy"
  }
}
