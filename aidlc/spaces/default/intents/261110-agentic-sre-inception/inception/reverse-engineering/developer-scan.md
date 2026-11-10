# Developer Code Scan: multi_cloud_agentic_SRE

- Scan date: 2026-11-10T06:15:07Z
- Commit: 69ec4cdd4a3272eb67a1ff9cc6f22b40a9d4a315 (branch `inception/requirements`)
- Breadth: full scan of the project's own files (first scan, no existing code knowledge store)
- Method: read-only. No project test, build or program was run; the facts below come from reading the files and `git log --stat`.

## Developer Code Scan Results

### Scan Coverage
- **Analyzed deeply**:
  - `CLAUDE.md`
  - `README.md`
  - `.gitignore` (project part above the `BEGIN AI-DLC:gitignore` marker)
  - `.mcp.json` (as a fact of the guardrail setup only; all five entries are AI-DLC root contributions whose versions the project pinned in commit 69ec4cd)
  - `.github/pull_request_template.md`
  - `.github/workflows/methodology-checks.yml`
  - `tools/claude-hooks/guard-bash.sh`
  - `tools/claude-hooks/test-guard.sh`
  - `tools/claude-hooks/settings.hooks.json`
  - `tools/claude-hooks/README.md`
  - `tools/ci/check_pr_body.py`
  - `tools/github-setup/` (README, staged PR template, staged workflow; compared with the installed copies)
  - `tools/otel/collector-local.yaml`
  - `tools/spikes/spike-b-pod.yaml`, `tools/spikes/spike-b-trust-policy.json`
  - `docs/plan.md`
  - `docs/runbooks/phase-0.md`
  - `docs/adr/0000-template.md`, `docs/adr/0001-adopt-ai-dlc-and-project-plan.md`, `docs/adr/0004-guardrail-hook-fails-closed.md`
  - `docs/evidence/README.md`, `docs/evidence/hook-audit.jsonl`, `docs/evidence/rulesets/.gitkeep`, `docs/evidence/telemetry/.gitkeep`
  - `docs/diagrams/architecture.png`, `docs/diagrams/incident-lifecycle.png`, `docs/diagrams/roadmap.png` (viewed as images)
  - `agents/README.md`, `console/README.md`, `evals/README.md`, `infra/README.md`, `platform/README.md`
  - `.claude/settings.json`: read only to establish which project hook is wired and which tool matcher it uses, plus the `permissions.allow` list (no AI-DLC internals documented)
- **Skimmed only**: none
- **Left out**:
  - `.claude/` (AI-DLC install: agents, hooks, skills, tools, knowledge, scopes, sensors), apart from the one settings fact above
  - `aidlc/` (AI-DLC workspace and records)
  - `.git/`
  - `.DS_Store` (OS metadata)
  - AI-DLC's managed block in `.gitignore`

### Packages Found
- `tools/claude-hooks` — developer guardrail (Claude Code PreToolUse hook and its test script) — Bash (POSIX tools, macOS bash 3.2 compatible) — blocks commands only a human may run and writes an audit line per block
- `tools/ci` — CI check script — Python 3 (standard library only: `os`, `re`, `sys`) — fails a PR whose description lacks the "AI involvement" fields or requirement IDs
- `.github` — GitHub configuration — YAML / Markdown — the `methodology-checks` workflow (job `pr-evidence`) and the PR template
- `tools/github-setup` — staging copies of the `.github/` files — YAML / Markdown — bootstrap only; the README says it can be deleted
- `tools/otel` — local OpenTelemetry Collector config for spike C — YAML — OTLP gRPC/HTTP in, `debug` exporter out (metrics only)
- `tools/spikes` — spike B fixtures — Kubernetes YAML and IAM JSON with placeholders (`ACCOUNT_ID`, `OIDC_PROVIDER_ARN`, `ISSUER_HOST_AND_PATH`) — test whether an AKS pod can assume an IAM role with no static keys
- `docs` — plan, Phase 0 runbook, ADRs, evidence folder, diagrams — Markdown / JSONL / PNG
- `agents`, `console`, `evals`, `infra`, `platform` — placeholders, each a one-paragraph README and no code (arrive in Phases 1, 2, 4 and 7)

There is no Python package, no `pyproject.toml`, no `uv.lock`, no Terraform, no Kubernetes or Fleet manifest outside the spike, no Strands agent code and no front-end.

