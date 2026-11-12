output "dashboard_url" {
  description = "The skeleton dashboard in the Managed Grafana workspace."
  value       = grafana_dashboard.skeleton.url
}
