provider "aws" {
  region = "us-east-1"

  # REQ-131.1: every resource carries the project and its teardown policy. The
  # state bucket outlives every teardown, like the permanent layer.
  default_tags {
    tags = {
      project           = "multi-cloud-agentic-sre"
      layer             = "permanent"
      "teardown-policy" = "keep"
    }
  }
}
