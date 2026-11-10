<!-- INVARIANT: examples are single-line HTML comments so a fresh template parses to total=0 (MEMORY_EMPTY). Do NOT un-comment or split across lines. t100 guards this. -->
> This file is kept up to date automatically while the stage runs. Add observations at the review step, not by editing here directly.

## Interpretations
<!-- example: 2026-05-29T10:14:32Z — chose REST over GraphQL; the consuming team only needs CRUD, revisit if subscriptions land -->
- 2026-11-10T19:34:54Z — Q5 "I have none yet" recorded as no external dependency in place; all four listed (plus D1, D5-D8 discovered while mapping) go into external-dependency-map.md as open items.
- 2026-11-10T19:34:54Z — Added D6 (separate GitHub identity for the coding agent) as the practical route to close the contract C11 label-authenticity question.

## Deviations
<!-- example: 2026-05-29T10:14:32Z — skipped the optional caching layer the stage prose suggested; the dataset is small enough that it adds risk -->

## Tradeoffs
<!-- example: 2026-05-29T10:14:32Z — picked TDD over BDD this run; the team is unit-first and the domain is well-understood -->

## Open questions
<!-- example: 2026-05-29T10:14:32Z — confirm the retention window with compliance before the next stage hardens the schema -->
- 2026-11-10T19:34:54Z — No runnable project check exists yet (no pyproject, no tests beyond test-guard.sh); the Construction verification command is proposed as deferred until the first unit lands one.