### Build System
- **Type**: none. No build manifest exists (`pyproject.toml`, `requirements.txt`, `package.json`, `*.tf`, `Makefile`, `Dockerfile`, `fleet.yaml`, `kustomization.yaml` are all absent).
- **Config Files**: `.github/workflows/methodology-checks.yml` (the only automation); `tools/claude-hooks/settings.hooks.json` (hook fragment merged by a human into `.claude/settings.json`); `.mcp.json` (MCP servers available to the coding agent); `.gitignore`.
- **Build Dependencies**:
  - `methodology-checks.yml` -> `tools/claude-hooks/test-guard.sh` -> `tools/claude-hooks/guard-bash.sh`
  - `methodology-checks.yml` -> `tools/ci/check_pr_body.py` (reads `PR_BODY` env) -> `.github/pull_request_template.md` (field labels must match)
  - `.claude/settings.json` (PreToolUse, matcher `Bash`) -> `tools/claude-hooks/guard-bash.sh` -> `docs/evidence/hook-audit.jsonl`
  - `docs/runbooks/phase-0.md` -> `tools/github-setup/*`, `tools/claude-hooks/*`, `tools/otel/collector-local.yaml`, `tools/spikes/*`

### APIs Discovered
- No network API (REST, GraphQL, gRPC, webhook handler, Lambda handler) exists in the repository.
- Process contract — `tools/claude-hooks/guard-bash.sh` — 1 contract: stdin is the Claude Code hook JSON; exit 0 allows, exit 2 blocks with a message on stderr; each block appends `{"ts","event":"blocked","rule"}` to `docs/evidence/hook-audit.jsonl`.
- Process contract — `tools/ci/check_pr_body.py` — 1 contract: reads env `PR_BODY`; exit 0 passes, exit 1 lists failures on stdout.
- CI job — `.github/workflows/methodology-checks.yml` — 1 job (`pr-evidence`) on `pull_request` events `opened, edited, synchronize, reopened, ready_for_review`, with `permissions: contents: read`.
- Planned, not implemented (from `docs/plan.md`): alert path Managed Prometheus Alertmanager -> SNS -> Lambda; GitHub merge webhook -> Lambda -> Verifier; AgentCore Gateway MCP targets (Rancher MCP, Prometheus, CloudWatch Logs, GitHub); optional A2A serving from AgentCore Runtime.

### Frameworks & Libraries
- Bash with `grep -E`, `awk`, `tr`, `date`, `mkdir` — system — hook and test script
- Python 3 — unpinned (`python3` on `ubuntu-latest`) — CI check, standard library only
- GitHub Actions `actions/checkout` — `v5` (tag, not SHA) — CI checkout
- OpenTelemetry Collector contrib image — `otel/opentelemetry-collector-contrib:latest` in the runbook (runbook says to pin it once it works) — spike C
- `amazon/aws-cli` image — `latest` — spike B pod
- Rancher — `rancher/rancher:v2.15.0` (runbook user data) — spike A
- MCP servers in `.mcp.json` (AI-DLC entries, pinned by the project): `mcp-proxy-for-aws@1.8.0`, `awslabs.aws-pricing-mcp-server@1.1.1`, `awslabs.aws-iac-mcp-server@1.0.26`, `awslabs.aws-serverless-mcp-server@0.2.1`; `context7` is an HTTP endpoint with no version
- Planned stack (plan only, nothing installed): Strands Agents, Amazon Bedrock AgentCore (Runtime, Gateway, Policy, Identity, Memory, Observability, Evaluations), Claude on Bedrock (Haiku 4.5, Sonnet 4.6, Opus 4.6), Terraform, Rancher + Fleet on K3s, OpenTelemetry Demo, Managed Prometheus, CloudWatch, Grafana, Route 53, AWS FIS, Azure Chaos Studio, React/Vite

### Test Coverage
- **Test Directories**: none as such; one test script, `tools/claude-hooks/test-guard.sh` (26 assertions: 11 allowed, 14 blocked, 1 audit-log check), run in CI.
- **Test Frameworks**: hand-written Bash assertion function `check()`; no `pytest`.
- **Coverage Config**: absent. `tools/ci/check_pr_body.py` has no tests.

### Code Quality Indicators
- **Linting**: none configured. No Ruff, Black, ShellCheck, `terraform fmt`, yamllint or markdownlint config or CI step.
- **CI/CD**: `.github/workflows/methodology-checks.yml` only (guard tests plus PR-description check). No deployment pipeline, no dependency review, no secret scanning step in CI, no `CODEOWNERS`.
- **Documentation**: strong for the stage of the project. `README.md`, `docs/plan.md` (451 lines, with sources), a step-by-step Phase 0 runbook, ADR template plus ADR-0001 and ADR-0004 (both `Proposed`), an evidence README, and header comments explaining each script's contract.

