# Contract Summary: Phases 1 to 3

Formal agreements across every boundary between the seven units in `inception/units-generation/unit-of-work.md`, following the dependency DAG in `inception/units-generation/unit-of-work-dependency.md`. Payload shapes come from the entities in `inception/domain-design/components.md`. Timing and safety bounds come from `inception/requirements-analysis/requirements.md`.

Decisions taken in `contract-design-questions.md`:
- **Q1. Contract definitions.** In-process contracts are Pydantic models in one shared package, `agents/contracts/`. JSON Schema is exported from those models for these docs and for CI checks.
- **Q2. Versioning.** Every message carries `schema_version`.
- **Q3. Write-enable flag.** It is off by default and gates every GitHub write tool until the kill switch exists.
- **Q4. Timeouts and retries.** Each boundary has its own defaults.

The system exposes no public API in Phases 1 to 3. Its external boundaries are the inbound alert feed and the GitHub webhooks it consumes, plus the PR description and CI checks that the human and GitHub consume.

## Contracts

| # | Provider Unit | Consumer | Mechanism | Owner |
|---|---|---|---|---|
| C1 | External: Managed Prometheus alert manager (via SNS) | u1-walking-skeleton (EventIntake) | Async event (SNS to Lambda) | u1 |
| C2 | External: GitHub (merge and close webhooks) | u7-verification-and-control (EventIntake) | HTTPS webhook (HMAC-signed) | u7 |
| C3 | u1-walking-skeleton (IncidentLedger) | u1 EventIntake; u5, u6, u7 via AgentSession | Shared schema plus in-process calls; DynamoDB conditional writes | u1 |
| C4 | u1-walking-skeleton (EventIntake) | u1 AgentSession; u7 for Verifier sessions | Async invocation (AgentCore Runtime) | u1 |
| C5 | u5, u6, u7 (agent roles) | u1/u5 AgentSession | In-process shared schema (agent result envelope) | u1 owns the envelope; each role unit owns its payload |
| C6 | u4-output-safety (OutputSanitizer) | u4 Notifier and ReplayRecorder; u6; u7 | In-process call | u4 |
| C7 | u1 Notifier (fixed templates); u4 (free-text summaries) | u1 EventIntake; u5 AgentSession | In-process call | u1 owns the interface; u4 extends it |
| C8 | u4-output-safety (ReplayRecorder) | u5 AgentSession | In-process call; S3 object | u4 |
| C9 | u1 ToolGovernance (read targets); extended by u5, u6, u7 | All agent roles | AgentCore Gateway (MCP) with Cedar policy | u1; u6 owns the write tools and the write-enable flag; u7 owns the kill switch |
| C10 | u6-remediation (agent PR description) | External: human reviewer; u2 PR description check | Shared schema (Markdown sections) | u6, checked by u2 |
| C11 | u2-coding-agent-guardrails (CI gate) | External: GitHub ruleset and every PR author | GitHub required checks and labels | u2 |

## Per-contract specs

### C1. Alert intake (external, inbound)

```yaml
asyncapi: 3.0.0
info: {title: Alert intake, version: 1.0.0}
channels:
  labAlerts:
    address: sns:lab-alerts            # topic; publish allowed only to the Managed Prometheus alert manager role (ADR-003)
    messages:
      alertNotification:
        payload:
          type: object
          required: [receiver, status, alerts]
          properties:
            status: {type: string, enum: [firing, resolved]}
            alerts:
              type: array
              items:
                type: object
                required: [labels, startsAt, fingerprint]
                properties:
                  labels:
                    type: object
                    required: [alertname, severity, service, cluster, cloud]
                  startsAt: {type: string, format: date-time}
                  fingerprint: {type: string}
operations:
  receiveAlert:
    action: receive
    channel: {$ref: '#/channels/labAlerts'}
x-behaviour:
  idempotency_key: "sha256(fingerprint + startsAt + status)"   # REQ-032, REQ-141
  timeout_to_record_s: 60                                       # REQ-030
  retries: {ledger_write: 3, backoff: jittered}                 # Q4
  dead_letter: {after_attempts: 3, notify: C7 fixed template}   # REQ-033, REQ-140
  below_threshold: record only, no session                      # REQ-035
  unknown_fields: ignored
```

### C2. GitHub merge and close webhooks (external, inbound)

```yaml
openapi: 3.1.0
info: {title: GitHub webhook intake, version: 1.0.0}
paths:
  /webhooks/github:
    post:
      parameters:
        - {in: header, name: X-Hub-Signature-256, required: true, schema: {type: string}}
        - {in: header, name: X-GitHub-Delivery, required: true, schema: {type: string}}
        - {in: header, name: X-GitHub-Event, required: true, schema: {type: string, enum: [pull_request]}}
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [action, pull_request, repository]
              properties:
                action: {type: string, enum: [closed]}
                pull_request:
                  type: object
                  required: [number, merged, head, merge_commit_sha, user]
      responses:
        '202': {description: Accepted; Verifier session started (merged) or incident closed (not merged)}
        '401': {description: Signature missing or invalid; logged, nothing acted on}
        '200': {description: Duplicate delivery ID; no effect (REQ-141)}
x-behaviour:
  signature: HMAC-SHA256 with the secret in Secrets Manager (ADR-003)
  accepted_only_for: PRs opened by the agent GitHub App on this repository
  idempotency_key: X-GitHub-Delivery
  merged_true: start Verifier session within 120 s (C4, REQ-080)
  merged_false: incident closed as not remediated (REQ-083)
```

