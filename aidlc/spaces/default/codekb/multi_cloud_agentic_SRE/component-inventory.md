# Component Inventory

Components that exist in the repository at commit 69ec4cd. Planned components are listed in a table at the end and are not part of the analyzed scope.

### Guardrail Hook

- **Location**: `tools/claude-hooks/guard-bash.sh`, `tools/claude-hooks/settings.hooks.json`, `tools/claude-hooks/README.md`
- **Type**: Claude Code PreToolUse hook (Bash)
- **Responsibility**: block shell commands only a human may run (Terraform/OpenTofu apply and destroy, kubectl and helm writes, force pushes, hard resets, recursive delete of `/` or `~`, AWS and Azure deletes); log each block by rule name.
- **Depends on**: Claude Code hook runtime; `grep -E`, `awk`, `tr`, `date`; `CLAUDE_PROJECT_DIR`
- **Used by**: `.claude/settings.json` (matcher `Bash`, `onFailure: block`); Guard Hook Tests
- **Writes**: `docs/evidence/hook-audit.jsonl`
- **Status**: installed and active; ADR-0004 `Proposed`
- **Gaps**: Bash tool only (no MCP, Edit or Write coverage); bypassable by flags before the verb and by the command-wide `--dry-run` exemption; uncovered verbs (see code-quality-assessment.md)

### Guard Hook Tests

- **Location**: `tools/claude-hooks/test-guard.sh`
- **Type**: Test script (Bash)
- **Responsibility**: 26 assertions: 11 commands allowed, 14 blocked, 1 check that the audit log holds the rule and not the arguments. Uses a temp dir as `CLAUDE_PROJECT_DIR`.
- **Depends on**: Guardrail Hook
- **Used by**: PR Evidence CI Workflow; humans (runbook steps 3 and 4)
- **Gaps**: no negative tests for bypass forms; no test that MCP or Edit calls are guarded (they are not)

### PR Evidence CI Workflow

- **Location**: `.github/workflows/methodology-checks.yml`
- **Type**: GitHub Actions workflow, job `pr-evidence`
- **Responsibility**: run Guard Hook Tests and the PR Description Check on every PR event
- **Depends on**: `actions/checkout@v5`, `ubuntu-latest` Bash and `python3`
- **Used by**: GitHub ruleset on `main` (runbook asks to make `pr-evidence` required)
- **Gaps**: runs scripts from the PR's own tree; no `CODEOWNERS`; no lint, dependency review or secret scan steps

### PR Description Check

- **Location**: `tools/ci/check_pr_body.py`
- **Type**: CI validator script (Python 3, standard library)
- **Responsibility**: fail the PR unless the body has `## AI involvement`, non-empty `AI wrote:` and `I changed or rejected:`, and `Requirements:` with `REQ-NNN` or `n/a`/`none`
- **Depends on**: env `PR_BODY`
- **Used by**: PR Evidence CI Workflow
- **Gaps**: no tests; no type hints

### PR Template

- **Location**: `.github/pull_request_template.md`
- **Type**: GitHub PR template
- **Responsibility**: give every PR the Summary, Requirements, AI involvement, Evidence and Risk and rollback sections the check expects
- **Used by**: GitHub; PR Description Check (by label text)

### GitHub Setup Staging Copies

- **Location**: `tools/github-setup/`
- **Type**: bootstrap copies (README, PR template, workflow)
- **Responsibility**: source for the first copy into `.github/` (runbook step 3)
- **Status**: superseded; workflow copy already drifted (`checkout@v4` vs installed `@v5`); README says it can be deleted

### Local Telemetry Collector Config

- **Location**: `tools/otel/collector-local.yaml`
- **Type**: OpenTelemetry Collector config
- **Responsibility**: spike C, receive Claude Code OTLP metrics on 4317/4318 and print them with the `debug` exporter
- **Gaps**: run with an unpinned `:latest` image; binds `0.0.0.0`

### Spike B Fixtures

