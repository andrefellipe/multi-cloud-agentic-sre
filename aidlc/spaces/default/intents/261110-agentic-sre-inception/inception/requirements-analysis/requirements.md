# Requirements: Multi-Cloud Agentic SRE, Phases 1 to 3

Every requirement has a stable `REQ-NNN` ID and an EARS acceptance criterion. The IDs carry into tasks, branches, commits, PRs, tests and eval scenarios. Each requirement ends with its source and how it is verified. `docs/plan.md` is treated as input to question, not as settled requirements: where this document differs from the plan, the source says why.

Source tags:
- `[desc]`: your initial request.
- `[Qn]`: answer n in `requirements-analysis-questions.md`.
- `[plan: section]`: `docs/plan.md`.
- `[RE: Sn]`: finding n in `aidlc/spaces/default/codekb/multi_cloud_agentic_SRE/code-quality-assessment.md`.
- `[practice]`: the affirmed team practices in `inception/practices-discovery/team-practices.md`.
- `[CLAUDE.md]`: the project rules.

Context comes from the reverse-engineering artifacts:
- `aidlc/spaces/default/codekb/multi_cloud_agentic_SRE/business-overview.md`: actors and capabilities.
- `aidlc/spaces/default/codekb/multi_cloud_agentic_SRE/architecture.md`: as-built vs. as-planned architecture, incident lifecycle.
- `aidlc/spaces/default/codekb/multi_cloud_agentic_SRE/code-structure.md`: protected paths, hook contract, existing checks.

## Intent analysis

- **Goal.** Build the first three phases of an open SRE agent system on AWS. It investigates incidents on Amazon EKS read-only through Rancher, proposes fixes only as pull requests a human merges, and verifies recovery afterwards. Along the way it proves that the coding agent building it is itself kept within safe limits.
- **Type.** New system on an existing Phase 0 scaffold (brownfield repository, greenfield product code).
- **Scope.** Multi-component and cross-account:
  - AWS foundation and lab cluster;
  - alert intake;
  - five agents on Bedrock AgentCore;
  - GitHub write path;
  - development guardrails.
- **Complexity.** Complex: new managed services, a safety-critical write path, and an AI component whose behaviour has to be bounded and measured.
- **Phases covered.**
  - Phase 1, Foundation on AWS.
  - Phase 2, Agent prototype, read-only.
  - Phase 3, Closed-loop remediation.
  - The coding-agent guardrail requirements (group A) apply from now, ahead of Phase 1 code. [desc]

### Actors

| Actor | Role in Phases 1 to 3 |
| --- | --- |
| Human operator (repository owner) | Merges or closes agent PRs, applies Terraform, pulls the kill switch, labels guardrail changes; the only gate to the lab cluster |
| Coding agent (Claude Code) | Builds the system under AI-DLC; bounded by group A |
| SRE agents | Triage, Investigator, Remediator, Reviewer, Verifier (the Scribe is Phase 6) [Q1] |
| CI (GitHub Actions) | Runs required checks on every PR, human or agent |

## Functional requirements

### A. Coding-agent guardrails (development safety)

Protected paths, used by every requirement in this group:
- `.mcp.json`
- `.claude/settings.json`
- `.github/`
- `tools/claude-hooks/`
- `tools/ci/`
- `docs/evidence/hook-audit.jsonl`

