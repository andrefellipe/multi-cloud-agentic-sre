# infra

Terraform root modules: `aws/` (VPC, EKS, Managed Prometheus, AgentCore, Knowledge Base, Route 53, budgets) and `azure/` (AKS). AWS arrives in Phase 1 and Azure in Phase 5. Claude proposes changes and runs `terraform plan`; you run `terraform apply`.