### Technical Debt Signals
- **Hook covers the Bash tool only**: `settings.hooks.json` and the wired entry in `.claude/settings.json` use matcher `Bash`. MCP tool calls and the Edit/Write tools are not inspected by the project's guard (see Handoff Summary).
- **Guard rules can be bypassed by argument order** (by reading `guard-bash.sh` lines 19-27; not executed): each rule requires the verb right after the program name, so global flags before the verb are not matched, for example `kubectl -n demo delete pod x`, `terraform -chdir=infra/aws apply`, `helm -n demo uninstall x`.
- **Dry-run exemption is command-wide** (lines 29-37): the first matching rule decides; if it is a `kubectl` or `helm` match and the string `--dry-run` appears anywhere in the command, the whole command is allowed, including a chained second command such as `... --dry-run=client ... && terraform apply`.
- **Rules not covered**: `git push origin +main` (force refspec), `gh` writes (`gh pr merge`, `gh api -X DELETE`, `gh repo delete`), `aws s3 rm`, `aws` mutating verbs other than `delete-*`, `terminate-instances`, `rb` (for example `put-*`, `update-*`, `create-*`), `rm -rf /*`, and obfuscated forms (`eval`, `bash -c "$(...)"`). A denylist cannot be complete; it is one layer, not a read-only credential.
- **Gates are self-referential**: the CI job runs the guard tests and the PR check script from the PR's own tree, so a PR that edits `test-guard.sh`, `check_pr_body.py` or the workflow is checked by its own edited version. No `CODEOWNERS` or path protection exists.
- **Default credentials are admin**: `docs/runbooks/phase-0.md` step 1.2 sets up an `AdministratorAccess` SSO profile and `export AWS_PROFILE=sre-lab` in the shell that later starts Claude Code; the AWS MCP servers use the standard credential chain. This contradicts `CLAUDE.md` "Use read-only credentials by default".
- **Unpinned images and actions**: `amazon/aws-cli:latest`, `otel/opentelemetry-collector-contrib:latest`, `actions/checkout@v5` by tag rather than digest/SHA (plan's ASI04 control asks for pins by version and digest).
- **Missing evidence still to produce**: `docs/evidence/rulesets/` and `docs/evidence/telemetry/` hold only `.gitkeep`; ADR-0002 and ADR-0003 (spike outcomes) do not exist yet.
- **Duplication**: `tools/github-setup/` duplicates the installed `.github/` files; the PR template is identical, the workflow already differs (`checkout@v4` vs `@v5`).
- **Python convention gap**: `check_pr_body.py` has no type hints and no tests, although `CLAUDE.md` asks for type hints and `pytest`.
- No TODO/FIXME/HACK comments, no suppressed linter warnings, no hard-coded secrets, account IDs or kubeconfigs found; the spike files use placeholders and the runbook substitutes them at run time into `/tmp`.

## Handoff Summary
- **Intent-relevant finding**: the project's guardrail today is a single Bash denylist hook. `tools/claude-hooks/settings.hooks.json` line 5 (`"matcher": "Bash"`) and the same matcher in `.claude/settings.json` mean MCP tool calls (for example the `aws-mcp` server's script runner, which can call any AWS API with the shell's credentials) and Edit/Write tool calls are not checked by it. `.claude/settings.json` pre-allows `Edit(/**)`, and only AI-DLC (not the project's hook) protects `.claude/settings.json` itself (ADR-0004). So nothing in the project's own controls stops the coding agent from editing `.mcp.json`, `.github/`, `tools/claude-hooks/` or `tools/ci/`. These are exactly the paths the intent asks to protect.
- **Risks / follow-up**:
  - Read-only credentials are not the default: the Phase 0 runbook exports an admin SSO profile into the shell Claude Code inherits (`docs/runbooks/phase-0.md` step 1.2).
  - The guard has bypasses (argument order, command-wide dry-run exemption, uncovered verbs); requirements should state the guarantee as an outcome to test (for example "no blocked operation executes"), not as a regex list.
  - CI gates run from the PR's own tree; protection needs a control outside the PR (`CODEOWNERS` plus a ruleset that requires code-owner review, or a required workflow from a protected ref).
  - The plan's runtime safety controls (Cedar at the Gateway, read-only Rancher role, GitHub App limited to contents and PRs, a ruleset that prevents agent merges) are entirely unbuilt; Phases 1 to 3 build them.
  - Preserve: the hook fails closed (`onFailure: block`, ADR-0004); the audit log records the rule name only, never the command; the PR check reads the body from an env variable, never shell interpolation.
