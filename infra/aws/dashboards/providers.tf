# The Managed Grafana workspace's API. The URL comes from the permanent layer.
# The token comes from the GRAFANA_AUTH environment variable: a 30-minute token
# of the terraform-dashboards service account, which you create just before you
# plan and apply (docs/runbooks/phase-1-skeleton.md). It is never a Terraform
# variable, so it is not saved in a plan file, and Terraform never stores it.
provider "grafana" {
  url = data.terraform_remote_state.permanent.outputs.grafana_url
}
