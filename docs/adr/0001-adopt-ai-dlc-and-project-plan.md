# ADR-0001: Adopt AI-DLC with Claude Code, on the project plan baseline

- Status: Accepted
- Date: 2026-11-09
- Requirements: n/a (precedes Inception)

## Context

The project needs a repeatable AI-assisted method that leaves proof it was followed, and a baseline architecture to question during Inception. The plan in `docs/plan.md` came out of a planning session with Claude and was checked by an independent review agent.

## Decision

1. Follow AWS's AI-Driven Development Lifecycle through `awslabs/aidlc-workflows`, with Claude Code as the harness. AI-DLC's records in `aidlc/` are evidence and are committed.
2. Use `docs/plan.md` as the input to Inception. Requirements and units of work come out of AI-DLC, not straight from the plan.
3. Enforce development guardrails with a Claude Code PreToolUse hook (`tools/claude-hooks/guard-bash.sh`): Claude never applies infrastructure or cluster changes; a human does.
4. Require an "AI involvement" section and requirement IDs in every PR, checked in CI (`methodology-checks`).
5. Use the repository layout in `README.md`.

## Options considered

- Kiro as the AI-DLC harness: equally supported by aidlc-workflows. Claude Code was chosen for continuity with earlier work and for its GitHub Action.
- No formal method: rejected, because a provable process is part of the project's value.

## Consequences

- Every infrastructure change waits for a human apply. This slows experiments but keeps the audit trail honest.
- The guardrail hook can block a legitimate command. Its rules change only by PR, together with a test.

## AI involvement

Drafted by Claude in a claude.ai planning session on 2026-11-09, together with this scaffold. You accepted it unchanged on 2026-11-13.
