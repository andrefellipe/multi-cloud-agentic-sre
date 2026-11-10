# Architecture Decisions: Domain Design

These ADRs record the component-boundary decisions taken in `domain-design-questions.md` (Q1 to Q6), plus one design choice of the architect's (ADR-007). They build on the approved requirements (`inception/requirements-analysis/requirements.md`) and stories (`inception/user-stories/stories.md`), and on the existing architecture described in `aidlc/spaces/default/codekb/multi_cloud_agentic_SRE/architecture.md`.

Numbering here is local to this design record. When a decision is filed in the repository's `docs/adr/` (from `0000-template.md`, as `CLAUDE.md` requires), it takes the next free repository number. Repository ADR-0002 and ADR-0003 are reserved for the Phase 0 spikes.

---

## ADR-001: One component per agent role, plus a shared session component

- **Context.** Phases 2 and 3 run five agents: Triage, Investigator, Remediator, Reviewer and Verifier. Each has its own prompt, tool set and model tier. The Reviewer must run on a different model from the Remediator and judge it independently (REQ-070). Budgets, the kill switch and tracing apply across all roles (REQ-100, REQ-101, REQ-104).
- **Decision.** Each role is its own component (TriageAgent, InvestigatorAgent, RemediatorAgent, ReviewerAgent, VerifierAgent). A shared AgentSession component runs the fixed graph and owns the cross-role concerns. [Q1]
- **Consequences.**
  - Positive: each role is tested and evaluated alone; prompt or model changes stay local; the Reviewer's independence is visible in the dependency graph, because it shares no code path with the Remediator except through AgentSession.
  - Negative: more components to package; hand-off contracts between AgentSession and each role must be specified in Contract Design.
- **Security and compliance.** Separating Reviewer from Remediator is a control for ASI09 (human-agent trust) and ASI08 (cascading failures).
- **Alternatives Rejected.**
  - One incident-response component with internal modules: simpler packaging, but prompts that change for different reasons would be coupled, and the Reviewer's independence would rest on convention.
  - An analysis component and a change component: fewer parts, but the Reviewer would share a component with the Remediator it judges.

## ADR-002: A single incident ledger owns the incident record

- **Context.** Intake and every agent role add to an incident. Deduplication (REQ-031), "one remediation per service" (REQ-064) and the latency timestamps (REQ-121) all need atomic, conditional updates.
- **Decision.** IncidentLedger is the only writer of the Incident and ServiceLock entities. It holds them in a table with conditional writes and enforces the incident state machine. EventIntake and AgentSession call it; agents return results to AgentSession instead of writing directly. [Q2]
- **Consequences.**
  - Positive: one place enforces invariants; the state machine is testable alone.
  - Negative: the ledger is a hot dependency; if it is unavailable, intake falls back to the dead-letter queue (REQ-033).
- **Security and compliance.** A single writer limits what a compromised agent could corrupt: agents hold no incident-table write tool.
- **Alternatives Rejected.**
  - Intake owns the record: intake would grow agent-specific update logic.
  - Each agent writes its own section: several writers, with no single enforcement of the per-service lock.

## ADR-003: One authenticated event intake for alerts and GitHub webhooks; outbound GitHub writes only through the gateway

- **Context.** Two inbound sources start or end agent work: Prometheus alerts through SNS (REQ-030) and GitHub merge and close webhooks (REQ-080, REQ-083). The requirements review found both unauthenticated as written. Both need idempotency (REQ-141) and dead-letter handling (REQ-033, REQ-140).
- **Decision.** EventIntake receives both sources:
  - Alerts are accepted only from the lab SNS topic, whose publish permission is limited to the alert manager.
  - Webhooks are accepted only with a valid GitHub HMAC signature; the secret is held in Secrets Manager.
  - Both share idempotency keys and the dead-letter queue.
  - All outbound GitHub writes (branch, PR, comment, revert PR) go through the governed gateway tool, never through a custom client. [Q3]
- **Consequences.**
  - Positive: one place to secure every trigger; forged or replayed events are rejected uniformly.
  - Negative: EventIntake handles two payload formats.
- **Security and compliance.** Addresses the accepted requirements-review finding on unauthenticated event sources (ASI02, ASI10).
- **Alternatives Rejected.**
  - A GitHub-integration component for inbound and outbound: puts an outbound write client outside the gateway's policy.
  - A separate webhook intake: duplicates the authentication and idempotency rules.

