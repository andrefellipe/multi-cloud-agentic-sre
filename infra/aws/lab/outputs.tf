output "rancher_url" {
  description = "Rancher's address, https://rancher.<domain>. Read it with terraform output -raw rancher_url."
  value       = "https://${local.rancher_fqdn}"
  sensitive   = true
}

output "eks_cluster_name" {
  description = "The lab's EKS cluster."
  value       = aws_eks_cluster.lab.name
}

output "kubernetes_version" {
  description = "The cluster's Kubernetes version, in EKS standard support (REQ-020)."
  value       = aws_eks_cluster.lab.version
}

output "update_kubeconfig_command" {
  description = "Points your kubectl at the cluster, to run Rancher's registration command."
  value       = "aws eks update-kubeconfig --region ${local.region} --name ${aws_eks_cluster.lab.name}"
}

output "rancher_instance_id" {
  description = "The Rancher host, for Session Manager: aws ssm start-session --target <id>."
  value       = aws_instance.rancher.id
}

output "rancher_admin_password_secret" {
  description = "The secret the Rancher host writes the admin password to."
  value       = aws_secretsmanager_secret.rancher_admin_password.name
}

output "rancher_agent_token_secret" {
  description = "The secret configure_rancher.py writes the sre-agent token to."
  value       = aws_secretsmanager_secret.rancher_agent_token.name
}
