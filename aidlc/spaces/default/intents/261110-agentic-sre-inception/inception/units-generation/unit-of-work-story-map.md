# Unit Story Map

Each story in `inception/user-stories/stories.md` is assigned to the unit that implements it. Units are defined in `unit-of-work.md`.

## Story to unit

| Story | Unit ID | Directory |
|---|---|---|
| US1.1 | U2 | u2-coding-agent-guardrails |
| US1.2 | U2 | u2-coding-agent-guardrails |
| US1.3 | U2 | u2-coding-agent-guardrails |
| US1.4 | U2 | u2-coding-agent-guardrails |
| US1.5 | U2 | u2-coding-agent-guardrails |
| US2.1 | U1 | u1-walking-skeleton |
| US2.2 | U1 | u1-walking-skeleton |
| US2.3 | U1 | u1-walking-skeleton |
| US2.4 | U3 | u3-lab-operations |
| US2.5 | U3 | u3-lab-operations |
| US2.6 | U1 | u1-walking-skeleton |
| US2.7 | U3 | u3-lab-operations |
| US3.1 | U1 | u1-walking-skeleton |
| US3.2 | U5 | u5-read-only-agents |
| US3.3 | U5 | u5-read-only-agents |
| US3.4 | U5 | u5-read-only-agents |
| US3.5 | U5 | u5-read-only-agents |
| US3.6 | U4 | u4-output-safety |
| US3.7 | U4 | u4-output-safety |
| US3.8 | U5 | u5-read-only-agents |
| US3.9 | U5 | u5-read-only-agents |
| US4.1 | U6 | u6-remediation |
| US4.2 | U4 | u4-output-safety |
| US4.3 | U6 | u6-remediation |
| US4.4 | U6 | u6-remediation |
| US4.5 | U7 | u7-verification-and-control |
| US4.6 | U7 | u7-verification-and-control |
| US4.7 | U7 | u7-verification-and-control |
| US4.8 | U7 | u7-verification-and-control |
| US4.9 | U7 | u7-verification-and-control |
| US5.1 | U2 | u2-coding-agent-guardrails |
| US5.2 | U2 | u2-coding-agent-guardrails |

## Cross-cutting concerns

Each story is owned by one unit. The concerns that several units rely on are:

| Concern | Owner | Used by |
|---|---|---|
| Output sanitization (REQ-063) | U4 (US4.2, US3.6) | U5, U6, U7 for every outbound text |
| CI gates on every PR (REQ-073, REQ-150, REQ-151) | U2 (US5.1, US5.2) | All units' PRs once U2 is merged |
| Incident ledger and timestamps (REQ-121) | U1 (US2.6) | U5, U6, U7 record into it |
| Gateway policy (ToolGovernance) | U1 (read target), U5 (read targets), U6 (write tools), U7 (kill switch) | All agents |

The phase gate stories sit in the unit that completes each phase: US2.7 in U3, US3.9 in U5, US4.9 in U7.

## Implementation order within each unit

| Unit | Order of its stories |
|---|---|
| U1 | US2.1, then US2.2, US2.3, US2.6, US3.1 |
| U2 | US1.1, then US1.2, US1.5, US1.4, US1.3, US5.2, US5.1 |
| U3 | US2.5, then US2.4, US2.7 |
| U4 | US4.2, then US3.6, US3.7 |
| U5 | US3.2, then US3.3, US3.4, US3.5, US3.8, US3.9 |
| U6 | US4.1, then US4.3, US4.4 |
| U7 | US4.5, then US4.7, US4.6, US4.8, US4.9 |

## Coverage check

- All 32 stories are assigned, each to exactly one unit.
- Every unit has stories: U1 has 5, U2 has 7, U3 has 3, U4 has 3, U5 has 6, U6 has 3, U7 has 5.