### C3. Incident ledger

```yaml
shared-schema:
  name: Incident
  schema_version: 1
  owner: u1-walking-skeleton (IncidentLedger)
  fields:
    incident_id: string            # ULID
    service: string
    status: enum [open, triaged, investigating, pr_open, awaiting_merge, verifying, recovered, not_remediated, escalated, closed_no_action]
    severity: string
    alerts: list[AlertRef]         # fingerprint, startsAt
    triage_decision: enum [act, no_action, duplicate] | null
    root_cause: string | null
    evidence_links: list[url]
    confidence: enum [low, medium, high] | null
    injection_flags: list[string]
    pr_url: url | null
    revert_count: int              # max 1 (REQ-082)
    tokens_used: int
    steps_used: int
    estimated_cost_usd: decimal    # labelled estimate (REQ-132)
    timestamps: {alert_fired, record_created, session_started, pr_opened, merged, verified}   # REQ-121
  operations:
    create_or_attach(alert) -> Incident        # conditional write on open incident per service (REQ-031)
    advance(incident_id, to_status, patch) -> Incident   # rejected if the transition is not in the state machine
    acquire_service_lock(service, incident_id) -> bool   # REQ-064
    release_service_lock(service, incident_id)
  errors: [TransitionNotAllowed, LockHeld, ConditionalCheckFailed, StoreUnavailable]
  timeout_s: 2
  retries: 3 jittered (Q4); StoreUnavailable after retries -> caller routes to dead-letter queue
  writers: [EventIntake, AgentSession]   # ADR-002, ADR-007; agents never write
```

### C4. Session start

```yaml
asyncapi: 3.0.0
info: {title: Session start, version: 1.0.0}
channels:
  sessionStart:
    address: agentcore-runtime:sre-agents
    messages:
      startSession:
        payload:
          type: object
          required: [schema_version, incident_id, kind, requested_at]
          properties:
            schema_version: {const: 1}
            incident_id: {type: string}
            kind: {type: string, enum: [incident, verifier]}
            merge_commit_sha: {type: string}       # required when kind = verifier
            requested_at: {type: string, format: date-time}
x-behaviour:
  start_deadline_s: 120          # REQ-034, REQ-080
  attempts: 3 then dead-letter queue (Q4)
  duplicate_start_for_incident: ignored while a session of the same kind is live
```

### C5. Agent result envelope

```yaml
shared-schema:
  name: AgentResult
  schema_version: 1
  owner: u1 (envelope); u5 (triage, investigation), u6 (remediation, review), u7 (verification) own their payloads
  envelope:
    role: enum [triage, investigator, remediator, reviewer, verifier]
    incident_id: string
    outcome: enum [ok, escalate, denied, budget_exhausted, error]
    payload: one of the role payloads below
    tool_calls: list[{tool, started_at, duration_ms, decision: allowed|denied, deny_reason}]   # how AgentSession sees calls and kill-switch denials (domain-design review R-01)
    tokens_used: int
    steps_used: int
  payloads:
    triage: {decision: act|no_action|duplicate, reason: string}
    investigation: {root_cause: string, evidence_links: [url], queries: [string], confidence: low|medium|high, partial_evidence: bool, injection_flags: [string], fix_in_allowed_paths: bool}
    remediation: {branch: string, pr_url: url, changed_paths: [string]}
    review: {verdict: pass|send_back, reasons: [string], reviewer_model_id: string}
    verification: {fleet_synced: bool, alert_cleared: bool, decision: recovered|revert, revert_pr_url: url|null}
  validation: AgentSession validates every result against this schema; an invalid result is treated as outcome=error and escalated
```

### C6. Output sanitizer

```yaml
shared-schema:
  name: Sanitize
  schema_version: 1
  owner: u4-output-safety
  request: {text: string, destination: slack|pr_body|pr_comment|replay}
  response:
    ok: {text: string, redactions: int}
    failure: {reason: scanner_unavailable|scanner_error}
  behaviour:
    fail_closed: true            # caller must not post or store on failure (REQ-063, ADR-005)
    retries: 0                   # Q4
```

### C7. Notify

```yaml
shared-schema:
  name: Notify
  schema_version: 1
  owner: u1 (interface and fixed templates); u4 adds free-text kinds
  request:
    kind: enum [dead_letter_alert, incident_closed, incident_escalated, pr_opened]
    incident_id: string | null
    pr_url: url | null
    body: string | null          # null for fixed-template kinds; free text only when sanitized through C6
  behaviour:
    retries: 3 with backoff (Q4)
    on_failure: record on incident, return without raising (REQ-091)
    phase_1_restriction: only dead_letter_alert, fixed template, until C6 exists (ADR-006)
```

### C8. Replay record

