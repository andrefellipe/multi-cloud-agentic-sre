# Managed Prometheus (LC13) and the demo's log group (LC12): where the platform
# Collector in the lab cluster sends the demo's telemetry (REQ-024, REQ-130.2).
# Both live in the permanent layer, so a lab teardown keeps them. The Collector's
# role, in infra/aws/lab, may write to them and to nothing else.

# The workspace's own error and warning events (alert manager and rule
# evaluation, for example a failed publish to the lab topic), kept 14 days like
# the pipeline's other logs. The vendedlogs prefix keeps the delivery resource
# policy that AWS adds small.
resource "aws_cloudwatch_log_group" "prometheus" {
  name              = "/aws/vendedlogs/prometheus/sre-lab"
  retention_in_days = 14
}

resource "aws_prometheus_workspace" "sre_lab" {
  alias = "sre-lab"

  logging_configuration {
    log_group_arn = "${aws_cloudwatch_log_group.prometheus.arn}:*"
  }
}

# The demo's logs, at warning level and above, kept 3 days (REQ-130.2). The
# Collector writes through the CloudWatch Logs OTLP endpoint, which needs the log
# group and the stream to exist; the stream is named after the cluster.
resource "aws_cloudwatch_log_group" "demo" {
  name              = "/sre-lab/otel-demo"
  retention_in_days = 3
}

resource "aws_cloudwatch_log_stream" "demo_eks" {
  name           = "sre-lab-eks"
  log_group_name = aws_cloudwatch_log_group.demo.name
}
