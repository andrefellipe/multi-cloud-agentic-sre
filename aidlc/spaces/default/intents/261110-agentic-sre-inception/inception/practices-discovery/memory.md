<!-- INVARIANT: examples are single-line HTML comments so a fresh template parses to total=0 (MEMORY_EMPTY). Do NOT un-comment or split across lines. t100 guards this. -->
> This file is kept up to date automatically while the stage runs. Add observations at the review step, not by editing here directly.

## Interpretations
<!-- example: 2026-05-29T10:14:32Z — chose REST over GraphQL; the consuming team only needs CRUD, revisit if subscriptions land -->

- 2026-11-10T10:21:27Z — read squash merges from the `(#N)` suffix and one-commit-per-PR history on `main`; GitHub merge settings were not inspected, so merge style stays draft
- 2026-11-10T10:21:27Z — treated CLAUDE.md rules as human-stated candidates for discovered-rules.md; added the no-direct-push rule from the phase-0 runbook ruleset
- 2026-11-10T13:28:04Z — integration: promoted interview answers Q1, Q4, Q6, Q8 and Q9 into discovered-rules.md as hard constraints alongside the CLAUDE.md rules (14 ALWAYS, 7 NEVER)
- 2026-11-10T13:28:04Z — integration: wrote Walking Skeleton as "always" for this project from Q10, overriding the scope's `skeleton: off` default

## Deviations
- 2026-11-10T10:21:27Z — drafted Deployment without the org default's staging/production split; the repo has one lab per cloud and the plan makes the human merge the only gate
- 2026-11-10T13:28:04Z — Q2 deviates from the lead draft: the human chose `<type>/REQ-NNN-<topic>` over the drafted `<type>/<topic>`; Way of Working now carries the REQ ID in branch names
<!-- example: 2026-05-29T10:14:32Z — skipped the optional caching layer the stage prose suggested; the dataset is small enough that it adds risk -->

## Tradeoffs
<!-- example: 2026-05-29T10:14:32Z — picked TDD over BDD this run; the team is unit-first and the domain is well-understood -->

## Open questions
- 2026-11-10T10:21:27Z — walking skeleton drafted as "yes" against the classic scope's `skeleton: off`; needs the human's explicit choice
- 2026-11-10T10:21:27Z — plan says a job applies Terraform, CLAUDE.md says the human applies; ask which holds for Phases 1-3
- 2026-11-10T13:28:04Z — resolved by Q4 (human applies locally) and Q10 (skeleton yes); still open: branch naming for work with no REQ ID, mypy vs pyright, Terraform apply path from Phase 4, GitHub merge settings not inspected
- 2026-11-10T13:31:06Z — branch naming for work with no REQ ID resolved by follow-up Q11 (A): `<type>/<topic>`; requirement work keeps `<type>/REQ-NNN-<topic>` (Q2); branch rule split out in discovered-rules.md (15 ALWAYS, 7 NEVER)
<!-- example: 2026-05-29T10:14:32Z — confirm the retention window with compliance before the next stage hardens the schema -->
