#!/usr/bin/env bash
# Claude Code PreToolUse hook for the Bash tool.
# Blocks commands that only a human may run in this project (applies, deletes, force-pushes).
# Contract: exit 2 blocks the tool call and shows stderr to Claude; exit 0 lets it run.
# Each block is appended to docs/evidence/hook-audit.jsonl with the rule name only,
# never the full command, so no arguments or secrets reach the log.
# Written for macOS bash 3.2 and BSD grep as well as Linux.
set -u

input="$(cat)"
root="${CLAUDE_PROJECT_DIR:-$(pwd)}"
log="$root/docs/evidence/hook-audit.jsonl"

# Check only the command field of the hook input, so a description that merely
# mentions "terraform apply" doesn't block a plan. Fall back to the whole input.
command_field="$(printf '%s' "$input" | grep -Eo '"command"[[:space:]]*:[[:space:]]*"([^"\\]|\\.)*"' | head -n 1)"
[ -n "$command_field" ] || command_field="$input"

rules='terraform[[:space:]]+(apply|destroy)'
rules="$rules"'|tofu[[:space:]]+(apply|destroy)'
rules="$rules"'|kubectl[[:space:]]+(apply|create|delete|replace|patch|edit|scale|drain|cordon|label|annotate|rollout[[:space:]]+(restart|undo))'
rules="$rules"'|helm[[:space:]]+(install|upgrade|uninstall|delete|rollback)'
rules="$rules"'|git[[:space:]]+push([[:space:]][^|;&]*)?[[:space:]](--force|--force-with-lease|-f)([^[:alnum:]-]|$)'
rules="$rules"'|git[[:space:]]+reset[[:space:]]+--hard'
rules="$rules"'|rm[[:space:]]+-[[:alpha:]]*r[[:alpha:]]*[[:space:]]+(/|~)([[:space:]]|\\?"|$)'
rules="$rules"'|aws[[:space:]][^|;&]*[[:space:]](delete-[[:alnum:]-]+|terminate-instances|rb)([[:space:]]|\\?"|$)'
rules="$rules"'|az[[:space:]][^|;&]*[[:space:]]delete([[:space:]]|\\?"|$)'

match="$(printf '%s' "$command_field" | grep -Eo "$rules" | head -n 1)"
[ -n "$match" ] || exit 0

# Dry runs change nothing, so let kubectl and helm dry runs through.
case "$match" in
  kubectl*|helm*)
    if printf '%s' "$command_field" | grep -Eq -- '--dry-run'; then exit 0; fi
    ;;
esac

rule="$(printf '%s' "$match" | awk '{print $1, $2}' | tr -d '"\\')"
mkdir -p "$(dirname "$log")"
printf '{"ts":"%s","event":"blocked","rule":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$rule" >> "$log"
echo "Blocked by project guardrail: '$rule' must be run by a human, not by Claude. See CLAUDE.md, Safety rules." >&2
exit 2
