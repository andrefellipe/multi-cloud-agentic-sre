# Bolt Plan: Phases 1 to 3

A **Bolt** is one build pass over a piece of the work. It runs that piece's design and code stages and ends in something that runs and is merged through PRs.

This plan covers the seven units of work defined in `inception/units-generation/unit-of-work.md`. It follows the dependency DAG in `unit-of-work-dependency.md` and the story assignments in `unit-of-work-story-map.md`.

It also draws on:
- the components in `inception/domain-design/components.md`;
- the contracts in `inception/contract-design/contract-summary.md`;
- the requirements in `inception/requirements-analysis/requirements.md`;
- the stories in `inception/user-stories/stories.md`.

Decisions from `delivery-planning-questions.md`:
- **Q1:** use an interim read-only profile before u1.
- **Q2:** build in phase-gate order.
- **Q3:** one unit per Bolt, with u1 split into four PRs.
- **Q4:** one unit at a time.

Practices from `inception/practices-discovery/team-practices.md`:
- Squash merges through PRs you merge.
- Branch names `<type>/REQ-NNN-<topic>`.
- Walking skeleton first.

## Sequence

| # | Bolt | Unit(s) | Walking skeleton | Phase gate |
|---|---|---|---|---|
| 0 | Pre-Bolt step (you) | none | none | none |
| 1 | B1 skeleton | u1-walking-skeleton | **Yes** | none |
| 2 | B2 guardrails | u2-coding-agent-guardrails | No | none |
| 3 | B3 lab operations | u3-lab-operations | No | Phase 1 (Dec 13, 2026) |
| 4 | B4 output safety | u4-output-safety | No | none |
| 5 | B5 read-only agents | u5-read-only-agents | No | Phase 2 (Dec 23, 2026) |
| 6 | B6 remediation | u6-remediation | No | none |
| 7 | B7 verification and control | u7-verification-and-control | No | Phase 3 (Jan 17, 2027) |

The order matches the DAG's declaration order, so there is no deviation from it. Each Bolt starts only after the previous one is merged (Q4).

## Pre-Bolt step (you, before B1 starts)

- Switch the shell that runs Claude Code to a read-only AWS profile, and do write work only in a separate terminal (Q1). This is an interim version of US1.4 (REQ-012 to REQ-014); B2 makes it enforced.
- Provide the B1 dependencies listed in `external-dependency-map.md`:
  - Slack webhook;
  - Bedrock model access;
  - spike result or fallback ADR.

## B1 skeleton: u1-walking-skeleton (walking skeleton)

- **Stories.** US2.1, US2.2, US2.3, US2.6, US3.1.
- **PRs (Q3), each mergeable on its own:**
  1. `feat/REQ-020-lab-vpc-eks-rancher`: VPC, EKS, Rancher host behind TLS, IP allow-list, SSO with MFA; EKS imported.
  2. `feat/REQ-023-demo-telemetry-alerts`: Fleet bundles for the demo app, flags, Collector, alert rule to SNS, and the Grafana dashboard.
  3. `feat/REQ-030-intake-ledger`: alert intake (C1), incident ledger (C3), dead-letter queue, and the fixed-template Slack notice (C7).
  4. `feat/REQ-034-session-rancher-read`: session start (C4), the AgentCore Runtime, Gateway with the read-only `k8s_read` target (C9), and one Rancher read.
- **What this proves end to end.** The architecture's riskiest seams: EKS and Rancher, telemetry and alerting, the Lambda and DynamoDB intake, AgentCore Runtime and Gateway, and the Rancher proxy.
- **Definition of done.**
  - All four PRs are merged, and you have applied the Terraform.
  - Required checks are green.
  - The skeleton demo passes.
  - You sign off the skeleton checkpoint.