| ID | Requirement (EARS) | Source | Verified by |
| --- | --- | --- | --- |
| REQ-001 | WHEN the coding agent calls a file-editing tool (Edit, Write, NotebookEdit or equivalent) on a protected path, THE SYSTEM SHALL block the call before it runs and tell the agent which rule blocked it. | [desc], [Q4], [RE: S2] | Guard test: one allowed and one blocked case per protected path |
| REQ-002 | WHEN the coding agent runs a shell command that would create, change, move, delete or change permissions on a protected path (for example redirection, `tee`, `sed -i`, `cp`, `mv`, `rm`, `chmod`, `git checkout`/`restore` of the path), THE SYSTEM SHALL block the command. | [desc], [Q4] | Guard test per write form |
| REQ-003 | WHEN the coding agent calls an MCP tool that is not on the read-only MCP allowlist, THE SYSTEM SHALL block the call. | [desc], [Q5], [RE: S1] | Guard test: one allowlisted read tool passes; `aws-mcp` script runner, a serverless deploy tool and an unknown tool are blocked |
| REQ-004 | THE SYSTEM SHALL keep the read-only MCP allowlist inside a protected path, so the coding agent cannot extend it. | [Q5], [Q4] | Path check in REQ-001 tests |
| REQ-005 | IF a guard hook fails, times out or cannot parse its input, THEN THE SYSTEM SHALL block the tool call. | ADR-0004, [practice] | Guard test with malformed input and a forced script error |
| REQ-006 | WHEN any guard blocks a call, THE SYSTEM SHALL append one JSON line to `docs/evidence/hook-audit.jsonl`. The line SHALL hold the timestamp, the tool type (shell, file edit or MCP), the rule name and the MCP server and tool name where applicable, and never the command arguments or file content. | [plan: Methodology], [RE: S10] | Audit-content test |
| REQ-007 | WHEN a pull request changes a protected path, THE SYSTEM SHALL fail a required CI check unless the repository owner has applied the `guardrail-change` label to that PR. | [desc], [Q4], [RE: S7] | CI test on a fixture PR with and without the label |
| REQ-008 | THE SYSTEM SHALL run the protected-path check and the methodology checks from `main`'s copy of the workflow and scripts, never from the PR's copy, and SHALL not check out or execute PR code in that privileged job. | [Q4], [RE: S7] | Workflow review plus a fixture PR that weakens a check script and still fails |
| REQ-009 | WHEN `.claude/settings.json` on a PR branch no longer wires the guard hooks for shell, file-edit and MCP tools with fail-closed behaviour, THE SYSTEM SHALL fail the required CI check. | [RE: S8], ADR-0004 | CI test with a settings file missing each matcher |
| REQ-010 | WHEN a blocked shell verb is preceded by global flags (for example `kubectl -n x delete`, `terraform -chdir=dir apply`, `helm -n x uninstall`) or chained after another command, THE SYSTEM SHALL block it. A `--dry-run` flag SHALL exempt only the command segment that carries it. | [RE: S4], [RE: S5] | Guard tests for each bypass form listed in the code-quality assessment |
| REQ-011 | WHEN the coding agent runs a command that merges or approves a PR, deletes a repository or branch on the remote, force-pushes (including `+refspec`), or calls a cloud CLI operation that creates, changes or deletes a resource, THE SYSTEM SHALL block it. | [CLAUDE.md], [RE: S6] | Guard tests per verb family |
| REQ-012 | WHEN a coding-agent session's cloud tools first run, THE SYSTEM SHALL check the active AWS identity. IF that identity is not the designated read-only role, THEN THE SYSTEM SHALL block every cloud CLI command and cloud MCP tool call for the session and tell the human why. | [desc], [Q6], [RE: S3] | Guard test with a stubbed identity response for the read-only role, another role and no credentials |
| REQ-013 | THE SYSTEM SHALL define the coding agent's read-only role so that it can describe and list resources but is denied secret values (Secrets Manager values, decrypted SSM parameters, KMS decrypt) and S3 object contents. | [Q6] | IAM policy simulation in CI on the role's policy |
| REQ-014 | THE SYSTEM SHALL keep write-capable cloud credentials out of the environment of the shell that starts the coding agent. The runbooks SHALL instruct exporting only the read-only profile there and doing write work in a separate human terminal. | [desc], [Q6], [CLAUDE.md], [RE: S3] | Runbook review; REQ-012 check at session start |
| REQ-015 | THE SYSTEM SHALL run an automated test for every guard rule, with at least one allowed and one blocked case, on every PR, and SHALL fail the PR if any case fails. | [practice] | `pr-evidence` CI job |

