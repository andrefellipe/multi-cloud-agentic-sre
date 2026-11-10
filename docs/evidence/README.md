# Evidence

Records that show the method was followed. Commit them, and never edit them by hand after the fact.

| Path | Written by | Shows |
| --- | --- | --- |
| `hook-audit.jsonl` | `tools/claude-hooks/guard-bash.sh` | Commands Claude tried that only a human may run (rule name only) |
| `rulesets/` | You, exported from GitHub | Branch rules and their history |
| `telemetry/` | You (Phase 0, spike C onward) | Claude Code telemetry samples, metrics only |
| `scorecards/` | Evaluation harness (Phase 4 onward) | Agent scores per release |
| `compliance/` | CI script (Phase 4 onward) | Share of PRs that met every rule |

AI-DLC keeps its own audit trail in `aidlc/spaces/default/intents/<intent-id>/audit/`.