- **Confidence hypothesis.** An injected fault on EKS becomes an incident record within 60 s and an agent session within 2 min. The session lists pods through the Rancher proxy. The same token is refused a write and a Secret read.
- **Expected demo.** Set a demo flag out of band. Then show:
  - the alert in Managed Prometheus;
  - the incident record with its timestamps;
  - the session trace with one `k8s_read` call;
  - a denied write attempt.

## B2 guardrails: u2-coding-agent-guardrails

- **Stories.** US1.1 to US1.5, US5.1, US5.2.
- **Definition of done.**
  - The guard covers shell, file-edit and MCP calls from one policy file, with tests for every rule.
  - Required checks run from `main`.
  - The read-only identity is enforced.
  - You have installed the settings change.
- **Confidence hypothesis.** The coding agent cannot edit a protected path, call a non-allowlisted MCP tool, or use a cloud tool under a non-read-only identity. A PR that weakens a check still fails.
- **Expected demo.** Five blocked attempts, one per form, with their audit lines. A fixture PR that touches `tools/ci/` fails without the label.

## B3 lab operations: u3-lab-operations (Phase 1 gate)

- **Stories.** US2.4, US2.5, US2.7.
- **Definition of done.**
  - Rebuild and teardown commands work.
  - The budget and its alerts are applied.
  - The nightly teardown runs.
  - The Phase 1 gate record is complete, and the phase gate tag is on `main`.
- **Confidence hypothesis.** The lab rebuilds from zero, in a time we record, and tears down to no billable resources.
- **Expected demo.** A timed rebuild, an injected fault end to end, and a teardown followed by a clean resource scan.

## B4 output safety: u4-output-safety

- **Stories.** US3.6, US3.7, US4.2.
- **Definition of done.** The sanitizer fails closed. Slack summaries and replay recordings are routed through it. Planted-secret tests pass.
- **Confidence hypothesis.** No agent text reaches Slack or storage unredacted, even when the scanner is down.
- **Expected demo.** A planted secret is redacted in Slack. With the scanner stopped, nothing is posted.

## B5 read-only agents: u5-read-only-agents (Phase 2 gate)

- **Stories.** US3.2 to US3.5, US3.8, US3.9.
- **Definition of done.**
  - Triage and the Investigator run on scenarios 1, 2 and 3.
  - Budgets and tracing work.
  - Gate scorecard: root causes match your labels, with zero write attempts.
  - The phase gate tag is on `main`.
- **Confidence hypothesis.** A read-only agent finds the right root cause on three EKS faults and never attempts a write.
- **Expected demo.** Scenario 2 (payment errors), from alert to Slack summary with evidence links. Scenario 14 shows the injection flag.

## B6 remediation: u6-remediation

- **Stories.** US4.1, US4.3, US4.4.
- **Definition of done.**
  - Remediator and Reviewer work end to end in replay.
  - GitHub write tools exist but stay off (`writes_enabled: false`, C9) until B7's kill switch is tested.
  - The per-service lock holds.
- **Confidence hypothesis.** The Remediator produces a correct fix inside the allowed paths, and a different-model Reviewer rejects a planted bad fix. Both are shown in replay, with writes disabled.
- **Expected demo.** A replayed scenario 1 produces the PR body and diff that would be opened. A planted bad fix is rejected twice and escalated.

## B7 verification and control: u7-verification-and-control (Phase 3 gate)

- **Stories.** US4.5 to US4.9.
- **Definition of done.**
  - Signed webhooks start the Verifier.
  - Revert happens at most once.
  - The kill switch is timed under 60 s.
  - You turn `writes_enabled` on only after the kill-switch test.
  - Scenarios 1 and 2 are fixed end to end with your merge, and scenario 14 is flagged.
  - The phase gate tag is on `main`.
- **Confidence hypothesis.** The closed loop works on real faults with you as the only gate, and you can stop every agent within a minute.
- **Expected demo.** Scenario 1 runs live: alert, PR, review, your merge, Fleet sync, recovered. Then the kill switch is triggered mid-session, with its timing shown.
