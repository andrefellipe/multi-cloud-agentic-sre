# terraform test for infra/aws/dashboards, with a mocked Grafana provider: no
# token, no Grafana call, no state. It checks what `terraform validate` cannot:
# the data sources sign in as the workspace's IAM role, and the dashboard reads
# only them. Values are synthetic.
#
# Run it with: terraform -chdir=infra/aws/dashboards init -backend=false && terraform -chdir=infra/aws/dashboards test

mock_provider "grafana" {}

override_data {
  target = data.terraform_remote_state.permanent
  values = {
    outputs = {
      grafana_url         = "https://g-0000000000.grafana-workspace.us-east-1.amazonaws.com"
      prometheus_endpoint = "https://aps-workspaces.us-east-1.amazonaws.com/workspaces/ws-00000000-0000-0000-0000-000000000000/"
    }
  }
}

run "dashboards_match_the_design" {
  command = plan

  # Managed Grafana 12 and later reach Managed Prometheus through its own plugin, signed with SigV4.
  assert {
    condition = (
      grafana_data_source.prometheus.type == "grafana-amazonprometheus-datasource"
      && grafana_data_source.prometheus.uid == "sre-lab-amp"
      && grafana_data_source.prometheus.url == "https://aps-workspaces.us-east-1.amazonaws.com/workspaces/ws-00000000-0000-0000-0000-000000000000/"
    )
    error_message = "The Prometheus data source must use the Managed Prometheus plugin and the permanent layer's workspace."
  }

  assert {
    condition = (
      jsondecode(grafana_data_source.prometheus.json_data_encoded).sigV4Auth
      && jsondecode(grafana_data_source.prometheus.json_data_encoded).sigV4AuthType == "ec2_iam_role"
      && jsondecode(grafana_data_source.prometheus.json_data_encoded).sigV4Region == "us-east-1"
    )
    error_message = "Managed Prometheus is queried as the workspace's IAM role, in us-east-1."
  }

  assert {
    condition = (
      grafana_data_source.cloudwatch.uid == "sre-lab-cloudwatch"
      && jsondecode(grafana_data_source.cloudwatch.json_data_encoded) == { authType = "ec2_iam_role", defaultRegion = "us-east-1" }
    )
    error_message = "CloudWatch is read as the workspace's IAM role, in us-east-1."
  }

  # REQ-024.1: one dashboard, reading only the two data sources above.
  assert {
    condition = toset(flatten([
      for panel in jsondecode(grafana_dashboard.skeleton.config_json).panels : [
        for target in try(panel.targets, []) : target.datasource.uid
      ]
    ])) == toset(["sre-lab-amp", "sre-lab-cloudwatch"])
    error_message = "The dashboard must read only the sre-lab-amp and sre-lab-cloudwatch data sources."
  }

  assert {
    condition     = jsondecode(grafana_dashboard.skeleton.config_json).uid == "sre-lab-skeleton" && grafana_dashboard.skeleton.folder == "sre-lab"
    error_message = "The skeleton dashboard keeps its UID and lives in the SRE lab folder."
  }
}