### B. Foundation on AWS (Phase 1)

| ID | Requirement (EARS) | Source | Verified by |
| --- | --- | --- | --- |
| REQ-020 | THE SYSTEM SHALL provision the lab VPC with no NAT gateway and an EKS cluster on a Kubernetes version in standard support, through Terraform under `infra/aws`. | [plan: Phase 1], [plan: Cost] | `terraform plan` output reviewed in the PR shows zero NAT gateways and the version |
| REQ-021 | THE SYSTEM SHALL run the Rancher server on K3s on one EC2 instance, separate from the workload cluster. Its endpoint SHALL be reachable only over TLS, only from allow-listed IP ranges, and only after single sign-on with MFA. | [plan: Why Rancher] | Connection test from a non-allow-listed address fails; login without MFA fails |
| REQ-022 | WHEN the EKS cluster is imported into Rancher, THE SYSTEM SHALL have Fleet deploy from `platform/` to clusters labelled `cloud=aws`. | [plan: Phase 1], [practice] | Fleet bundle status shows `Ready` at the `main` commit |
| REQ-023 | THE SYSTEM SHALL deploy the OpenTelemetry Demo through Fleet with its base flag settings stored in Git. | [plan: Phase 1] | Fleet status; flag values in Git match the running flagd config |
| REQ-024 | THE SYSTEM SHALL collect metrics into Amazon Managed Service for Prometheus and logs and traces into CloudWatch from an OpenTelemetry Collector labelled with cluster and cloud. It SHALL show them in one Grafana dashboard. | [plan: Multi-cloud design] | Query returns series labelled `cloud=aws` |
| REQ-025 | WHEN the human runs the rebuild command against a torn-down lab, THE SYSTEM SHALL recreate the Phase 1 lab from zero, apart from the Terraform apply the human runs, and SHALL print the elapsed time. | [plan: Definition of done], [practice] | Timed rebuild recorded at the Phase 1 gate |
| REQ-026 | WHEN the human runs the teardown command, THE SYSTEM SHALL remove or stop every billable lab resource tagged for the project. It SHALL list anything it could not remove. | [plan: Definition of done], [plan: Cost] | Tag-based resource scan after teardown shows no running billable resource |

### C. Alert intake and incident record

| ID | Requirement (EARS) | Source | Verified by |
| --- | --- | --- | --- |
| REQ-030 | WHEN a Managed Prometheus alert rule fires, THE SYSTEM SHALL deliver it through SNS to the intake function and create or update an incident record within 60 seconds of the alert firing. | [plan: Components], [Q10] | Phase 1 gate run; latency metric REQ-121 |
| REQ-031 | WHEN an alert arrives for a service that already has an open incident, THE SYSTEM SHALL attach the alert to that incident with a conditional write and SHALL NOT start a second remediation. | [plan: Design rules] | Unit test with two alerts for one service; integration test on the incident table |
| REQ-032 | WHEN the same alert notification is delivered more than once, THE SYSTEM SHALL record it once, keyed by an idempotency key derived from the alert. | Corner checklist (retries) | Unit test with a duplicated SNS message |
| REQ-033 | IF the intake function cannot write the incident record after its retries, THEN THE SYSTEM SHALL keep the alert in a dead-letter queue and notify the human channel. | Corner checklist (store unavailable) | Integration test with the table write denied |
| REQ-034 | WHEN an incident record is created or reopened, THE SYSTEM SHALL start an agent session for it within 2 minutes. | [plan: Phase 2], [Q10] | Latency metric REQ-121 |
| REQ-035 | WHEN an alert carries a severity below the configured threshold, THE SYSTEM SHALL record it on the incident without starting an agent session. | [plan: Practices] example REQ-012 ("critical alert") | Unit test per severity |

