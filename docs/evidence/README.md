# Evidence

Records that show the method was followed. Commit them, and never edit them by hand after the fact.

| Path | Written by | Shows |
| --- | --- | --- |
| `hook-audit.jsonl` | `tools/claude-hooks/guard-bash.sh` | Commands Claude tried that only a human may run (rule name only) |
| `rulesets/` | You, exported from GitHub | Branch rules and their history |
| `telemetry/` | You (Phase 0, spike C onward) | Claude Code telemetry samples, metrics only |
| `spike-a/` | Claude, from the runs of Phase 0's spike A, which you ran | `rancher-ai-mcp` called directly (A4) and through AgentCore Gateway (A5) |
| `spike-b/` | Claude, from the run of Phase 0's spike B, which you ran | A pod in AKS assuming an IAM role with its own service-account token, with no AWS keys |
| `scorecards/` | Evaluation harness (Phase 4 onward) | Agent scores per release |
| `compliance/` | CI script (Phase 4 onward) | Share of PRs that met every rule |

AI-DLC keeps its own audit trail in `aidlc/spaces/default/intents/<intent-id>/audit/`.
