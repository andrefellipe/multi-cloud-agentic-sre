provider "aws" {
  region = "us-east-1"

  # REQ-131.1: the permanent layer is never torn down (SC-5).
  default_tags {
    tags = {
      project           = "multi-cloud-agentic-sre"
      layer             = "permanent"
      "teardown-policy" = "keep"
    }
  }
}