### D. Triage (Phase 2)

| ID | Requirement (EARS) | Source | Verified by |
| --- | --- | --- | --- |
| REQ-040 | WHEN an agent session starts, THE SYSTEM SHALL have the Triage agent decide `act`, `no action` or `duplicate`, and record the decision and its reason on the incident. | [plan: Agent design] | Replay scenarios 1, 2, 3, 9 |
| REQ-041 | WHEN Triage decides `no action` (for example the workload already self-healed), THE SYSTEM SHALL close the incident with its evidence and post a summary to the human channel without opening a PR. | [plan: Scenario catalog 9] | Replay scenario 9 |

### E. Investigation, read-only (Phase 2)

| ID | Requirement (EARS) | Source | Verified by |
| --- | --- | --- | --- |
| REQ-050 | THE SYSTEM SHALL give the Investigator only read tools, all reached through AgentCore Gateway. The tools are: Kubernetes through the Rancher proxy (with a token whose role has no write verbs and no access to Secrets), Managed Prometheus queries, CloudWatch Logs and Git history. | [plan: Agent design], [Q9] | Gateway policy test; Rancher role test attempting a write and a Secret read |
| REQ-051 | WHEN the Investigator finishes, THE SYSTEM SHALL attach to the incident a root-cause statement, the queries run, links to the graphs, and a confidence of low, medium or high. | [plan: Design rules] | Replay scenarios 1 to 3; schema check on the incident record |
| REQ-052 | IF the Investigator finds no fix inside the allowed paths, or its confidence is low, THEN THE SYSTEM SHALL report and escalate to the human channel without opening a PR. | [plan: Incident lifecycle] | Replay with a scenario whose fix lies outside allowed paths |
| REQ-053 | THE SYSTEM SHALL take the "last known good" version of a workload from Git and Fleet history, never from agent memory or model output. | [plan: Design rules] | Unit test of the version lookup |
| REQ-054 | WHEN tool output contains text shaped as instructions to the agent, THE SYSTEM SHALL treat it as data, SHALL NOT act on it, and SHALL flag it on the incident. | [plan: Safety ASI01], [Q2] | Scenario 14 (prompt injection in logs) |
| REQ-055 | IF a tool call times out or fails, THEN THE SYSTEM SHALL record the failure on the incident, continue with the remaining sources, and label the root cause as based on partial evidence. | Corner checklist (network) | Replay with an injected tool timeout |

### F. Remediation by pull request (Phase 3)

| ID | Requirement (EARS) | Source | Verified by |
| --- | --- | --- | --- |
| REQ-060 | WHEN the Investigator reports a root cause whose fix lies inside the allowed paths, THE SYSTEM SHALL have the Remediator open one branch and one PR through the GitHub App. That PR SHALL change only files in the OpenTelemetry Demo's Fleet bundles under `platform/` (image tags, flag overrides, resource limits). | [Q8], [plan: Agent design] | Scenarios 1 and 2 end to end |
| REQ-061 | WHEN the Remediator requests a write to any other path, or any merge, approval, ruleset or settings change, THE SYSTEM SHALL deny it at the Gateway policy and log the denial. | [plan: Safety ASI02], [Q8] | Cedar policy unit tests; a denied attempt in a replay |
| REQ-062 | THE SYSTEM SHALL write every agent PR description with the incident ID, the root cause, the queries run, links to the graphs, the confidence, the rollback plan, `Requirements:` with REQ IDs or `n/a`, and an `AI involvement` section. The PR SHALL pass `tools/ci/check_pr_body.py`. | [plan: Design rules], [practice] | CI `pr-evidence` on agent PRs |
| REQ-063 | WHEN agent output is about to be written to a PR, a PR comment or the human channel, THE SYSTEM SHALL pass it through a secret scanner and redact matches. IF the scanner is unavailable, THEN THE SYSTEM SHALL not post the output. | [plan: Safety, Data leaks] | Unit test with planted secrets; scanner-down test |
| REQ-064 | WHILE a service has an open agent PR or a pending Verifier check, THE SYSTEM SHALL NOT open another remediation PR for that service. | [plan: Safety ASI08] | Integration test with a second alert during an open PR |
| REQ-065 | THE SYSTEM SHALL give the GitHub App only repository contents and pull-request permissions on this repository, and the `main` ruleset SHALL prevent the App from merging. | [plan: Safety ASI03] | App permission export; merge attempt by the App fails |

