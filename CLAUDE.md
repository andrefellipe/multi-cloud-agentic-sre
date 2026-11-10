# Project rules for Claude: Multi-Cloud Agentic SRE

## What this project is

An open SRE agent system on AWS (Bedrock AgentCore, Strands Agents, Claude on Bedrock). It investigates incidents on Amazon EKS and Azure AKS through Rancher, proposes fixes only as pull requests, and verifies recovery after a human merges. The plan is in `docs/plan.md`; the current phase and its steps are in `README.md` and `docs/runbooks/`.

## Method: AI-DLC

- Work through `/aidlc` (awslabs/aidlc-workflows). Don't skip its approval gates. Its records in `aidlc/` are project evidence: never edit or delete them by hand.
- Treat `docs/plan.md` as input to question, not as settled requirements.
- Phrase acceptance criteria in EARS ("WHEN ..., THE SYSTEM SHALL ...") and give each an ID (REQ-001). Reference the IDs in tasks, commits, PRs, tests and eval scenarios.
- Record each significant decision as an ADR in `docs/adr/` (copy `0000-template.md`), including suggestions of yours that the human rejected.

## Safety rules

- Never run `terraform apply` or `destroy`, kubectl write commands (`apply`, `create`, `delete`, `patch`, `edit`, `scale`), `helm install`, `upgrade` or `uninstall`, or cloud delete commands. Use `terraform plan`, `kubectl diff`, `kustomize build`, `helm template` or `--dry-run`; the human applies. The hook in `tools/claude-hooks/` enforces this.
- Never write secrets, tokens, kubeconfigs or account IDs into files, commits, PRs or logs. Use environment variables, AWS Secrets Manager or AgentCore Identity.
- Changes reach clusters only through Git (Fleet) and reach cloud resources only through Terraform PRs.
- Use read-only credentials by default. Ask before using anything with write access.

## Engineering conventions

- Python 3.12+ managed with `uv`, type hints and `pytest` for agents and tools.
- Terraform: root modules under `infra/aws` and `infra/azure`, pinned provider versions, `terraform fmt` and `terraform validate` before proposing a change.
- Kubernetes manifests under `platform/` as Fleet bundles, with kustomize overlays per cloud (`cloud=aws`, `cloud=azure`).
- Small changes: one task per PR.

## Commits and pull requests

- Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`), with requirement IDs when they apply.
- Keep the `Co-Authored-By` trailer that Claude Code adds.
- Fill in the PR template's "AI involvement" section honestly: what you generated, and what the human changed or rejected. CI fails if it's empty.