- **Location**: `tools/spikes/spike-b-pod.yaml`, `tools/spikes/spike-b-trust-policy.json`
- **Type**: Kubernetes manifest and IAM trust policy with placeholders
- **Responsibility**: test that an AKS pod can assume an IAM role through workload identity federation (projected service-account token, audience `sts.amazonaws.com`, subject `system:serviceaccount:spike:otel`)
- **Status**: spike not yet recorded (ADR-0003 absent)
- **Gaps**: `amazon/aws-cli:latest` unpinned

### MCP Server Declarations

- **Location**: `.mcp.json`
- **Type**: Claude Code MCP configuration
- **Responsibility**: declares the MCP servers the coding agent can call: `context7` (HTTP), `aws-mcp` (`mcp-proxy-for-aws@1.8.0`), `aws-pricing`, `aws-iac`, `aws-serverless` (versions pinned by the project in commit 69ec4cd). All five are AI-DLC contributions; the project has added no server of its own (no Rancher or GitHub MCP yet).
- **Relevance**: these servers use the shell's AWS credential chain; their tool calls are not seen by the Guardrail Hook.

### Project Rules

- **Location**: `CLAUDE.md`
- **Type**: coding-agent instructions
- **Responsibility**: project description, AI-DLC method, EARS and requirement IDs, ADR policy, safety rules (no applies or cluster writes, no secrets, Git-only change paths, read-only credentials by default), engineering conventions (Python 3.12+ with uv, type hints, pytest; Terraform layout; Fleet bundles with kustomize overlays), commit and PR rules

### Architecture Decision Records

- **Location**: `docs/adr/`
- **Type**: documentation
- **Contents**: `0000-template.md`; `0001-adopt-ai-dlc-and-project-plan.md` (Proposed); `0004-guardrail-hook-fails-closed.md` (Proposed). 0002 (Rancher MCP spike) and 0003 (AKS-to-AWS identity spike) are referenced by the runbook but not written.

### Project Plan and Runbooks

- **Location**: `docs/plan.md`, `docs/runbooks/phase-0.md`, `docs/diagrams/`
- **Type**: documentation
- **Responsibility**: the plan is the Inception input (architecture, agent design, safety controls mapped to OWASP agentic risks, evaluation strategy, roadmap, cost, risks); the runbook gives Phase 0 steps for accounts, toolchain, repository, AI-DLC and hook install, Inception, and spikes A, B and C

### Evidence Store

- **Location**: `docs/evidence/`
- **Type**: evidence folder
- **Contents**: `README.md`; `hook-audit.jsonl` (3 block records); `rulesets/` and `telemetry/` empty (`.gitkeep`); `scorecards/` and `compliance/` named in README but not created

### Placeholder Directories

- **Location**: `agents/`, `console/`, `evals/`, `infra/`, `platform/`
- **Type**: one README each, no code
- **Arrive in**: `infra/` Phase 1 (AWS) and 5 (Azure); `platform/` Phase 1; `agents/` Phase 2; `evals/` Phase 4; `console/` Phase 7

## Planned components (not built; from `docs/plan.md`)

| Component | Layer | Phase |
| --- | --- | --- |
| Terraform root modules `infra/aws`, `infra/azure` | IaC | 1, 5 |
| Rancher on K3s (EC2) + Fleet | Multi-cluster management | 1 |
| OpenTelemetry Demo, Collector, flags as Fleet bundles | Platform | 1 |
| Alert rule -> SNS -> Lambda -> incident table | Alerting | 1 |
| Strands graph: Triage, Investigator, Remediator, Reviewer, Verifier, Scribe | Agents | 2, 3, 6 |
| AgentCore Gateway targets and Cedar policies, kill switch | Governance | 2, 3 |
| GitHub App via AgentCore Identity | Identity | 3 |
| Secret scanner and redaction on agent output | Safety | 3 |
| Merge webhook -> Lambda -> Verifier | Remediation loop | 3 |
| Replay harness, evaluators, scorecards | Evaluation | 4 |
| Route 53 weighted records, Chaos Studio | Multi-cloud | 5 |
| AgentCore Memory + Knowledge Base on S3 Vectors | Memory | 6 |
| React/Vite console | UI | 7 |