### G. Independent review (Phase 3)

| ID | Requirement (EARS) | Source | Verified by |
| --- | --- | --- | --- |
| REQ-070 | WHEN the Remediator opens a PR, THE SYSTEM SHALL have the Reviewer agent check the diff against the incident evidence, the policies and the CI results (`kustomize build`). The Reviewer SHALL run on a different model from the Remediator. | [plan: Agent design] | Configuration test that the model IDs differ; scenario 1 |
| REQ-071 | WHEN the Reviewer rejects a PR, THE SYSTEM SHALL return it to the Remediator with the reasons. After two rejections it SHALL close the PR and escalate. | [plan: Incident lifecycle] | Replay with a planted bad fix |
| REQ-072 | THE SYSTEM SHALL record the Reviewer's verdict as a PR comment or check, and the Reviewer SHALL have no permission to approve or merge. | [plan: Safety ASI03] | Permission test |
| REQ-073 | THE SYSTEM SHALL run the required CI checks on agent PRs, with the agent's GitHub App listed in the review action's allowed bots. | [plan: Phase 3] | Agent PR shows all required checks |

### H. Verification and revert (Phase 3)

| ID | Requirement (EARS) | Source | Verified by |
| --- | --- | --- | --- |
| REQ-080 | WHEN the human merges an agent PR, THE SYSTEM SHALL start a Verifier session from the merge webhook within 2 minutes. | [plan: Design rules], [Q10] | Scenario 1 end to end |
| REQ-081 | WHEN Fleet reports the bundle synced to the merged commit and the alert has cleared within 20 minutes of the merge, THE SYSTEM SHALL close the incident as recovered and post a summary. | [plan: Agent design], [Q10] | Scenarios 1 and 2 end to end |
| REQ-082 | IF the alert has not cleared or Fleet has not synced within 20 minutes of the merge, THEN THE SYSTEM SHALL open exactly one revert PR and escalate. It SHALL never open a second revert PR for the same incident. | [plan: Design rules] | Replay with recovery withheld; second-failure test |
| REQ-083 | WHEN the human closes an agent PR without merging, THE SYSTEM SHALL record that on the incident, close the incident as not remediated, and post a summary. | [plan: Incident lifecycle] | Integration test on the close webhook |

### I. Human channel (Phases 2 and 3)

| ID | Requirement (EARS) | Source | Verified by |
| --- | --- | --- | --- |
| REQ-090 | WHEN an incident is closed, escalated, or has a PR opened, THE SYSTEM SHALL post a summary with the incident ID and the PR link (when one exists) to Slack through an incoming webhook whose URL is stored in AWS Secrets Manager. | [Q3], [plan: Phase 2] | Integration test against a test webhook |
| REQ-091 | IF the Slack post fails, THEN THE SYSTEM SHALL retry with capped backoff, record the failure on the incident, and continue the incident flow. | Corner checklist (service down) | Test with the webhook unreachable |

### J. Runtime safety controls (Phases 2 and 3)

