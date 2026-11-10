<!-- INVARIANT: examples are single-line HTML comments so a fresh template parses to total=0 (MEMORY_EMPTY). Do NOT un-comment or split across lines. t100 guards this. -->
> This file is kept up to date automatically while the stage runs. Add observations at the review step, not by editing here directly.

## Interpretations
<!-- example: 2026-05-29T10:14:32Z — chose REST over GraphQL; the consuming team only needs CRUD, revisit if subscriptions land -->
- 2026-11-10T06:19:48Z — Documented two architectures side by side: "as built" (hook + CI check scaffold) and "as planned" (from docs/plan.md), labelled throughout so later stages do not treat planned components as existing.
- 2026-11-10T06:19:48Z — Treated all five .mcp.json servers as AI-DLC contributions (they match aidlc-manifest rootContributions); recorded only that the project pinned their versions and that their tool calls bypass the project's Bash-only guard.

## Deviations
<!-- example: 2026-05-29T10:14:32Z — skipped the optional caching layer the stage prose suggested; the dataset is small enough that it adds risk -->
- 2026-11-10T06:19:48Z — Read .claude/settings.json despite the .claude/ exclusion, limited to which project hook it wires (matcher Bash) and its permissions.allow list (Edit(/**)), as the brief allows for the guardrail facts; no AI-DLC internals documented.
- 2026-11-10T06:19:48Z — Guard bypasses (argument order, command-wide --dry-run exemption, uncovered verbs) are found by reading guard-bash.sh only; not executed, because the brief forbids running project tests or programs.

## Tradeoffs
<!-- example: 2026-05-29T10:14:32Z — picked TDD over BDD this run; the team is unit-first and the domain is well-understood -->
- 2026-11-10T06:19:48Z — Claimed kind: full with analyzed ./ because every project-owned file was read (PNG diagrams viewed); shallow paths left empty since the only unread folders are AI-DLC's own and .git, which belong to Left out, not shallow.

## Open questions
<!-- example: 2026-05-29T10:14:32Z — confirm the retention window with compliance before the next stage hardens the schema -->
- 2026-11-10T06:19:48Z — Is pr-evidence already a required status check on the main ruleset? Not visible in the repo (docs/evidence/rulesets/ is empty); requirements on CI gates depend on it.
- 2026-11-10T06:19:48Z — Will the coding agent get a separate read-only AWS profile? The Phase 0 runbook exports an AdministratorAccess profile into the shell Claude Code inherits, which conflicts with CLAUDE.md and the intent.
- 2026-11-10T06:19:48Z — Protection of guardrail and CI paths: a hook on Edit/Write/MCP tools, CODEOWNERS plus ruleset review, or both? Requirements Analysis should decide, with an ADR.
