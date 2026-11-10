# Delivery Planning Questions

This stage puts the seven units of work in `inception/units-generation/unit-of-work.md` into a build order. Each unit is built as one or more Bolts. A Bolt is one build pass over a piece of the work that ends in something that runs and is merged through PRs.

Two things are already settled:
- **Your team practice requires a walking skeleton first.** A walking skeleton is the thinnest end-to-end slice, built first to prove the pieces connect. Here that is u1: an alert reaches the intake, opens an agent session, and the agent makes one read through Rancher.
- **The dependency order is fixed.** It is in `unit-of-work-dependency.md`. This stage only chooses a path through it.

Each question names the trade whose call it is.

## Q1. [Delivery lead] The guardrails unit (u2) comes after the skeleton. How do we stay safe while the coding agent builds u1?

The workflow builds the skeleton unit to completion before any other unit. Meanwhile the coding agent writes Terraform and Lambda code with today's guardrails: the Bash-only hook, and the admin profile in the shell.

A. Keep u1 first. Before it starts, you switch the shell that runs Claude Code to a read-only AWS profile by hand, an interim version of US1.4. u2 comes immediately after u1. (Recommended: removes the biggest risk at no build cost; the hook already blocks apply and destroy.)
B. Go back to Units Generation and move the most critical guardrail pieces (MCP deny-by-default, protected paths) into u1
C. Accept the risk until u2 is built
X. Other (please specify)

[Answer]: A

## Q2. [Delivery lead] In what order should the units after the skeleton be built?

A. Phase-gate order: u1, u2, u3 (Phase 1 gate), u4, u5 (Phase 2 gate), u6, u7 (Phase 3 gate). Recommended: each phase gate lands on its planned date (Dec 13, Dec 23, Jan 17) with something demoable.
B. Agents first: u1, u2, u4, u5, u6, u7, then u3. This gets to the agent sooner but defers rebuild, teardown and the budget.
C. Formal scoring (value plus urgency plus risk reduction, divided by size) to rank u2 to u7
X. Other (please specify)

[Answer]: A

## Q3. [Delivery lead] How big should a Bolt be?

u1 is extra-large; the others are medium or large.

A. One unit per Bolt, with u1's Bolt split into four PRs (lab and Rancher, telemetry and alert rule, intake and ledger, session and Rancher read), and each PR mergeable alone. Recommended: keeps "one task per PR" while the unit stays one Bolt.
B. Split u1 into two Bolts and keep the others one Bolt each
C. Bundle u3 and u4 into one Bolt, since they can be built in parallel
X. Other (please specify)

[Answer]: A

## Q4. [Delivery lead] Should units be built one at a time, or several at once?

A. One at a time: each unit's design and code finish before the next starts (recommended: you are the only reviewer and merger, so parallel work would queue on you anyway)
B. In parallel wherever the dependency graph allows (u3 alongside u4, u2 alongside u3)
X. Other (please specify)

[Answer]: A

## Q5. [Delivery lead] Which outside dependencies do you already have? (select all that apply)

Each one blocks a Bolt until it exists.

A. A Slack workspace and an incoming webhook (needed by u1 for dead-letter alerts)
B. The agent's GitHub App, created and installed on this repository with contents and pull-request permissions only (needed by u6)
C. Bedrock model access for Haiku 4.5, Sonnet 4.6 and Opus 4.6 through `us.` profiles, confirmed in the lab account (needed by u1's session and by u5)
D. The Phase 0 spike results: `rancher-ai-mcp` behind the Gateway, recorded as ADR-0002 (needed by u1's Rancher read; gate Nov 29)
X. Other (please specify)

[Answer]: X. None yet (the person: "I have none yet."). Update: C (the person: "I have access to Bedrock models now.")
