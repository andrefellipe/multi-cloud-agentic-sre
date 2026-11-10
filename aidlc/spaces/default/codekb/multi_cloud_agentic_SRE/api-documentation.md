# API Documentation

## Summary

The repository exposes **no network API** at commit 69ec4cd. The interfaces that exist are process-level contracts between the developer tooling, Claude Code and GitHub Actions. The APIs in `docs/plan.md` are listed at the end as planned, so later stages do not mistake them for existing ones.

## 1. Guard hook contract (`tools/claude-hooks/guard-bash.sh`)

| Aspect | Contract |
| --- | --- |
| Caller | Claude Code, PreToolUse event, matcher `Bash` only (`settings.hooks.json`, wired into `.claude/settings.json`) |
| Input | Hook JSON on stdin, for example `{"tool_name":"Bash","tool_input":{"command":"...","description":"..."}}`. Only the first `"command"` string is checked; if none is found, the whole input is checked. |
| Environment | `CLAUDE_PROJECT_DIR` (root for the audit log; falls back to `pwd`) |
| Exit 0 | Allow the tool call |
| Exit 2 | Block; stderr: `Blocked by project guardrail: '<rule>' must be run by a human, not by Claude. See CLAUDE.md, Safety rules.` |
| Other exit / failure to start / timeout | Blocked by the harness because `"onFailure": "block"` (ADR-0004) |
| Side effect | On block, append one line to `docs/evidence/hook-audit.jsonl` |

### Blocked rules (as written, lines 19-27)

| Rule family | Pattern (summary) | Exemption |
| --- | --- | --- |
| Terraform / OpenTofu | `terraform` or `tofu` followed directly by `apply` or `destroy` | none |
| kubectl writes | `kubectl` followed directly by `apply`, `create`, `delete`, `replace`, `patch`, `edit`, `scale`, `drain`, `cordon`, `label`, `annotate`, `rollout restart`, `rollout undo` | `--dry-run` anywhere in the command |
| helm writes | `helm` followed directly by `install`, `upgrade`, `uninstall`, `delete`, `rollback` | `--dry-run` anywhere in the command |
| Force push | `git push ... --force`, `--force-with-lease` or `-f` | none |
| Hard reset | `git reset --hard` | none |
| Recursive delete of root or home | `rm -<flags with r> /` or `~` as a whole argument | none |
| AWS deletes | `aws ... delete-*`, `terminate-instances`, `rb` | none |
| Azure deletes | `az ... delete` | none |

### Audit log record (`docs/evidence/hook-audit.jsonl`)

```json
{"ts":"2026-11-10T04:47:28Z","event":"blocked","rule":"terraform apply"}
```

Fields: `ts` (UTC, second precision), `event` (always `blocked`), `rule` (first two words of the match, quotes and backslashes stripped). Three records exist (two `terraform apply`, one `kubectl delete`), all from 2026-11-10 guard tests.

## 2. PR description check (`tools/ci/check_pr_body.py`)

| Aspect | Contract |
| --- | --- |
| Input | env `PR_BODY` (empty if unset) |
| Pre-processing | HTML comments `<!-- ... -->` removed, so template hints do not count as answers |
| Required | Text `## AI involvement`; lines with labels `AI wrote:` and `I changed or rejected:` (optionally list items), each with at least 3 characters of content; a `Requirements:` line containing `REQ-` followed by three digits, or exactly `n/a` or `none` |
| Exit 0 | Prints `PR description check passed.` |
| Exit 1 | Prints `PR description check failed:` and one bullet per error |

Note: `REQ-\d{3}` also matches `REQ-0123` (a substring); IDs with four or more digits pass silently.

## 3. CI workflow (`.github/workflows/methodology-checks.yml`)

| Aspect | Value |
| --- | --- |
| Trigger | `pull_request`: `opened`, `edited`, `synchronize`, `reopened`, `ready_for_review` |
| Token permissions | `contents: read` |
| Job | `pr-evidence` on `ubuntu-latest` |
| Steps | `actions/checkout@v5`; `bash tools/claude-hooks/test-guard.sh`; `python3 tools/ci/check_pr_body.py` with `PR_BODY` |
| Required status | The runbook (step 3) says to add `pr-evidence` as a required check on the `main` ruleset after the first PR. Whether that is done is not visible in the repository (`docs/evidence/rulesets/` is empty). |

## 4. PR template fields (`.github/pull_request_template.md`)

`## Summary`, `Requirements:`, `## AI involvement` (`AI wrote:`, `I changed or rejected:`), `## Evidence` (checks run; plan/diff output reviewed; eval scorecard compared), `## Risk and rollback`.

## 5. Planned interfaces (not implemented; source `docs/plan.md`)

| Interface | Type | Producer -> consumer | Phase |
| --- | --- | --- | --- |
| Alert intake | Alertmanager -> SNS -> Lambda | Managed Prometheus -> incident table and agent session | 1-2 |
| Incident table | DynamoDB with conditional writes | Lambda, agents | 1-2 |
| Agent tools | MCP via AgentCore Gateway: Rancher MCP (read-only), Prometheus queries, CloudWatch Logs, GitHub (branch and PR in allowed paths) | Agents -> Gateway -> targets | 2-3 |
| Tool policy | Cedar rules in AgentCore Policy; kill switch = deny all | Gateway | 2-3 |
| Merge webhook | GitHub webhook -> Lambda -> Verifier session | GitHub -> AgentCore | 3 |
| Notifications | Slack | Agents -> human | 2 |
| A2A | AgentCore Runtime serving the graph, SigV4 or OAuth | External agent or benchmark -> graph | later |
