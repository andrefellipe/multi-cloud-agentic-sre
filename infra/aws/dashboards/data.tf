# The dashboards root reads what it needs from the permanent layer's outputs (SC-5).
data "terraform_remote_state" "permanent" {
  backend = "s3"

  config = {
    bucket = "multi-cloud-agentic-sre-tfstate"
    key    = "permanent/terraform.tfstate"
    region = "us-east-1"
  }
}

locals {
  region              = "us-east-1"
  prometheus_endpoint = data.terraform_remote_state.permanent.outputs.prometheus_endpoint
}
