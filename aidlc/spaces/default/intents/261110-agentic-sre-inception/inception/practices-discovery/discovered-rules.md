# Discovered Rules

> Hard constraints stated by the human, in `CLAUDE.md`, the Phase 0 runbook, or the practices interview of 2026-11-10.

## Mandated

- ALWAYS deliver changes to clusters through Git (Fleet bundles under `platform/`) and changes to cloud resources through Terraform pull requests. (CLAUDE.md, Safety rules)
- ALWAYS use read-only credentials by default, and ask the human before using any credential with write access. (CLAUDE.md, Safety rules)
- ALWAYS verify infrastructure and cluster changes with non-mutating commands only: `terraform plan`, `kubectl diff`, `kustomize build`, `helm template` or `--dry-run`. (CLAUDE.md, Safety rules)
- ALWAYS leave `terraform apply` to the human, who runs it locally from the merged `main` for Phases 1 to 3. (CLAUDE.md, Safety rules; interview Q4)
- ALWAYS run `terraform fmt` and `terraform validate` before proposing a Terraform change, and pin provider versions. (CLAUDE.md, Engineering conventions)
- ALWAYS squash-merge pull requests into `main`, one commit per PR. (interview Q1)
- ALWAYS pin GitHub Actions by commit SHA and container images by digest from Phase 1 onward. (interview Q6)
- ALWAYS enforce 80% line coverage on all Python code in CI before merge, without lowering the floor to make a build pass. (interview Q8)
- ALWAYS run Ruff (lint and format), a Python type checker, ShellCheck, and `terraform fmt`/`validate` in CI as blocking checks. (interview Q9)
- ALWAYS write acceptance criteria in EARS form ("WHEN ..., THE SYSTEM SHALL ...") with a `REQ-NNN` ID, and cite those IDs in tasks, commits, PRs, tests and eval scenarios. (CLAUDE.md, Method)
- ALWAYS name a branch `<type>/REQ-NNN-<topic>` when the work has a requirement ID, and `<type>/<topic>` when it has none. (interview Q2, Q11)
- ALWAYS record each significant decision as an ADR in `docs/adr/` from `0000-template.md`, including AI suggestions the human rejected. (CLAUDE.md, Method)
- ALWAYS use Conventional Commits, keep the `Co-Authored-By` trailer Claude Code adds, and keep each PR to one task. (CLAUDE.md, Commits and pull requests)
- ALWAYS fill in the PR template's "AI involvement" section honestly: what the AI generated and what the human changed or rejected. (CLAUDE.md; enforced by `tools/ci/check_pr_body.py`)
- ALWAYS work through `/aidlc` and pass its approval gates. (CLAUDE.md, Method)

## Forbidden

- NEVER run `terraform apply` or `terraform destroy`; the human applies. (CLAUDE.md, Safety rules; enforced by `tools/claude-hooks/guard-bash.sh`)
- NEVER run kubectl write commands (`apply`, `create`, `delete`, `patch`, `edit`, `scale`). (CLAUDE.md, Safety rules)
- NEVER run `helm install`, `helm upgrade` or `helm uninstall`. (CLAUDE.md, Safety rules)
- NEVER run cloud delete commands. (CLAUDE.md, Safety rules)
- NEVER write secrets, tokens, kubeconfigs or account IDs into files, commits, PRs or logs; use environment variables, AWS Secrets Manager or AgentCore Identity. (CLAUDE.md, Safety rules)
- NEVER edit or delete AI-DLC records under `aidlc/` by hand. (CLAUDE.md, Method)
- NEVER push directly to `main` or force-push it; every change reaches `main` through a pull request the human merges. (docs/runbooks/phase-0.md, ruleset "main"; interview Q3)
