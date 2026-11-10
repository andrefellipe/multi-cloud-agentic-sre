# Units of Work: Phases 1 to 3

This file groups the 16 components in `inception/domain-design/components.md` into seven units of work. The grouping follows the ADRs in `inception/domain-design/decisions.md` and the decisions in `units-generation-questions.md` (Q1 to Q4 and the approved plan). Every story in `inception/user-stories/stories.md` belongs to exactly one unit, and every requirement in `inception/requirements-analysis/requirements.md` is reached through those stories. Build order and the critical path are not set here; Delivery Planning decides them.

## Unit index

| Unit ID | Directory | Name | Kind | Complexity | Deployment model |
|---|---|---|---|---|---|
| U1 | u1-walking-skeleton | Walking skeleton | service | XL | Standalone: Terraform (human apply), Fleet bundles, Lambda + DynamoDB, one AgentCore Runtime |
| U2 | u2-coding-agent-guardrails | Coding-agent guardrails | library | M | Embedded: repository tooling (Claude Code hooks, CI workflows) |
| U3 | u3-lab-operations | Lab operations | service | M | Standalone: Terraform (human apply), scheduled teardown job |
| U4 | u4-output-safety | Output safety | library | M | Embedded: in the AgentCore Runtime and the Lambda functions |
| U5 | u5-read-only-agents | Read-only agents | service | L | Shared: the AgentCore Runtime deployment from U1 |
| U6 | u6-remediation | Remediation | service | L | Shared: the AgentCore Runtime deployment, plus Gateway policies |
| U7 | u7-verification-and-control | Verification and control | service | L | Shared: the AgentCore Runtime and the intake Lambda, plus the kill-switch policy |

Deployment follows Q4 (hybrid):
- Intake, webhook handling and the ledger run as AWS Lambda functions with DynamoDB.
- The five agents and the session share one AgentCore Runtime deployment (one process, per the plan's inter-agent control).
- Terraform and Fleet bundles go out through their own Git paths.
- The guardrails are repository tooling.

## Unit definitions

### U1 u1-walking-skeleton (service, XL)

- **Description.** The thin end-to-end path the team practice requires first. An alert reaches the intake, an incident record exists, an agent session starts, and the agent makes one read through Rancher. Per Q2, it carries the full skeleton stories, including the hardened Rancher, the telemetry stack and the complete alert intake.
- **Components.** All of:
  - LabInfrastructure: VPC, EKS, Rancher host, AMP, CloudWatch, SNS, the incident table and the dead-letter queue.
  - PlatformBundles: the demo, flags, Collector and alert rules.
  - EventIntake: the alert path.
  - IncidentLedger: create, update, attach and the state machine.
  - Notifier: fixed-template dead-letter alerts only.
  - AgentSession: session start.
  - InvestigatorAgent: a single Rancher read.
  - ToolGovernance: the Rancher read-only target and read-only policy.
- **Responsibilities.** REQ-020 to REQ-024, REQ-030 to REQ-035, REQ-050, REQ-102 (read side), REQ-121 (first timestamps), REQ-140, REQ-141 (alerts).
- **Boundaries.**
  - No triage logic, root-cause reasoning or write tools.
  - The Investigator here does one fixed read to prove the path.
  - Webhook handling arrives in U7.
- **Notes and constraints.**
  - Human applies all Terraform.
  - Rancher behind TLS, IP allow-list and SSO with MFA (REQ-021).
  - Notifier posts only fixed templates until U4 exists (ADR-006).
  - The skeleton's end-to-end check is confirmed in Delivery Planning.

### U2 u2-coding-agent-guardrails (library, M)

- **Description.** Guardrails for the coding agent, plus the required CI gates that protect them and enforce the quality and evidence bars.
- **Components.** CodingAgentGuard and GuardrailCiGate. These extend `tools/claude-hooks/`, `.github/workflows/methodology-checks.yml` and `tools/ci/check_pr_body.py`.
- **Responsibilities.** REQ-001 to REQ-015, REQ-073 (agent PRs through the required checks), REQ-112, REQ-150, REQ-151, REQ-152 (CI side).
- **Boundaries.** It touches no lab resource, and its tests run locally and in CI only.
- **Notes and constraints.**
  - Changes to this unit's own files are protected paths. After the first merge, every later PR to them needs your `guardrail-change` label.
  - The settings install into `.claude/settings.json` is done by you, as the current runbook already does.

### U3 u3-lab-operations (service, M)

- **Description.** Operating the Phase 1 lab within budget, and the Phase 1 gate.
- **Components.** LabInfrastructure: rebuild and teardown commands, the AWS Budget, and the nightly or idle teardown job.
- **Responsibilities.** REQ-025, REQ-026, REQ-130, REQ-131, REQ-160.
- **Boundaries.** It adds no new runtime resources beyond the budget and the teardown schedule.
- **Notes and constraints.** The rebuild time is measured and recorded at the gate.

### U4 u4-output-safety (library, M)

- **Description.** One fail-closed path for every outbound text, built before the first Slack summary or recording (ADR-005).
- **Components.**
  - OutputSanitizer.
  - ReplayRecorder.
  - Notifier: summaries and escalations, retries, routed through the sanitizer.
- **Responsibilities.** REQ-063, REQ-090, REQ-091, REQ-103 (Slack webhook custody), REQ-104 (trace export of recorded calls), REQ-105, REQ-106 (configuration plumbing shared by agents).
- **Boundaries.** It makes no agent decisions. It only offers sanitize, record and notify to its callers.

### U5 u5-read-only-agents (service, L)

- **Description.** Phase 2: Triage and the full read-only Investigator, with budgets, tracing and the Phase 2 gate.
- **Components.**
  - TriageAgent.
  - InvestigatorAgent (full).
  - AgentSession: graph order, caps, tracing, persisting results.
  - ToolGovernance: Prometheus, CloudWatch Logs and Git read targets.
- **Responsibilities.** REQ-040, REQ-041, REQ-051 to REQ-055, REQ-101, REQ-104, REQ-106, REQ-111, REQ-132, REQ-161.
- **Boundaries.** No write tool other than the session's writes to the ledger and Slack (REQ-111).

### U6 u6-remediation (service, L)

- **Description.** Phase 3 change path: the Remediator's PR in allowed paths, and the independent Reviewer on a different model.
- **Components.**
  - RemediatorAgent.
  - ReviewerAgent.
  - ToolGovernance: GitHub App branch, PR and comment tools; path limits; merge and approve denials.
  - IncidentLedger: per-service remediation lock.
  - AgentSession: send-back loop.
- **Responsibilities.** REQ-060 to REQ-062, REQ-064, REQ-065, REQ-070 to REQ-072, REQ-102 (write side).
- **Boundaries.** It ends when a reviewed PR is waiting for your merge. What happens after the merge belongs to U7.

### U7 u7-verification-and-control (service, L)

- **Description.** Closing the loop after the human decision, the kill switch, and the Phase 3 gate.
- **Components.**
  - EventIntake: GitHub merge and close webhooks with HMAC verification.
  - VerifierAgent.
  - ToolGovernance: kill-switch policy.
  - AgentSession: kill-switch handling.
- **Responsibilities.** REQ-080 to REQ-083, REQ-100, REQ-110, REQ-120, REQ-141 (webhooks), REQ-162.
- **Boundaries.** It can open only one revert PR per incident. It adds no new remediation paths.
