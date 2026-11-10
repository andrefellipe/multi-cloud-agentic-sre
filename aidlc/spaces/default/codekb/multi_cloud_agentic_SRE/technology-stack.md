# Technology Stack

## In the repository today

| Technology | Version | Where | Purpose |
| --- | --- | --- | --- |
| Bash | macOS bash 3.2 compatible; `/usr/bin/env bash` | `tools/claude-hooks/*.sh` | Guard hook and its tests |
| POSIX/BSD tools (`grep -E`, `awk`, `tr`, `date`) | system | `guard-bash.sh` | Parsing and matching |
| Python | `python3` from `ubuntu-latest`, unpinned; standard library only | `tools/ci/check_pr_body.py` | PR description check |
| GitHub Actions | `actions/checkout@v5` (tag) | `.github/workflows/methodology-checks.yml` | CI |
| Claude Code hooks | PreToolUse, `onFailure: block` (Claude Code 2.1.322 per ADR-0004) | `tools/claude-hooks/settings.hooks.json` | Guardrail |
| MCP (Model Context Protocol) | `mcp-proxy-for-aws@1.8.0`, `awslabs.aws-pricing-mcp-server@1.1.1`, `awslabs.aws-iac-mcp-server@1.0.26`, `awslabs.aws-serverless-mcp-server@0.2.1`, `context7` HTTP | `.mcp.json` | Coding-agent tools (AI-DLC-provided entries) |
| OpenTelemetry Collector contrib | `latest` image (runbook) | `tools/otel/collector-local.yaml` | Spike C |
| Kubernetes manifest | `v1` Namespace, ServiceAccount, Pod | `tools/spikes/spike-b-pod.yaml` | Spike B |
| AWS CLI image | `amazon/aws-cli:latest` | spike B pod | Spike B |
| IAM policy language | `2012-10-17` | `tools/spikes/spike-b-trust-policy.json` | Spike B |
| Rancher | `rancher/rancher:v2.15.0` | runbook spike A user data | Spike A |
| Markdown, PNG | n/a | `docs/` | Documentation |

## Required by project rules but not yet present

From `CLAUDE.md` "Engineering conventions":

- Python 3.12+ managed with `uv`, type hints, `pytest` (no `pyproject.toml` or `uv.lock` yet)
- Terraform with pinned provider versions, `terraform fmt` and `terraform validate` (no `.tf` files yet)
- Fleet bundles with kustomize overlays per cloud (`cloud=aws`, `cloud=azure`) (no manifests yet)
- Formatter and linter defaults from `org.md`: Black and Ruff for Python (not configured)

## Planned stack (from `docs/plan.md`; nothing installed)

| Layer | Choice |
| --- | --- |
| Workload clusters | Amazon EKS (current Kubernetes version), Azure AKS Free tier |
| Demo app | OpenTelemetry Demo (Astronomy Shop) with flagd feature flags |
| Multi-cluster | Rancher on K3s (one EC2 instance) + Fleet |
| Telemetry | OpenTelemetry Collector -> Amazon Managed Service for Prometheus, CloudWatch; Grafana |
| Alerting | Managed Prometheus Alertmanager -> SNS -> Lambda |
| Incident state | DynamoDB (conditional writes) |
| Agent runtime | Amazon Bedrock AgentCore Runtime (sessions: 15 min idle, 8 h max) |
| Agent framework | Strands Agents (graph + agents-as-tools) |
| Models | Claude on Bedrock via `us.` inference profiles: Haiku 4.5 (small), Sonnet 4.6 (large), Opus 4.6 (reviewer) |
| Tools | AgentCore Gateway MCP targets: `rancher/rancher-ai-mcp`, Prometheus, CloudWatch Logs, GitHub |
| Governance | AgentCore Policy (Cedar), Bedrock Guardrails |
| Memory | AgentCore Memory (episodic), Bedrock Knowledge Base on S3 Vectors |
| Identity | AgentCore Identity, IAM roles, OIDC federation (GitHub OIDC, AKS workload identity) |
| Observability | AgentCore Observability (OpenTelemetry) |
| Evaluation | AgentCore Evaluations, custom evaluators, replay harness |
| Chaos | OTel Demo flags, AWS FIS `aws:eks:pod-*` (EKS 1.30+), Azure Chaos Studio (Chaos Mesh) |
| Traffic | Route 53 weighted records with health checks |
| Source, CI, IaC | GitHub, GitHub Actions, Terraform; Claude Code GitHub Action on Bedrock |
| UI | Slack; React/Vite console |
| Regions | AWS `us-east-1`, Azure East US |

## Local toolchain named by the runbook

`terraform` (HashiCorp tap), `gh`, `awscli`, `azure-cli`, `kubectl`, `helm`, `jq`, `uv`, Claude Code native installer, Docker Desktop or OrbStack. None are pinned to versions in the repository.