## ADR-004: One coding-agent guard with a single policy file, plus a separate CI gate run from `main`

- **Context.**
  - Today `tools/claude-hooks/guard-bash.sh` guards shell commands only.
  - The requirements add file-edit and MCP coverage, the read-only identity check, and bypass hardening (REQ-001 to REQ-014).
  - The CI gate must not run the PR's own copy of its checks (REQ-008).
  - A code-owner review rule is not workable, because GitHub forbids self-approval.
- **Decision.**
  - CodingAgentGuard has one policy file (protected paths, MCP allowlist, blocked verb families, read-only role reference) and one entry point per tool type.
  - GuardrailCiGate holds the required CI checks:
    - the protected-path check with the owner-applied `guardrail-change` label;
    - the settings-wiring check;
    - guard tests;
    - pinning, quality and traceability gates.
  - The CI gate runs from `main`'s copy. [Q4]
- **Consequences.**
  - Positive: one list of protected paths; the CI side cannot be weakened by the PR it judges.
  - Negative: a privileged CI job that reads PR metadata is itself an injection target (risk R2), so it must never execute PR code.
  - Open: how CI proves the label came from the owner (requirements-review finding R-01, accepted as risk) is settled in NFR or functional design.
- **Security and compliance.** The core control for "the coding agent cannot change its own guardrails". It remains defense in depth behind the read-only credentials.
- **Alternatives Rejected.**
  - Separate scripts per tool type: several protected-path lists drift.
  - CI checks folded into the guard: the checks would run from the PR's copy.

## ADR-005: A standalone output sanitizer, built in Phase 2

- **Context.** Secret scanning and redaction (REQ-063) are needed on Slack summaries and replay recordings in Phase 2 (REQ-090, REQ-105), and on PR text in Phase 3. The story review found redaction scheduled only in Phase 3.
- **Decision.** OutputSanitizer is one fail-closed component that every outbound text path calls: Notifier, ReplayRecorder, RemediatorAgent, ReviewerAgent, VerifierAgent. It is built in Phase 2, before the first Slack summary or recording. [Q5]
- **Consequences.**
  - Positive: one rule set and one choke point; closes the Phase 2 sequencing gap.
  - Negative: a scanner outage stops all outbound posting. This is accepted by design (fail closed).
- **Security and compliance.** Data-leak control for a repository that goes public in Phase 7.
- **Alternatives Rejected.**
  - Redaction inside each consumer: duplicated rules, and Phase 2 consumers would ship without it.

## ADR-006: Slack notifier from Phase 1, limited to fixed templates until the sanitizer exists

- **Context.** Phase 1's dead-letter handling needs a human channel (REQ-033). The story review found none before Phase 2. OutputSanitizer arrives in Phase 2 (ADR-005).
- **Decision.** Notifier is built in Phase 1 and posts to Slack through the webhook in Secrets Manager. In Phase 1 it sends only fixed-template dead-letter alerts with no free text. From Phase 2, every message passes through OutputSanitizer. [Q6]
- **Consequences.**
  - Positive: one channel from day one.
  - Negative: the Slack workspace and webhook (assumption A4) are needed in Phase 1, not Phase 2.
- **Security and compliance.** Fixed templates carry no tool output, so no secret can leak before the sanitizer exists.
- **Alternatives Rejected.**
  - SNS email first: two channels to maintain and test.
  - Dead-letter alarm only: the human is not told in the channel the stories assume.

## ADR-007: Agents are stateless; AgentSession persists their results

- **Context.** With a single ledger writer (ADR-002), agents need a path to record their outcomes.
- **Decision.** Agent components take the incident context from AgentSession and return structured results; AgentSession writes those results to IncidentLedger. Agents hold no incident-table tool. (Architect's decision, following from ADR-002.)
- **Consequences.**
  - Positive: agents are replayable from recorded inputs; a compromised agent cannot rewrite incident history.
  - Negative: AgentSession must validate each agent's structured output before persisting it, which is the "malformed output" corner from the checklist.
- **Security and compliance.** Narrows each agent's write surface (ASI03).
- **Alternatives Rejected.**
  - Agents write through a ledger tool behind the gateway: workable, but adds a write tool to every agent's catalogue for no gain.
