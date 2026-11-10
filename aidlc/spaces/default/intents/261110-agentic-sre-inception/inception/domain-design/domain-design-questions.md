# Domain Design Questions

These questions decide the logical building blocks (the code you write) for Phases 1 to 3. They draw on the approved requirements (`inception/requirements-analysis/requirements.md`), the stories (`inception/user-stories/stories.md`) and the existing components (`aidlc/spaces/default/codekb/multi_cloud_agentic_SRE/component-inventory.md`). Deployment topology (how components are packaged into Lambdas, AgentCore runtimes and so on) is decided later, in Units Generation. Each question names the trade whose call it is.

## Q1. [Architect] How should the five SRE agents be split into components?

The plan uses a fixed graph: Triage, Investigator, Remediator, Reviewer, Verifier. Each has its own prompt, tools and model tier. The Reviewer must stay independent of the Remediator (REQ-070).

A. One component per agent role, plus a shared session component that runs the graph and enforces the token and step caps (recommended: each role changes at its own rate and is tested on its own, and the Reviewer's independence becomes a boundary rather than a convention)
B. One incident-response component, with the roles as internal modules
C. Two components: a read-only analysis component (Triage and Investigator) and a change component (Remediator, Reviewer and Verifier)
X. Other (please specify)

[Answer]: A

## Q2. [Architect] Which component owns the incident record?

Intake, Triage, the Investigator, the Remediator and the Verifier all add to an incident. Deduplication and "one remediation per service" depend on conditional writes (REQ-031, REQ-064).

A. A dedicated incident-ledger component owns the incident and its state machine; everyone else calls it to read or advance an incident (recommended: one writer enforces deduplication, the per-service lock and the timestamps for REQ-121)
B. The alert-intake component owns it, and the agents call intake to update it
C. Each agent writes its own section of the record directly
X. Other (please specify)

[Answer]: A

## Q3. [Architect] Where are GitHub merge and close webhooks received?

Merge and close events start the Verifier or close the incident (REQ-080, REQ-083). The requirements review flagged that inbound events need authentication (signature checks, publisher limits).

A. One event-intake component receives both inbound sources: alerts from SNS and webhooks from GitHub. It applies the same authentication, idempotency and dead-letter rules to both. Outbound GitHub writes go only through the governed tool gateway (recommended: one place to secure every trigger that starts agent work)
B. A GitHub-integration component handles both inbound webhooks and outbound PR operations; alert intake stays separate
C. A separate webhook-intake component beside alert intake
X. Other (please specify)

[Answer]: A

## Q4. [Security engineer] How should the coding-agent guardrails be structured?

Today one script guards shell commands only. The requirements add file-edit and MCP coverage, the read-only identity check, and one shared list of protected paths (REQ-001 to REQ-014).

A. One coding-agent-guard component with a single policy file (protected paths, MCP allowlist, blocked verb families) and one entry point per tool type (shell, file edit, MCP); a separate CI-gate component for the protected-path, settings and guard-test checks run from `main` (recommended: one source of truth for what is protected; the CI side changes on a different trigger)
B. Separate independent scripts per tool type, each with its own list
C. Fold the CI checks into the guard component
X. Other (please specify)

[Answer]: A

## Q5. [Security engineer] Where does secret scanning and redaction live?

Slack summaries and replay recordings (Phase 2) and PR descriptions (Phase 3) all need it (REQ-063, REQ-105). The story review found redaction scheduled only in Phase 3.

A. A standalone output-sanitizer component that every outbound path calls, built in Phase 2 before the first Slack post or recording (recommended: one fail-closed choke point, and it fixes the Phase 2 sequencing gap)
B. Each consumer (notifier, recorder, PR writer) carries its own redaction
X. Other (please specify)

[Answer]: A

## Q6. [Operations engineer] How should the human be notified in Phase 1, before the agents and Slack summaries arrive in Phase 2?

The dead-letter-queue alert in Phase 1 (REQ-033) needs a channel; the story review found none until Phase 2.

A. A notifier component built in Phase 1 that posts to Slack through the webhook in Secrets Manager; Phase 2 summaries reuse it (recommended: one channel from day one; moves the Slack setup earlier)
B. SNS email in Phase 1, Slack from Phase 2
C. CloudWatch alarm on the dead-letter queue only in Phase 1, with no message to a channel
X. Other (please specify)

[Answer]: A