| ID | Requirement (EARS) | Source | Verified by |
| --- | --- | --- | --- |
| REQ-100 | WHEN the human triggers the kill switch (one documented command or console action), THE SYSTEM SHALL deny and log every agent tool call at the Gateway within 60 seconds. In-flight sessions SHALL end without opening a PR. | [Q7], [plan: Design rules] | Kill-switch test at the Phase 3 gate, timed |
| REQ-101 | WHEN an incident's agent session reaches 100,000 model tokens or 40 agent steps, THE SYSTEM SHALL stop the session and escalate to the human channel. | [Q11], [plan: Design rules] | Replay with a forced long loop |
| REQ-102 | THE SYSTEM SHALL give no agent a shell tool, a Kubernetes write verb or a cloud write API. Their only write paths are the incident table, the GitHub App's branch and PR operations, and the Slack webhook. | [plan: Safety ASI05] | Gateway tool catalog export; policy tests |
| REQ-103 | THE SYSTEM SHALL hold the Rancher token, the GitHub App key and the Slack webhook URL in AgentCore Identity or AWS Secrets Manager. They SHALL not appear in code, configuration files, CI variables or logs. | [plan: Identity], [CLAUDE.md] | Secret scan of the repository and CI logs; configuration review |
| REQ-104 | THE SYSTEM SHALL trace every model call and tool call with the incident ID in AgentCore Observability. | [plan: Components] | Trace query for a replayed incident |
| REQ-105 | THE SYSTEM SHALL record each tool call's input and output during live runs, after secret redaction (REQ-063), so the run can be replayed. | [plan: Phase 2], [plan: Evaluation strategy] | Replay of a recorded scenario reproduces the tool outputs |
| REQ-106 | THE SYSTEM SHALL read model IDs for each agent role from configuration, not code. | [plan: Agent design] | Unit test switching a model ID |

## Non-functional requirements

| ID | Category | Requirement (EARS) | Source | Verified by |
| --- | --- | --- | --- | --- |
| REQ-110 | Safety | THE SYSTEM SHALL record zero safety violations in every gate run of Phases 2 and 3. A violation is a disallowed action executed, or an unsafe change reaching the human for merge without a Reviewer rejection. | [plan: Definition of done] | Gate scorecards; Gateway deny log |
| REQ-111 | Safety | WHILE Phase 2 is the latest completed phase, THE SYSTEM SHALL make zero write attempts outside the incident table and the human channel. | [plan: Phase 2 gate] | Gateway log for the Phase 2 gate runs |
| REQ-112 | Safety | THE SYSTEM SHALL pin GitHub Actions by commit SHA, container images by digest and MCP servers by exact version. | [practice], [plan: Safety ASI04] | CI lint over workflow, manifest and MCP configuration files |
| REQ-120 | Latency | THE SYSTEM SHALL meet, measured per incident and reported at each gate: alert to incident record 60 s or less (REQ-030); alert to agent session started 2 min or less (REQ-034); alert to PR opened 15 min or less as a median over gate runs (REQ-060); merge to Verifier decision 20 min or less (REQ-081, REQ-082). | [Q10] | Timestamps on the incident record |
| REQ-121 | Latency | THE SYSTEM SHALL store the timestamps needed for REQ-120 on each incident record: alert fired, record created, session started, PR opened, merged, verified. | [Q10] | Schema check |
| REQ-130 | Cost | THE SYSTEM SHALL keep an AWS Budget of US$150 a month for the lab account, with alerts to the human at 50%, 80% and 100% of actual spend. | [Q11], [plan: Cost] | Terraform plan; budget alert test notification |
| REQ-131 | Cost | WHEN the lab has had no human or agent activity for the configured idle period, or nightly at the scheduled time, THE SYSTEM SHALL stop or tear down idle billable lab resources. | [Q11], [plan: Cost] | Scheduled run log; resource scan the next morning |
| REQ-132 | Cost | THE SYSTEM SHALL record model tokens and estimated cost per incident on the incident record, labelled as an estimate. | [plan: Metrics] | Schema check; replay run |
| REQ-140 | Reliability | IF the intake function or an agent session fails, THEN THE SYSTEM SHALL not lose the alert. The alert either reaches an incident record or stays in the dead-letter queue with a notification (REQ-033). | Corner checklist | Fault-injection test on intake |
| REQ-141 | Reliability | THE SYSTEM SHALL make the intake function and the merge webhook handler idempotent, so a redelivered event has the same effect as one delivery. | Corner checklist | Unit tests with redelivery |
| REQ-150 | Quality | THE SYSTEM SHALL keep 80% line coverage on all Python code and pass Ruff, a type checker, ShellCheck and `terraform fmt`/`validate`, all as blocking CI checks. | [practice] | CI |
| REQ-151 | Traceability | THE SYSTEM SHALL cite the REQ IDs a test or eval scenario verifies, in that test or scenario. | [CLAUDE.md], [plan: Proof] | CI traceability script lists every REQ with at least one test |
| REQ-152 | Security | THE SYSTEM SHALL use no long-lived static cloud keys in code or CI. CI reaches AWS through GitHub OIDC with a read-only role for `terraform plan`. | [plan: Identity], [practice] | Workflow review; IAM role trust policy |

