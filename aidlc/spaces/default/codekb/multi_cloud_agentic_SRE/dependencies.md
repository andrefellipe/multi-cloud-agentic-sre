# Dependencies

## External dependencies (present)

| Dependency | Version / pin | Consumer | Pin quality | Notes |
| --- | --- | --- | --- | --- |
| `actions/checkout` | `@v5` | `methodology-checks.yml` | Tag, not SHA | Plan's ASI04 control asks for pins by version and digest |
| GitHub-hosted runner | `ubuntu-latest` | `methodology-checks.yml` | Floating | Provides `bash` and `python3` |
| Python 3 | runner default | `check_pr_body.py` | Floating | Standard library only (`os`, `re`, `sys`); no third-party packages |
| `mcp-proxy-for-aws` | `1.8.0` | `.mcp.json` `aws-mcp` | Exact version, no hash | Launched through `uvx`; uses the shell's AWS credential chain |
| `awslabs.aws-pricing-mcp-server` | `1.1.1` | `.mcp.json` | Exact version | via `uvx` |
| `awslabs.aws-iac-mcp-server` | `1.0.26` | `.mcp.json` | Exact version | via `uvx` |
| `awslabs.aws-serverless-mcp-server` | `0.2.1` | `.mcp.json` | Exact version | via `uvx`; includes deploy tools (`sam_deploy`, `deploy_webapp`) |
| `context7` | HTTP endpoint | `.mcp.json` | None | Reads `CONTEXT7_API_KEY` from env |
| `otel/opentelemetry-collector-contrib` | `latest` | runbook spike C | Floating | Runbook says to pin once it works |
| `amazon/aws-cli` | `latest` | `tools/spikes/spike-b-pod.yaml` | Floating | Throwaway spike |
| `rancher/rancher` | `v2.15.0` | runbook spike A | Tag | Throwaway spike |
| `uv` / `uvx` | unpinned (Homebrew) | MCP server launch | Floating | |

No `requirements.txt`, `pyproject.toml`, `uv.lock`, `package.json`, `.terraform.lock.hcl` or Helm chart lock exists, so there is nothing for a dependency-review tool to read yet.

## Internal dependencies

```
.github/workflows/methodology-checks.yml
  -> tools/claude-hooks/test-guard.sh -> tools/claude-hooks/guard-bash.sh
  -> tools/ci/check_pr_body.py ~> .github/pull_request_template.md (label strings)

.claude/settings.json (PreToolUse, matcher Bash)
  -> tools/claude-hooks/guard-bash.sh -> docs/evidence/hook-audit.jsonl

tools/claude-hooks/settings.hooks.json  (merged into .claude/settings.json by a human with jq)

docs/runbooks/phase-0.md
  -> tools/github-setup/{pull_request_template.md, methodology-checks.yml}
  -> tools/claude-hooks/{settings.hooks.json, test-guard.sh}
  -> tools/otel/collector-local.yaml
  -> tools/spikes/{spike-b-pod.yaml, spike-b-trust-policy.json}
```

`~>` marks an implicit dependency by matching text: renaming a label in the template without changing the script breaks every PR.

## External services the project depends on (operational)

| Service | Used for | Present how |
| --- | --- | --- |
| GitHub (repository, Actions, rulesets) | Source, CI, human merge gate | Workflow and template present; ruleset configured by hand per runbook, not exported yet |
| AWS (IAM Identity Center, Budgets, Bedrock, EC2, IAM) | Phase 0 accounts and spikes | Runbook steps only |
| Azure (AKS, Cost Management, Chaos provider) | Phase 0 spike B | Runbook steps only |
| Anthropic Claude Code | Coding agent and hooks | `CLAUDE.md`, `.claude/settings.json` |

## Dependency risks relevant to the intent

- **Credential inheritance**: every `uvx`-launched AWS MCP server and every Bash call inherits the shell's `AWS_PROFILE`. The runbook's profile `sre-lab` has `AdministratorAccess`.
- **Gate dependency on the PR tree**: CI's correctness depends on files the PR itself can change (`test-guard.sh`, `guard-bash.sh`, `check_pr_body.py`, the workflow).
- **Settings rewrite**: running `aidlc config --harness claude` again rewrites `.claude/settings.json` and drops the guard (ADR-0004, Consequences).
