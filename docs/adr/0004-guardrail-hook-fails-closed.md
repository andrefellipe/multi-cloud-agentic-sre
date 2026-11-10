# ADR-0004: The guardrail hook fails closed, and a human installs it

- Status: Proposed
- Date: 2026-11-10
- Requirements: n/a (precedes Inception)

## Context

ADR-0001 enforces the project's safety rules with a Claude Code PreToolUse hook, `tools/claude-hooks/guard-bash.sh`. Installing it on 2026-11-10, with Claude Code 2.1.322, surfaced two facts:

- When a command hook fails (the script can't start, times out, or exits with a code other than 0 or 2), Claude Code's default, `"onFailure": "continue"`, lets the tool call go ahead. A missing or broken guard would silently allow everything it exists to block.
- AI-DLC's own `guard-tool-call` hook stops Claude Code from editing `.claude/settings.json`, so the planned install step, asking Claude to merge `settings.hooks.json` into that file, can't work.

## Decision

1. Set `"onFailure": "block"` on the guard in `tools/claude-hooks/settings.hooks.json`, so a guard that fails blocks the Bash call instead of allowing it.
2. A human installs the hook from a terminal outside Claude Code, with the `jq` merge in `tools/claude-hooks/README.md` (also step 4 of `docs/runbooks/phase-0.md`), after reviewing its diff.

## Options considered

- Keep the default, `continue`: a guard that can't run fails open, which defeats its purpose.
- Ask Claude to edit `.claude/settings.json`: not possible, because AI-DLC blocks the edit and a tool call can't set a bypass.
- Put the hook in `.claude/settings.local.json`, which Claude may be able to edit: that file is gitignored, so the guard would exist on one machine only and never show up in a PR.

## Consequences

- If `guard-bash.sh` goes missing, loses its execute bit, or crashes, every Bash call Claude makes is blocked, including the `aidlc engine` commands it runs, until a human fixes the script and `test-guard.sh` passes.
- Running `aidlc config --harness claude` again rewrites `.claude/settings.json` and drops the guard; nothing blocks until a human re-runs the merge. Watch PR diffs for the guard group disappearing from `.claude/settings.json`.

## AI involvement

Claude, working in Claude Code, found both facts: the first by reading the hook schema in the installed Claude Code build, the second when AI-DLC blocked its edit. It proposed `onFailure: block` and the terminal install steps, and drafted this ADR. The human approved both changes on 2026-11-10 and rejected nothing.
