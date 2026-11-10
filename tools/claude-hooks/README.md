# Claude Code guardrail hook

`guard-bash.sh` runs before every Bash command Claude Code wants to execute. It blocks commands that only a human may run in this project (`terraform apply` and `destroy`, kubectl and helm writes, force-pushes, hard resets, cloud deletes) and logs each block to `docs/evidence/hook-audit.jsonl`, recording the rule but never the full command.

## Install

AI-DLC's installer writes its own `.claude/settings.json`, so add this hook after running `aidlc config --harness claude`. In Claude Code, ask:

> Merge the hooks in tools/claude-hooks/settings.hooks.json into .claude/settings.json without removing any existing AI-DLC hooks or permissions. Show me the diff.

Restart Claude Code, then ask it to run `terraform apply`. The command must be blocked, and a line must appear in `docs/evidence/hook-audit.jsonl`.

## Test

```bash
bash tools/claude-hooks/test-guard.sh
```

CI runs the same tests on every pull request. To change a rule, change the script and its tests in the same PR.
