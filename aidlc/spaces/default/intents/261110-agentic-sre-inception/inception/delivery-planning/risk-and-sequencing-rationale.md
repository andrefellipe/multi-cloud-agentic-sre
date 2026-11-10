# Risk and Sequencing Rationale

This file explains why the Bolts in `bolt-plan.md` run in the order they do. A **Bolt** is one build pass over a piece of the work that ends in something that runs. The order is a path through the dependency DAG (directed acyclic graph) in `inception/units-generation/unit-of-work-dependency.md`, chosen in `delivery-planning-questions.md` Q2.

## Heuristics used

1. **Walking skeleton first** (Cockburn). The skeleton is the thinnest end-to-end slice, built first to prove the pieces connect.
   - It is required by the affirmed team practice (`inception/practices-discovery/team-practices.md`).
   - B1 proves the riskiest integration seams before features pile on them:
     - AWS, Rancher and EKS;
     - the telemetry and alert path;
     - AgentCore Runtime and Gateway.
2. **Risk-first for safety controls** (Boehm).
   - B2 (guardrails) comes immediately after B1, because every later Bolt is code written by the coding agent.
   - The interim read-only profile (Q1) covers the gap during B1.
3. **Phase-gate order for the rest** (Q2).
   - Each phase gate in `docs/plan.md` lands with something demoable: Phase 1 on Dec 13, Phase 2 on Dec 23, Phase 3 on Jan 17.
   - The phase gates are the plan's main defence against scope creep. Its top risk is never finishing, so each stop must be worth showing.

We did not use formal WSJF scoring (Weighted Shortest Job First: value plus urgency plus risk reduction, divided by size). The DAG leaves little freedom, and the gate dates already encode time criticality.

## Deviation from topological order

There is none. The chosen order u1, u2, u3, u4, u5, u6, u7 is one valid topological order of the DAG:
- u2 depends on nothing, so it could come first. It is placed after u1 because the skeleton must be the first unit.
- u3 and u4 could swap. u3 goes first so the Phase 1 gate lands before agent work.

## Sequencing risks

| # | Risk | Likelihood | Impact | Mitigation | Bolt |
|---|---|---|---|---|---|
| S1 | Coding agent acts unsafely before B2's guardrails exist | Medium | High | Interim read-only profile by hand (Q1); the hook already blocks apply, destroy and force-push; B2 is next | B1 |
| S2 | B1 is extra-large and slips the Phase 1 gate (Dec 13) | High | Medium | Four independently mergeable PRs (Q3); B3 can absorb the gate demo if B1 runs late | B1, B3 |
| S3 | Spike ADR-0002 (Rancher MCP behind the Gateway) fails | Medium | Medium | C9 is tool-agnostic; fall back to a generic Kubernetes MCP server through the Rancher proxy; decision due by the Nov 29 gate | B1 |
| S4 | Agent write tools exist before the kill switch | Medium | High | `writes_enabled` off by default (C9); you turn it on only after B7's kill-switch test | B6, B7 |
| S5 | Holiday break (Dec 24 to Jan 3) splits B6 and B7 | High | Low | B6 is fully replay-based, so it can pause safely; B7 needs live runs after the break | B6, B7 |
| S6 | Contract-review findings accepted as risk (write idempotency, lost webhooks, revert loop, lock lease) surface late in B6 or B7 | Medium | High | Revisit them in Functional Design for u6 and u7 before code; listed in the phase check | B6, B7 |
| S7 | You are the only reviewer and merger, so PRs queue | Medium | Medium | One Bolt at a time (Q4); small PRs | All |