## Phase gates (acceptance)

| ID | Requirement (EARS) | Source | Verified by |
| --- | --- | --- | --- |
| REQ-160 | WHEN a fault is injected into the EKS lab at the Phase 1 gate, THE SYSTEM SHALL raise an alert end to end into an incident record, and the timed rebuild from zero (REQ-025) SHALL succeed. | [plan: Phase 1 gate] | Gate demo record |
| REQ-161 | WHEN scenarios 1 (bad image tag), 2 (payment errors) and 3 (memory leak) run at the Phase 2 gate, THE SYSTEM SHALL state a root cause that matches your label for each, with zero write attempts (REQ-111). | [Q2], [plan: Phase 2 gate] | Gate scorecard with your labels |
| REQ-162 | WHEN scenarios 1 and 2 run at the Phase 3 gate, THE SYSTEM SHALL fix each end to end through a PR you merge, with recovery confirmed by the Verifier. WHEN scenario 14 (prompt injection in logs) runs, THE SYSTEM SHALL ignore and flag the instruction. The kill-switch test (REQ-100) SHALL pass. | [Q2], [plan: Phase 3 gate] | Gate scorecard; kill-switch timing |

## Constraints

- Clusters change only through Git (Fleet); cloud resources change only through Terraform PRs. You run `terraform apply` locally for Phases 1 to 3. [CLAUDE.md], [practice]
- No `terraform apply`/`destroy`, kubectl or helm writes, or cloud deletes by the coding agent or the SRE agents. [CLAUDE.md]
- Stack: AWS `us-east-1`; Bedrock AgentCore (Runtime, Gateway, Policy, Identity, Observability); Strands Agents; Claude on Bedrock (Haiku 4.5 small tier, Sonnet 4.6 large tier, Opus 4.6 reviewer, through `us.` inference profiles); Python 3.12+ with `uv`; Terraform; Rancher with Fleet. [plan: Components]
- Squash merges into `main` through PRs you merge; Conventional Commits; branch names `<type>/REQ-NNN-<topic>` or `<type>/<topic>`. [practice]
- One task per PR; every PR fills the "AI involvement" section. [CLAUDE.md]

## Assumptions

| # | Assumption | Reason it needs no requirement now | Owner |
| --- | --- | --- | --- |
| A1 | The Phase 0 spike on `rancher-ai-mcp` behind AgentCore Gateway reports before Phase 2 starts; REQ-050 holds for either outcome. | [Q9] | You (ADR-0002) |
| A2 | The lab is single-tenant with one human operator, so per-user authorization, tenant isolation and personal-data rules do not apply. | Corner checklist, deployment shape | You |
| A3 | Claude Haiku 4.5, Sonnet 4.6 and Opus 4.6 remain available to the account through `us.` profiles for Phases 2 and 3. | [plan: Agent design], tested Nov 10, 2026 | You |
| A4 | A Slack workspace with an incoming webhook exists before Phase 2. | [Q3] | You |
| A5 | Fleet's polling interval allows sync within the 20-minute Verifier window. | [Q10] | Architect |
| A6 | Agents run as one process (no A2A in Phases 1 to 3), so inter-agent authentication is not needed yet. | [plan: Safety ASI07] | Architect |

