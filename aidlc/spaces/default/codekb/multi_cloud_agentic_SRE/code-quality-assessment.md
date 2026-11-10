# Code Quality Assessment

Assessment by reading only; no test, build or program was run.

## Overall

A small, deliberately written scaffold. The few scripts are clear, commented and defensive about secrets. The gaps are about **coverage of the safety controls** rather than code quality, and they bear directly on the intent's safety requirements.

## Quick ratings (code-analysis-guide scale)

| Criterion | Rating | Evidence |
| --- | --- | --- |
| Naming clarity | good | `guard-bash.sh`, `check_pr_body.py`, `field()`, `command_field`, `rules` |
| Function size | good | All scripts under 65 lines |
| Error handling | fair | Hook fails closed via the harness; `set -u` without `set -e` is intentional. `check_pr_body.py` handles a missing body. The hook's `mkdir -p` and append are unchecked; a write failure still exits 2 (block). |
| Test presence | fair | Hook has 26 assertions in CI; `check_pr_body.py` has none |
| Duplication | fair | `tools/github-setup/` duplicates `.github/` and has already drifted |
| Dead code | good | None found |

## Tests and coverage

- `tools/claude-hooks/test-guard.sh`: 11 allow, 14 block, 1 audit-content check (26 total, matching the runbook's "26 passed"). Run in CI on every PR.
- No `pytest`, no coverage tool, no coverage floor. The classic scope's 80% line-coverage floor and the `CLAUDE.md` pytest convention will need a test setup before Phase 2 Python lands.

## Linting and formatting

None configured: no Ruff/Black, ShellCheck, yamllint, markdownlint, `terraform fmt`/`validate` step. `org.md` says linting runs in CI before merge and blocks the PR; that is not yet true here.

## CI/CD

- One workflow, `methodology-checks` (job `pr-evidence`), `contents: read`, body passed through env (injection-safe).
- No deployment pipeline (none needed yet), no dependency review, no secret-scanning step (the runbook relies on GitHub's public-repo secret scanning with push protection), no build provenance.
- No `CODEOWNERS`; the ruleset is configured by hand and not yet exported to `docs/evidence/rulesets/`.

## Documentation

Good: README with phase table, a detailed plan with sources, a step-by-step runbook marking every human-only step "(you)", ADR template with an "AI involvement" section, script header comments explaining contracts.

## Security and safety findings (intent-relevant)

| # | Finding | Evidence | Severity for the intent |
| --- | --- | --- | --- |
| S1 | The project's guard checks the **Bash tool only**; MCP tool calls are not inspected | `settings.hooks.json` line 5 `"matcher": "Bash"`; same in `.claude/settings.json` | High: intent requires guardrails to cover MCP calls |
| S2 | **Edit/Write to guardrail and CI files is not blocked** by the project: `Edit(/**)` is pre-allowed; only AI-DLC protects `.claude/settings.json` | `.claude/settings.json` `permissions.allow`; ADR-0004 | High: intent requires the agent not to change `.mcp.json`, `.claude/settings.json`, `.github/`, `tools/claude-hooks/`, `tools/ci/` |
| S3 | **Admin credentials are the default** in the shell that starts Claude Code | runbook step 1.2 (`AdministratorAccess`, `export AWS_PROFILE=sre-lab`) | High: contradicts `CLAUDE.md` read-only default and the intent |
| S4 | **Verb must follow the program name directly**, so global flags bypass rules (`kubectl -n x delete`, `terraform -chdir=... apply`, `helm -n x uninstall`) | `guard-bash.sh` lines 19-22 | Medium |
| S5 | **`--dry-run` anywhere allows the whole command** when the first match is kubectl or helm, including a chained blocked command | lines 29-37 | Medium |
| S6 | **Uncovered destructive verbs**: `git push origin +branch`, `gh pr merge` / `gh api -X DELETE` / `gh repo delete`, `aws s3 rm`, AWS `put-*`/`update-*`/`create-*`, `rm -rf /*`, obfuscated commands | lines 19-27 | Medium (inherent denylist limit) |
| S7 | **CI gates are judged by the PR's own copy** of the scripts and workflow | `methodology-checks.yml` checkout of the PR tree | Medium: a PR can weaken its own check |
| S8 | **Settings rewrite drops the guard silently** | ADR-0004 Consequences | Medium: needs a detection check |
| S9 | Unpinned images and action tag | `amazon/aws-cli:latest`, collector `:latest`, `actions/checkout@v5` | Low (spikes) / Medium for CI |
| S10 | `docs/evidence/hook-audit.jsonl` is append-only only by convention; the coding agent can edit it | `Edit(/**)` | Low-Medium: evidence integrity |

Positive controls to preserve: fail-closed hook (`onFailure: block`); audit log without command arguments; PR body via env variable; `.gitignore` excludes `.env*`, `*.pem`, `kubeconfig*`, Terraform state and plans; spike fixtures use placeholders, substituted outside Git.

No hard-coded secrets, tokens, kubeconfigs or account IDs were found in project files.

## Technical debt summary

1. Guard coverage (S1, S2, S4-S6) and credential default (S3): address in Inception as safety requirements.
2. Gate self-protection (S7, S8): `CODEOWNERS` + ruleset code-owner review, and a CI check that `.claude/settings.json` still wires the guard.
3. Quality tooling: Ruff, Black, ShellCheck, pytest with coverage before Phase 2.
4. Evidence backlog: ruleset export, telemetry excerpt, ADR-0002, ADR-0003; ADR-0001 and ADR-0004 still `Proposed`.
5. Remove or sync `tools/github-setup/`.
6. Add tests and type hints to `check_pr_body.py`; tighten `REQ-\d{3}` to a word boundary.
