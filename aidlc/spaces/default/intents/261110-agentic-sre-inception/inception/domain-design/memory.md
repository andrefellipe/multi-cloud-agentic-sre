<!-- INVARIANT: examples are single-line HTML comments so a fresh template parses to total=0 (MEMORY_EMPTY). Do NOT un-comment or split across lines. t100 guards this. -->
> This file is kept up to date automatically while the stage runs. Add observations at the review step, not by editing here directly.

## Interpretations
<!-- example: 2026-05-29T10:14:32Z — chose REST over GraphQL; the consuming team only needs CRUD, revisit if subscriptions land -->
- 2026-11-10T15:02:54Z — Treated Terraform (LabInfrastructure), Fleet bundles (PlatformBundles) and Cedar policies (ToolGovernance) as components because they are code we write; AWS/Rancher/AgentCore services stay external dependencies.
- 2026-11-10T15:02:54Z — Used the Q3 answer and Q5/Q6 answers to close accepted review findings (webhook auth, Phase 2 redaction, Phase 1 channel) at the design level rather than reopening requirements.

## Deviations
<!-- example: 2026-05-29T10:14:32Z — skipped the optional caching layer the stage prose suggested; the dataset is small enough that it adds risk -->

## Tradeoffs
<!-- example: 2026-05-29T10:14:32Z — picked TDD over BDD this run; the team is unit-first and the domain is well-understood -->
- 2026-11-10T15:02:54Z — ADR-007 (agents stateless, session persists results) was my call, not a question: it follows from the single-writer ledger and removes a write tool from every agent.
- 2026-11-10T15:02:54Z — Phase 1 notifier precedes the sanitizer; resolved by limiting Phase 1 to fixed templates (ADR-006) instead of pulling the sanitizer into Phase 1.

## Open questions
<!-- example: 2026-05-29T10:14:32Z — confirm the retention window with compliance before the next stage hardens the schema -->
- 2026-11-10T15:02:54Z — How CI proves the guardrail-change label came from the owner (requirements review R-01) remains open for NFR/functional design; ADR-004 notes it.
- 2026-11-10T15:02:54Z — The settings layers outside the PR (settings.local.json, user settings) are not covered by any component yet (requirements review R-02, accepted).
