# Claude Code guardrail hook

`guard-bash.sh` runs before every Bash command Claude Code wants to execute. It blocks commands that only a human may run in this project (`terraform apply` and `destroy`, kubectl and helm writes, force-pushes, hard resets, cloud deletes) and logs each block to `docs/evidence/hook-audit.jsonl`, recording the rule but never the full command.

The hook fails closed: `settings.hooks.json` sets `"onFailure": "block"`, so Claude Code also blocks the command when the script can't start, times out, or exits with a code other than 0 or 2. If every Bash command is suddenly blocked, check that `guard-bash.sh` exists and is executable, then run its tests.

## Install

AI-DLC's installer writes its own `.claude/settings.json`, so add this hook after running `aidlc config --harness claude`, and again after any later run that rewrites the file. AI-DLC doesn't let Claude Code edit `.claude/settings.json`, so run these steps yourself, in a terminal outside Claude Code, from the repository root. They need `jq`.

1. Build the merged settings and review the change:

   ```bash
   merged="$(mktemp)"
   jq --slurpfile add tools/claude-hooks/settings.hooks.json '
     reduce ($add[0].hooks | to_entries[]) as $event (.;
       .hooks[$event.key] = [(.hooks[$event.key] // [])[]
                             | select(tostring | contains("tools/claude-hooks/") | not)]
                            + $event.value)
   ' .claude/settings.json > "$merged"
   diff -u .claude/settings.json "$merged"
   ```

   In the diff, only the `guard-bash.sh` group at the end of `PreToolUse` may change; every AI-DLC hook and permission stays. The filter first drops any group that already runs a script from `tools/claude-hooks/`, so running it again, for example after `settings.hooks.json` changes, doesn't add a duplicate.

2. Install it, in the same terminal:

   ```bash
   cp "$merged" .claude/settings.json && rm "$merged"
   ```

3. Restart Claude Code, then ask it to run `terraform apply`. The command must be blocked, and a line must appear in `docs/evidence/hook-audit.jsonl`.

## Test

```bash
bash tools/claude-hooks/test-guard.sh
```

CI runs the same tests on every pull request. To change a rule, change the script and its tests in the same PR.
