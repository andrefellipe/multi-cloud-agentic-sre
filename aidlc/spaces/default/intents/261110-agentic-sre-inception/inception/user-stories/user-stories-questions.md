# User Stories Plan and Questions

## Plan

- **Input.** The 75 approved requirements in `inception/requirements-analysis/requirements.md`, the reverse-engineering artifacts, and the affirmed team practices.
- **Format.** "As a [persona], I want [goal], so that [benefit]." Stories meet the INVEST criteria and have stable `USx.y` IDs. Acceptance criteria are Given/When/Then with `ACx.y.z` IDs, and each one names the REQ IDs it demonstrates.
- **Priority.** MoSCoW for each story. The MVP line is set later, in Delivery Planning.
- **Coverage.** Every REQ maps to at least one story. Pure quality bars (coverage floor, pinning, linters) may be marked `N/A`, with the reason, where no person-facing behaviour exists.

The questions below settle what the requirements did not. Each names the trade whose call it is.

## Q1. [Product owner] Who are the personas for Phases 1 to 3?

There is no end-user UI yet. The plan names you (the operator who merges) and suggests a peer who reviews at each phase gate.

A. Two personas: the lab operator (you: merge, kill switch, guardrail changes, gate sign-off) and the phase-gate peer reviewer; agent behaviour is told from the operator's side (recommended: matches who actually acts in Phases 1 to 3)
B. One persona: the lab operator only
C. Three personas: the lab operator, a future on-call responder who receives the Slack summaries, and the peer reviewer
X. Other (please specify)

[Answer]: C

## Q2. [Product owner] How should the stories be grouped?

A. By phase, then by step of the incident lifecycle, with the coding-agent guardrails as their own group first (recommended: lines up with the phase gates and the walking skeleton, and feeds Units Generation directly)
B. By the requirement areas A to J in `requirements.md`
C. By persona
X. Other (please specify)

[Answer]: A

## Q3. [Product owner] How should MoSCoW priority be assigned?

A. Must = needed to pass the phase gate it belongs to or a safety requirement; Should = everything else in Phases 1 to 3; Could = nice extras; Won't = the out-of-scope list (recommended: gives Delivery Planning a clear MVP line per phase)
B. Every story in Phases 1 to 3 is Must
C. Must only for the walking-skeleton slice and the safety stories; everything else Should
X. Other (please specify)

[Answer]: B
