# Team Allocation

A **mob** is the group that builds a Bolt together. A **Bolt** is one build pass over a piece of the work that ends in something that runs. This project is solo: the mob is you plus the AI. The classic plan has no team-formation stage, so every Bolt is built by the AI developer agent, and you are the reviewer, merger and the person who runs `terraform apply`. The Bolts and their order are in `bolt-plan.md`. The units of work they build are defined in `inception/units-generation/unit-of-work.md`.

| Bolt | Built by | Your role | Peer check (optional) |
|---|---|---|---|
| B1 skeleton | aidlc-developer-agent | Approve plans, merge 4 PRs, apply Terraform, sign off the skeleton checkpoint | none |
| B2 guardrails | aidlc-developer-agent | Approve plans, merge, label `guardrail-change`, install the settings change | none |
| B3 lab operations | aidlc-developer-agent | Approve plans, merge, apply Terraform, run the Phase 1 gate | Phase 1 gate: 30-minute review with the peer reviewer (persona P3) |
| B4 output safety | aidlc-developer-agent | Approve plans, merge | none |
| B5 read-only agents | aidlc-developer-agent | Approve plans, merge, label scenario root causes, run the Phase 2 gate | Phase 2 gate peer review |
| B6 remediation | aidlc-developer-agent | Approve plans, merge; `writes_enabled` stays off | none |
| B7 verification and control | aidlc-developer-agent | Approve plans, merge agent PRs, run the kill-switch test, then turn on `writes_enabled`, run the Phase 3 gate | Phase 3 gate peer review |

## Capacity

At about 15 to 20 hours a week (`docs/plan.md`), your review and merge time is the constraint, so Bolts run one at a time (Q4).

## Who does what

The AI builds, tests and opens PRs. Only you merge, apply, flip flags, or approve gates. These rules come from `CLAUDE.md` and the affirmed practices.
