# The skeleton's one Grafana dashboard (REQ-024.1, OD-6), kept as JSON in
# platform/dashboards/skeleton.json, and the two data sources it reads. Both data
# sources sign in as the workspace's own IAM role (infra/aws/permanent/grafana.tf),
# which may read CloudWatch and query Managed Prometheus, and nothing else. The
# dashboard refers to them by the fixed UIDs below.

# Managed Grafana 12 and later query Managed Prometheus through its own plugin;
# the core Prometheus data source no longer signs requests with SigV4.
resource "grafana_data_source" "prometheus" {
  type       = "grafana-amazonprometheus-datasource"
  name       = "Managed Prometheus (sre-lab)"
  uid        = "sre-lab-amp"
  url        = local.prometheus_endpoint
  is_default = true

  json_data_encoded = jsonencode({
    httpMethod    = "POST"
    sigV4Auth     = true
    sigV4AuthType = "ec2_iam_role"
    sigV4Region   = local.region
    # The Collector exports span metrics every 60 s.
    timeInterval = "60s"
  })
}

resource "grafana_data_source" "cloudwatch" {
  type = "cloudwatch"
  name = "CloudWatch (sre-lab)"
  uid  = "sre-lab-cloudwatch"

  json_data_encoded = jsonencode({
    authType      = "ec2_iam_role"
    defaultRegion = local.region
  })
}

resource "grafana_folder" "sre_lab" {
  title = "SRE lab"
  uid   = "sre-lab"
}

resource "grafana_dashboard" "skeleton" {
  folder      = grafana_folder.sre_lab.uid
  config_json = file("${path.module}/../../../platform/dashboards/skeleton.json")

  depends_on = [
    grafana_data_source.prometheus,
    grafana_data_source.cloudwatch,
  ]
}
