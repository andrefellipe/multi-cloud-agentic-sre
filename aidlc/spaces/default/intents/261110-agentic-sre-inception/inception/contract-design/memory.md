<!-- INVARIANT: examples are single-line HTML comments so a fresh template parses to total=0 (MEMORY_EMPTY). Do NOT un-comment or split across lines. t100 guards this. -->
> This file is kept up to date automatically while the stage runs. Add observations at the review step, not by editing here directly.

## Interpretations
<!-- example: 2026-05-29T10:14:32Z — chose REST over GraphQL; the consuming team only needs CRUD, revisit if subscriptions land -->
- 2026-11-10T15:15:42Z — Treated the inbound alert feed and GitHub webhooks as external boundaries (no public API exists in Phases 1-3), and the PR description and CI checks as contracts consumed by the human and GitHub.
- 2026-11-10T15:15:42Z — Used the contracts to close earlier accepted review findings where a contract could: tool_calls in the agent result envelope (domain-design R-01), main's copy of the protected list (domain-design R-02), single allowed-paths file (domain-design R-06), write-enable flag (units R-02).

## Deviations
<!-- example: 2026-05-29T10:14:32Z — skipped the optional caching layer the stage prose suggested; the dataset is small enough that it adds risk -->

## Tradeoffs
<!-- example: 2026-05-29T10:14:32Z — picked TDD over BDD this run; the team is unit-first and the domain is well-understood -->

## Open questions
<!-- example: 2026-05-29T10:14:32Z — confirm the retention window with compliance before the next stage hardens the schema -->
- 2026-11-10T15:15:42Z — Owner-applied label proof (C11) remains unsolved; GitHub cannot distinguish the owner from an agent using the owner's token. Needs a separate credential or a GitHub App for the agent in functional/NFR design.