```yaml
shared-schema:
  name: ToolCallRecording
  schema_version: 1
  owner: u4-output-safety
  record: {recording_id: string, incident_id: string, tool: string, input: json, output: json, recorded_at: date-time}
  behaviour:
    input_and_output_sanitized_via: C6 (destination=replay)
    on_sanitizer_failure: recording skipped and noted on the incident
    storage: S3, key incidents/<incident_id>/<recording_id>.json
```

### C9. Governed tools and policy

```yaml
shared-schema:
  name: ToolCatalogue
  schema_version: 1
  owner: u1 (read targets); u5 (metrics, logs, Git reads); u6 (GitHub writes, write-enable flag); u7 (kill switch)
  tools:
    - {name: k8s_read, via: Rancher proxy, verbs: [get, list, watch], secrets: denied}       # REQ-050
    - {name: prometheus_query, read: true}
    - {name: cloudwatch_logs_query, read: true}
    - {name: git_history_read, read: true}
    - {name: github_create_branch, write: true, gated_by: writes_enabled}
    - {name: github_open_pr, write: true, gated_by: writes_enabled, allowed_paths_source: platform/allowed-remediation-paths.yaml}
    - {name: github_comment, write: true, gated_by: writes_enabled}
  denied_always: [github_merge, github_approve, rulesets, repo_settings, shell, k8s_write, cloud_write]   # REQ-061, REQ-102
  flags:
    writes_enabled: {default: false, set_by: human only, precondition: kill switch merged and tested (Q3)}
    kill_switch: {default: off, effect: deny all tools, propagation_s: 60}                 # REQ-100
  deny_response: {decision: denied, reason: enum [not_in_catalogue, path_not_allowed, writes_disabled, kill_switch, policy]}
  timeouts: {per_call_s: 30, read_retries: 2, write_retries: 0}                             # Q4
  logging: every denial logged with incident_id (REQ-110, REQ-111)
```

### C10. Agent PR description

```yaml
shared-schema:
  name: AgentPrDescription
  schema_version: 1
  owner: u6-remediation; checked by u2 (tools/ci/check_pr_body.py)
  required_sections:
    - "Summary"            # includes incident ID
    - "Requirements:"      # REQ IDs or n/a
    - "## AI involvement"  # "AI wrote:" and "I changed or rejected:"
    - "Evidence"           # root cause, queries, graph links, confidence
    - "Risk and rollback"  # rollback plan
  constraints:
    sanitized_via: C6 (destination=pr_body)
    changed_paths: subset of platform/allowed-remediation-paths.yaml
```

### C11. CI gate

```yaml
shared-schema:
  name: RequiredChecks
  schema_version: 1
  owner: u2-coding-agent-guardrails
  checks:
    - {name: pr-evidence, runs_from: main, inputs: [PR body via env, changed files]}
    - {name: guardrail-paths, runs_from: main, protected_list_source: main copy of the guard policy, label: guardrail-change, label_actor: repository owner only, reruns_on: [labeled, unlabeled, synchronize]}
    - {name: settings-wiring, runs_from: main}
    - {name: guard-tests, runs_from: main}
    - {name: quality, checks: [ruff, type-check, shellcheck, terraform-fmt-validate, coverage>=80, pinning]}
    - {name: traceability, report: REQ -> tests}
  never: execute PR-branch code in a privileged job (REQ-008)
```

## Contract ownership rules

- **Ownership.** The owner named in the table maintains the spec and its Pydantic models in `agents/contracts/` (Q1). For non-Python boundaries (Terraform, CI, GitHub), the owning unit's files are the spec. Consumers never fork a contract.
- **Additive changes.** New optional fields, new enum values that consumers can ignore, and new tools gated off by default are allowed within a phase. Consumers ignore unknown fields (Q2).
- **Breaking changes.** A breaking change needs a new `schema_version` major. Both versions are accepted for one release. Replay recordings on the old version must still load. The change is recorded as an ADR in `docs/adr/`.
- **Safety-relevant contracts.** C2, C9, C10 and C11 are safety-relevant: changing them reduces or reshapes a control. Changes to C9 deny rules and the C11 checks live in protected paths and need your `guardrail-change` label.
- **Single source for allowed paths.** The allowed remediation paths live in one file, `platform/allowed-remediation-paths.yaml`, owned by u6. The Gateway policy (C9) and the PR check (C10) read that file. This resolves the domain-design review finding R-06.

## Open questions

| Contract | Question | Blocks |
|---|---|---|
| C11 | How the gate proves the `guardrail-change` label was applied by the owner and not by the agent's session, when both use the same GitHub identity (requirements review R-01) | u2 |
| C9 | Whether `rancher-ai-mcp` or a generic Kubernetes MCP server provides `k8s_read` (spike ADR-0002) | u1 |
| C1 | The exact severity threshold that starts a session (proposed: critical and warning) | u1 |
| C4 | Whether the Verifier waits inside one session or re-triggers itself, and how polling counts against the 40-step cap (domain-design review R-05) | u7 |
| C3 | Where InboundEvent idempotency keys are stored: a separate table, or a ledger-owned item type (domain-design review R-04) | u1 |