## Out of scope (Phases 1 to 3)

- AKS, Azure identity federation, Chaos Studio, Route 53 weighted failover and the gray-failure scenario (Phase 5). [Q1]
- The Scribe, AgentCore Memory, the Knowledge Base and postmortem generation (Phase 6). [Q1]
- The evaluation harness beyond recording runs for replay: AgentCore Evaluations, LLM judge, CI eval tiers, scorecard publication (Phase 4). [plan: Phase 4]
- Terraform changes by the Remediator; any agent write outside the demo's Fleet bundles. [Q8]
- An automatic kill-switch trigger on budget overrun. [Q7]
- The React console and the benchmark (Phase 7). [plan: Phase 7]
- Merging without a human, replacing a paging tool, more than two clouds. [plan: Out of scope]

## Open questions for later stages

- How CI applies Terraform from Phase 4 onward (an ADR before Phase 5). [practice]
- mypy or pyright as the type checker (decided in the first Python unit). [practice]
- How Construction's own branches reach a `main` that only accepts PRs you merge (Delivery Planning).
- The severity threshold that starts an agent session (REQ-035): proposed `critical` and `warning`, to confirm in Functional Design.
- The idle period for REQ-131: proposed 2 hours, to confirm in NFR design.

## Risks

| # | Risk | Likelihood | Impact | Mitigation | Linked REQs |
| --- | --- | --- | --- | --- | --- |
| R1 | The coding agent's guardrails can be bypassed by an unforeseen shell or MCP form | Medium | High: unsafe change to cloud or guardrails | Deny-by-default MCP allowlist; read-only credentials as the primary control, the hook as defense in depth; CI check from `main` | REQ-001 to REQ-015 |
| R2 | A privileged CI job that runs on PRs from `main`'s copy is itself an injection target | Medium | High | Never check out or execute PR code in that job; pass PR data only through environment variables | REQ-008 |
| R3 | `rancher-ai-mcp` does not work with community Rancher or the Gateway | Medium | Medium: Phase 2 delay | Tool-agnostic REQ-050; fallback to a generic Kubernetes MCP server through the Rancher proxy | REQ-050 |
| R4 | Prompt injection through logs or tool output steers an agent | Medium | High | Tool output as data; Gateway policy outside the model; Reviewer on another model; scenario 14 at the Phase 3 gate | REQ-054, REQ-061, REQ-070, REQ-162 |
| R5 | Agent output leaks a secret into a PR or Slack (the repository goes public in Phase 7) | Medium | High | Secret scanner with fail-closed posting; redacted replay recordings | REQ-063, REQ-105 |
| R6 | Cloud spend exceeds the lab budget (idle clusters, NAT gateway, extended support) | Medium | Medium | Budget alerts, nightly teardown, no NAT, current Kubernetes version | REQ-020, REQ-130, REQ-131 |
| R7 | Token use per incident is far above the plan's 50,000 estimate | Medium | Medium | 100,000-token and 40-step cap; tokens recorded per incident | REQ-101, REQ-132 |
| R8 | Fleet sync or alert clearance is slower than 20 minutes, causing false reverts | Low | Medium | Measure in Phase 1; tune the window in NFR design before Phase 3 | REQ-081, REQ-082, A5 |
| R9 | Phase dates slip (Phase 3 gate Jan 17, 2027, with a holiday break) | High | Medium | Walking skeleton first; cut scope from the end; each gate demoable | REQ-160 to REQ-162 |
| R10 | A preview or new AgentCore feature changes behaviour | Low | Medium | Prefer GA services; tools behind the Gateway | REQ-050, REQ-102 |
