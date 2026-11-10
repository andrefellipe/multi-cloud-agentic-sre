# Code Structure

## Repository layout (project-owned files only)

AI-DLC's install (`.claude/`) and workspace (`aidlc/`) are excluded from this inventory; `.claude/settings.json` is referenced only where it wires the project's hook.

```
.
|-- CLAUDE.md                     project rules for the coding agent
|-- README.md                     status, phase table, repository map
|-- .gitignore                    Terraform state, secrets, Python/Node caches (+ AI-DLC block)
|-- .mcp.json                     MCP servers for the coding agent (AI-DLC entries, pinned)
|-- .github/
|   |-- pull_request_template.md  Summary, Requirements, AI involvement, Evidence, Risk
|   `-- workflows/
|       `-- methodology-checks.yml  job pr-evidence
|-- agents/README.md              placeholder (Phase 2)
|-- console/README.md             placeholder (Phase 7)
|-- evals/README.md               placeholder (Phase 4)
|-- infra/README.md               placeholder (Phase 1 AWS, Phase 5 Azure)
|-- platform/README.md            placeholder (Phase 1)
|-- docs/
|   |-- plan.md                   project plan (input to Inception)
|   |-- runbooks/phase-0.md       step-by-step Phase 0
|   |-- adr/                      0000 template, 0001, 0004 (0002, 0003 reserved for spikes)
|   |-- diagrams/                 architecture, incident-lifecycle, roadmap (PNG)
|   `-- evidence/                 README, hook-audit.jsonl, rulesets/ and telemetry/ (empty)
`-- tools/
    |-- claude-hooks/             guard-bash.sh, test-guard.sh, settings.hooks.json, README
    |-- ci/check_pr_body.py       PR description check
    |-- github-setup/             staging copies of .github files
    |-- otel/collector-local.yaml spike C collector
    `-- spikes/                   spike B pod manifest and IAM trust policy
```

## File classification

| File | Category | Language | Lines (approx.) |
| --- | --- | --- | --- |
| `tools/claude-hooks/guard-bash.sh` | Middleware (tool-call guard) | Bash | 43 |
| `tools/claude-hooks/test-guard.sh` | Test | Bash | 62 |
| `tools/claude-hooks/settings.hooks.json` | Configuration | JSON | 17 |
| `tools/ci/check_pr_body.py` | Utility / validator | Python | 40 |
| `.github/workflows/methodology-checks.yml` | Configuration (CI) | YAML | 20 |
| `.github/pull_request_template.md` | Static / template | Markdown | 20 |
| `tools/github-setup/*` | Static (duplicate staging copies) | YAML, Markdown | 48 |
| `tools/otel/collector-local.yaml` | Configuration | YAML | 18 |
| `tools/spikes/spike-b-pod.yaml` | Configuration (Kubernetes fixture) | YAML | 45 |
| `tools/spikes/spike-b-trust-policy.json` | Configuration (IAM fixture) | JSON | 18 |
| `.mcp.json` | Configuration | JSON | 38 |
| `.gitignore` | Configuration | gitignore | 61 |
| `CLAUDE.md`, `README.md`, `docs/**/*.md`, `*/README.md` | Documentation | Markdown | about 900 in total |
| `docs/evidence/hook-audit.jsonl` | Evidence (append-only log) | JSONL | 3 |
| `docs/diagrams/*.png` | Static / asset | PNG | n/a |

No Model/Entity, Controller, Service, Repository or Migration files exist.

## Code patterns

- **Hook contract (Claude Code PreToolUse)**: read JSON from stdin, decide, exit 0 (allow) or 2 (block with stderr). `set -u`; no `set -e`, so a failing `grep` does not abort. Written for macOS bash 3.2 and BSD grep.
- **Denylist built by string concatenation** of ERE alternatives (`rules="$rules"'|...'`) and one `grep -Eo` pass; first match wins.
- **Audit without payload**: the log line carries a timestamp, a fixed event and the first two words of the match, never arguments.
- **Fail closed** at the harness level: `"onFailure": "block"` in `settings.hooks.json`.
- **Env-var hand-off to avoid injection**: the workflow passes `github.event.pull_request.body` through `env: PR_BODY` instead of interpolating it into `run:`.
- **Placeholders, then substitution outside Git**: spike files carry `ACCOUNT_ID`, `OIDC_PROVIDER_ARN`, `ISSUER_HOST_AND_PATH`; the runbook pipes `sed` output to `kubectl` or to `/tmp`, so the tracked file never holds real identifiers.
- **Install by human with a reviewed diff**: `jq` merge of `settings.hooks.json` into `.claude/settings.json`, idempotent (drops any existing `tools/claude-hooks/` group first).

## Internal dependency graph

```
methodology-checks.yml -> tools/claude-hooks/test-guard.sh
test-guard.sh          -> tools/claude-hooks/guard-bash.sh
methodology-checks.yml -> tools/ci/check_pr_body.py
check_pr_body.py       -> (labels in) .github/pull_request_template.md   [implicit, by string]
.claude/settings.json  -> tools/claude-hooks/guard-bash.sh               [PreToolUse, matcher Bash]
guard-bash.sh          -> docs/evidence/hook-audit.jsonl                 [append]
docs/runbooks/phase-0.md -> tools/github-setup/*, tools/claude-hooks/*, tools/otel/*, tools/spikes/*
```

No circular references.

## Conventions observed

- Markdown with sentence-case headings and tables; ADRs follow `docs/adr/0000-template.md` (Context, Decision, Options considered, Consequences, AI involvement).
- Conventional Commits (`chore:`) with PR numbers; `Co-Authored-By` trailers per `CLAUDE.md`.
- Requirement IDs `REQ-NNN` (three digits) are what `check_pr_body.py` accepts.
- Python style: module-level script, no type hints, no `main()` guard.
