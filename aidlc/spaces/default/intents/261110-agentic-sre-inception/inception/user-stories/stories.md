# User Stories: Phases 1 to 3

Personas are defined in `personas.md`. The requirements are in `inception/requirements-analysis/requirements.md`. Stories are grouped by phase and then by step of the incident lifecycle, with the coding-agent guardrails first (Q2). Every story is **Must Have** for Phases 1 to 3 (Q3). Each acceptance criterion names the REQ IDs it demonstrates. The team practice is test-after, with acceptance criteria that cite REQ IDs (`inception/practices-discovery/team-practices.md`).

Context for the existing components comes from `aidlc/spaces/default/codekb/multi_cloud_agentic_SRE/business-overview.md` and `aidlc/spaces/default/codekb/multi_cloud_agentic_SRE/component-inventory.md`.

## Story map

| Group | Stories | Phase | Walking skeleton |
| --- | --- | --- | --- |
| 1. Coding-agent guardrails | US1.1 to US1.5 | Now, before Phase 1 code | No |
| 2. Foundation and alert intake | US2.1 to US2.7 | 1 | US2.1 to US2.3, US2.6 |
| 3. Read-only agent | US3.1 to US3.9 | 2 | US3.1 |
| 4. Closed-loop remediation | US4.1 to US4.9 | 3 | No |
| 5. Evidence for the peer review | US5.1, US5.2 | 1 to 3 | No |

The walking skeleton is the thin slice the team practices require first: an alert reaches the intake (US2.6), opens an agent session (US3.1), and the agent makes one read through Rancher (US3.1).

---

## Group 1. Coding-agent guardrails

### US1.1 Protected files stay out of the coding agent's reach
**As** Olivia (P1), **I want** the coding agent to be unable to edit the files that hold its own guardrails, tool configuration and CI gates, **so that** a confused or manipulated agent cannot loosen the rules that bound it.
- **Priority:** Must. **Depends on:** none.
- AC1.1.1: Given a coding-agent session, when the agent calls a file-editing tool on `.mcp.json`, `.claude/settings.json`, any file under `.github/`, `tools/claude-hooks/`, `tools/ci/`, or `docs/evidence/hook-audit.jsonl`, then the call is blocked before it runs and the agent is told which rule blocked it. (REQ-001, REQ-004)
- AC1.1.2: Given a coding-agent session, when the agent runs a shell command that writes, moves, deletes or changes permissions on one of those paths, then the command is blocked. (REQ-002)
- AC1.1.3: Given a guard hook that crashes, times out or receives malformed input, when the agent makes any tool call, then the call is blocked. (REQ-005)
- AC1.1.4: Given any block, when Olivia opens `docs/evidence/hook-audit.jsonl`, then she finds one line with the timestamp, tool type and rule name, and no command arguments or file content. (REQ-006)
- AC1.1.5: Given a PR, when CI runs, then every guard rule's allowed and blocked test cases run and the PR fails if any case fails. (REQ-015)
- **INVEST:** independent of cloud work; small (hook rules plus tests); testable by the guard test suite.

### US1.2 MCP tools are blocked unless allowlisted
**As** Olivia (P1), **I want** the coding agent's MCP tool calls to be denied unless they are on a read-only allowlist, **so that** an MCP server cannot become a back door around the shell guardrails.
- **Priority:** Must. **Depends on:** US1.1 (the allowlist lives in a protected path).
- AC1.2.1: Given the read-only MCP allowlist, when the agent calls a listed read tool, then the call proceeds. (REQ-003)
- AC1.2.2: Given the allowlist, when the agent calls the AWS script runner, a serverless deploy tool, or a tool that is not on the list, then the call is blocked and logged with server and tool name. (REQ-003, REQ-006)
- AC1.2.3: Given the agent tries to add a tool to the allowlist, when it edits the allowlist file, then the edit is blocked as a protected path. (REQ-004)

### US1.3 Guardrail changes only through a PR Olivia labels, checked from `main`
**As** Olivia (P1), **I want** a PR that touches a protected path to fail CI unless I have labelled it `guardrail-change`, with the check running from `main`'s copy, **so that** a PR cannot weaken the check that judges it, and guardrail changes happen only when I mean them to.
- **Priority:** Must. **Depends on:** US1.1.
- AC1.3.1: Given a PR that changes a protected path without the `guardrail-change` label, when CI runs, then the required check fails. (REQ-007)
- AC1.3.2: Given the same PR after the repository owner adds the label, when CI runs, then the protected-path check passes. (REQ-007)
- AC1.3.3: Given a PR that also edits the check script, when CI runs, then the check runs from `main`'s copy and the PR's copy is never executed in that job. (REQ-008)
- AC1.3.4: Given a PR whose `.claude/settings.json` drops the shell, file-edit or MCP matcher, or the fail-closed setting, when CI runs, then the required check fails. (REQ-009)

### US1.4 The coding agent works with read-only cloud credentials
**As** Olivia (P1), **I want** the coding agent's shell to carry only a read-only AWS identity, and its cloud tools to refuse to run under any other identity, **so that** the agent cannot change or read secrets from my cloud account even if every other guard fails.
- **Priority:** Must. **Depends on:** none.
- AC1.4.1: Given a session whose AWS identity is the designated read-only role, when the agent runs a cloud CLI command or a cloud MCP tool, then it proceeds. (REQ-012)
- AC1.4.2: Given a session whose identity is any other role, or has no credentials, when the agent first uses a cloud tool, then every cloud command and cloud MCP call in that session is blocked and Olivia is told why. (REQ-012)
- AC1.4.3: Given the read-only role's policy, when it is simulated in CI, then list and describe actions are allowed and secret values, decrypted SSM parameters, KMS decrypt and S3 object reads are denied. (REQ-013)
- AC1.4.4: Given the Phase 0 and Phase 1 runbooks, when Olivia follows them, then only the read-only profile is exported in the shell that starts Claude Code, and write work is done in a separate terminal. (REQ-014)

### US1.5 Destructive commands are blocked however they are written
**As** Olivia (P1), **I want** destructive commands to be blocked even when flags come before the verb or the command is chained, **so that** a small change in spelling does not get past the guard.
- **Priority:** Must. **Depends on:** US1.1.
- AC1.5.1: Given `kubectl -n x delete`, `terraform -chdir=dir apply` or `helm -n x uninstall`, when the agent runs it, then it is blocked. (REQ-010)
- AC1.5.2: Given a `kubectl` command with `--dry-run` chained to a blocked command, when the agent runs it, then the blocked segment is still blocked. (REQ-010)
- AC1.5.3: Given `gh pr merge`, a remote branch or repository delete, a `+refspec` force push, or a cloud CLI create, update or delete, when the agent runs it, then it is blocked. (REQ-011)

---

## Group 2. Phase 1: foundation and alert intake

### US2.1 Provision the lab from a reviewed plan
**As** Olivia (P1), **I want** the VPC and EKS cluster defined in Terraform and proposed as a plan in a PR, **so that** I apply only what I have reviewed, with no NAT gateway and no extended-support charges.
- **Priority:** Must. **Depends on:** US1.4.
- AC2.1.1: Given the Terraform PR, when CI runs `terraform plan` with a read-only role, then the plan shows zero NAT gateways and a Kubernetes version in standard support. (REQ-020, REQ-152)
- AC2.1.2: Given the PR, when Olivia merges it and runs `terraform apply` herself, then the VPC and EKS cluster exist. Neither the coding agent nor CI applied anything. (REQ-020)

### US2.2 Reach both clusters through a hardened Rancher
**As** Olivia (P1), **I want** Rancher on its own K3s instance behind TLS, an IP allow-list and SSO with MFA, with Fleet deploying from `platform/`, **so that** one controlled door manages the cluster, and Git is the only way changes reach it.
- **Priority:** Must. **Depends on:** US2.1.
- AC2.2.1: Given the Rancher endpoint, when a connection comes from outside the allow-list, or a login lacks MFA, then it is refused. (REQ-021)
- AC2.2.2: Given the EKS cluster imported into Rancher with `cloud=aws`, when a commit lands on `main` under `platform/`, then Fleet reports the bundle `Ready` at that commit. (REQ-022)

### US2.3 Run the demo app and see its telemetry
**As** Olivia (P1), **I want** the OpenTelemetry Demo deployed by Fleet, with its flags in Git and its telemetry in Managed Prometheus, CloudWatch and Grafana, **so that** there is a realistic workload to break and observe.
- **Priority:** Must. **Depends on:** US2.2.
- AC2.3.1: Given the demo bundle, when Fleet syncs, then the running flag values match the base settings in Git. (REQ-023)
- AC2.3.2: Given the Collector, when Olivia queries Managed Prometheus, then she sees series labelled with cluster and `cloud=aws`, and logs and traces appear in CloudWatch and one Grafana dashboard. (REQ-024)

### US2.4 Rebuild and tear down the lab with one command each
**As** Olivia (P1), **I want** one command to rebuild the lab and one to tear it down, plus a nightly teardown of idle resources, **so that** I pay only for the hours I work and can start fresh any time.
- **Priority:** Must. **Depends on:** US2.1 to US2.3.
- AC2.4.1: Given a torn-down lab, when Olivia runs the rebuild command (and the Terraform apply it asks her to run), then the Phase 1 lab is back and the elapsed time is printed. (REQ-025)
- AC2.4.2: Given a running lab, when Olivia runs the teardown command, then no billable tagged resource is left running, and anything it could not remove is listed. (REQ-026)
- AC2.4.3: Given idle lab resources at the scheduled time, when the nightly job runs, then they are stopped or torn down, and the run is logged. (REQ-131)

### US2.5 Know early when spend is rising
**As** Olivia (P1), **I want** an AWS Budget of US$150 a month that alerts me at 50%, 80% and 100%, **so that** a forgotten cluster or a runaway agent cannot surprise me with a bill.
- **Priority:** Must. **Depends on:** US2.1.
- AC2.5.1: Given the budget, when actual spend crosses 50%, 80% or 100% of US$150, then Olivia receives an alert for each threshold. (REQ-130)

### US2.6 Turn an alert into exactly one incident record
**As** Sam (P2), **I want** each firing alert to create or update exactly one incident record within a minute, **so that** duplicates and redeliveries never turn into two incidents or two fixes.
- **Priority:** Must. **Depends on:** US2.3.
- AC2.6.1: Given an alert rule fires, when it reaches the intake through SNS, then an incident record exists within 60 seconds, holding the alert-fired and record-created timestamps. (REQ-030, REQ-121)
- AC2.6.2: Given an open incident for a service, when a second alert for that service arrives, then it is attached to the same incident, and no second remediation starts. (REQ-031)
- AC2.6.3: Given the same SNS message delivered twice, when the intake runs twice, then the incident shows one alert. (REQ-032, REQ-141)
- AC2.6.4: Given the incident table rejects writes, when the intake exhausts its retries, then the alert sits in the dead-letter queue and Sam is notified. No alert is lost. (REQ-033, REQ-140)
- AC2.6.5: Given an alert below the session threshold, when it arrives, then it is recorded on the incident and no agent session starts. (REQ-035)

### US2.7 Demonstrate the Phase 1 gate
**As** Priya (P3), **I want** a recorded demo in which an injected fault raises an alert into an incident record, and a timed rebuild from zero succeeds, **so that** I can sign off Phase 1 from evidence.
- **Priority:** Must. **Depends on:** US2.4, US2.6.
- AC2.7.1: Given the Phase 1 lab, when a fault is injected, then the gate record shows the alert, the incident record and its timestamps. (REQ-160)
- AC2.7.2: Given the gate, when the rebuild runs from zero, then its elapsed time is in the gate record. (REQ-160, REQ-025)

---

## Group 3. Phase 2: read-only agent

### US3.1 An incident opens an agent session that reads through Rancher (walking skeleton)
**As** Olivia (P1), **I want** each new incident to start an agent session within two minutes, with the agent able to read the cluster only through Rancher with a token that has no write verbs and no access to Secrets, **so that** I prove the riskiest plumbing early and the agent cannot change the cluster whatever a prompt says.
- **Priority:** Must. **Depends on:** US2.2, US2.6.
- AC3.1.1: Given a new incident record, when the intake hands it over, then an agent session starts within 2 minutes and the session-start time is recorded. (REQ-034, REQ-121)
- AC3.1.2: Given the agent session, when it lists pods in the demo namespace, then the read succeeds through the Rancher proxy via AgentCore Gateway. (REQ-050)
- AC3.1.3: Given the same token, when a write verb or a Secret read is attempted, then Rancher denies it. (REQ-050, REQ-102)

### US3.2 Triage decides whether to act
**As** Sam (P2), **I want** the agent to decide `act`, `no action` or `duplicate` and give its reason, **so that** I only hear about incidents that need attention.
- **Priority:** Must. **Depends on:** US3.1.
- AC3.2.1: Given a session for a new fault, when Triage runs, then the incident records `act` with a reason. (REQ-040)
- AC3.2.2: Given a pod that already self-healed (scenario 9), when Triage runs, then the incident closes as `no action`, with evidence, a Slack summary and no PR. (REQ-041)

### US3.3 Investigation attaches its evidence
**As** Sam (P2), **I want** the root cause posted with the queries run, graph links and a confidence level, **so that** I can check the agent's reasoning instead of trusting it.
- **Priority:** Must. **Depends on:** US3.2.
- AC3.3.1: Given scenario 1, 2 or 3 in replay, when the Investigator finishes, then the incident holds a root-cause statement, the queries, graph links and a low, medium or high confidence. (REQ-051)
- AC3.3.2: Given a bad image tag, when the Investigator names the last known good version, then that version comes from Git and Fleet history. (REQ-053)
- AC3.3.3: Given a tool call that times out, when the Investigator continues, then the failure is recorded and the root cause is labelled as based on partial evidence. (REQ-055)

### US3.4 No safe fix means a report, not a guess
**As** Sam (P2), **I want** to be escalated with the findings when the agent finds no fix within its allowed paths, or has low confidence, **so that** a person decides instead of the agent guessing.
- **Priority:** Must. **Depends on:** US3.3.
- AC3.4.1: Given a root cause whose fix lies outside the allowed paths, when the Investigator finishes, then Sam gets an escalation in Slack and no PR is opened. (REQ-052)
- AC3.4.2: Given low confidence, when the Investigator finishes, then Sam is escalated and no PR is opened. (REQ-052)

### US3.5 Instructions hidden in logs are flagged, not followed
**As** Olivia (P1), **I want** text in tool output that tries to instruct the agent to be ignored and flagged, **so that** an attacker who can write a log line cannot steer the agent.
- **Priority:** Must. **Depends on:** US3.3.
- AC3.5.1: Given a log line containing instructions (scenario 14), when the Investigator reads it, then the agent does not act on it and the incident carries a prompt-injection flag. (REQ-054)

### US3.6 Incident summaries arrive in Slack
**As** Sam (P2), **I want** a Slack message for every closed or escalated incident and every agent PR, with its ID and link, **so that** I can follow incidents without opening the lab.
- **Priority:** Must. **Depends on:** US3.2.
- AC3.6.1: Given an incident is closed, escalated or has a PR opened, when that happens, then a Slack summary with the incident ID (and PR link, if any) is posted through the webhook stored in Secrets Manager. (REQ-090)
- AC3.6.2: Given Slack is unreachable, when a summary is due, then it is retried with backoff, the failure is recorded on the incident, and the incident flow carries on. (REQ-091)

### US3.7 Every agent run can be traced and replayed
**As** Olivia (P1), **I want** every model and tool call traced with the incident ID, tool calls recorded for replay after redaction, and model IDs in configuration, **so that** I can explain any run and compare prompt or model changes on identical inputs.
- **Priority:** Must. **Depends on:** US3.3.
- AC3.7.1: Given a replayed incident, when Olivia queries AgentCore Observability by incident ID, then she sees every model and tool call. (REQ-104)
- AC3.7.2: Given a live run, when it completes, then its tool inputs and outputs are stored redacted, and a replay reproduces them. (REQ-105)
- AC3.7.3: Given a changed model ID in configuration, when the next session starts, then that role uses the new model, with no code change. (REQ-106)

### US3.8 A runaway incident stops itself
**As** Olivia (P1), **I want** a session to stop and escalate at 100,000 tokens or 40 steps, with tokens and estimated cost recorded per incident, **so that** one stuck incident cannot burn the budget.
- **Priority:** Must. **Depends on:** US3.1.
- AC3.8.1: Given a session forced into a loop, when it reaches 100,000 tokens or 40 steps, then it stops and Sam is escalated. (REQ-101)
- AC3.8.2: Given any finished session, when Olivia reads the incident, then she sees tokens used and the estimated cost, labelled as an estimate. (REQ-132)

### US3.9 Demonstrate the Phase 2 gate
**As** Priya (P3), **I want** scenarios 1, 2 and 3 run with root causes matching Olivia's labels and the Gateway log showing zero write attempts, **so that** I can sign off the read-only agent.
- **Priority:** Must. **Depends on:** US3.3 to US3.8.
- AC3.9.1: Given scenarios 1, 2 and 3, when they run at the gate, then each root cause matches Olivia's label in the gate scorecard. (REQ-161)
- AC3.9.2: Given the gate runs, when Priya reads the Gateway log, then it shows no write attempt outside the incident table and Slack. (REQ-111)

---

## Group 4. Phase 3: closed-loop remediation

### US4.1 The agent proposes its fix as a PR in allowed paths only
**As** Olivia (P1), **I want** the Remediator to open one PR that changes only the demo's Fleet bundles under `platform/`, through a GitHub App that cannot merge, **so that** every agent change is small, reviewable, and waits for me.
- **Priority:** Must. **Depends on:** US3.3.
- AC4.1.1: Given scenario 1 or 2 with a root cause inside allowed paths, when the Remediator runs, then exactly one branch and one PR exist, touching only the demo's Fleet bundles. (REQ-060)
- AC4.1.2: Given the Remediator requests a write elsewhere, or a merge, approval, ruleset or settings change, when the Gateway evaluates it, then it is denied and logged. (REQ-061, REQ-102)
- AC4.1.3: Given the agent PR, when CI runs, then the description holds the incident ID, root cause, queries, graph links, confidence, rollback plan, `Requirements:` and `AI involvement`, and `check_pr_body.py` passes. (REQ-062)
- AC4.1.4: Given the GitHub App, when it tries to merge its own PR, then the `main` ruleset refuses. Its permissions are limited to contents and PRs on this repository. (REQ-065)

### US4.2 No secret leaks through agent output
**As** Olivia (P1), **I want** agent output scanned and redacted before it reaches a PR or Slack, and all agent credentials held outside code, **so that** nothing secret ends up in a repository that goes public in Phase 7.
- **Priority:** Must. **Depends on:** US4.1, US3.6.
- AC4.2.1: Given output containing a planted secret, when it is about to be posted, then the secret is redacted. (REQ-063)
- AC4.2.2: Given the secret scanner is unavailable, when output is due, then nothing is posted. (REQ-063)
- AC4.2.3: Given the repository and CI logs, when a secret scan runs, then no Rancher token, GitHub App key or Slack webhook URL is found. These live only in AgentCore Identity or Secrets Manager. (REQ-103)

### US4.3 One fix at a time per service
**As** Sam (P2), **I want** no second remediation PR for a service while one is open or being verified, **so that** fixes do not pile on top of each other.
- **Priority:** Must. **Depends on:** US4.1.
- AC4.3.1: Given an open agent PR for a service, when a new alert for that service leads to a fix, then no second PR is opened, and the alert joins the open incident. (REQ-064)

### US4.4 A different model reviews every agent PR
**As** Olivia (P1), **I want** a Reviewer on a different model to check each agent PR against the evidence, the policies and the CI results, **so that** I see fixes that a second, independent check has already questioned.
- **Priority:** Must. **Depends on:** US4.1.
- AC4.4.1: Given an agent PR, when the Reviewer runs, then its verdict appears as a PR comment or check, and configuration shows that its model differs from the Remediator's. (REQ-070, REQ-072)
- AC4.4.2: Given a planted bad fix, when the Reviewer rejects it twice, then the PR is closed and Sam is escalated. (REQ-071)
- AC4.4.3: Given the Reviewer, when it tries to approve or merge, then it is not permitted. (REQ-072)
- AC4.4.4: Given an agent PR, when CI runs, then every required check runs on it, because the App is listed in the review action's allowed bots. (REQ-073)

### US4.5 Recovery is confirmed after the merge
**As** Sam (P2), **I want** a Verifier to check that Fleet synced and the alert cleared after Olivia merges, **so that** "fixed" means observed recovery, not just a merged PR.
- **Priority:** Must. **Depends on:** US4.4.
- AC4.5.1: Given Olivia merges an agent PR, when the merge webhook fires, then a Verifier session starts within 2 minutes. (REQ-080)
- AC4.5.2: Given Fleet syncs to the merged commit and the alert clears within 20 minutes, when the Verifier checks, then the incident closes as recovered with a Slack summary, and the merged and verified timestamps are recorded. (REQ-081, REQ-121)

### US4.6 One revert, then a human
**As** Sam (P2), **I want** exactly one revert PR when recovery fails, followed by an escalation, **so that** the system never loops on its own fixes.
- **Priority:** Must. **Depends on:** US4.5.
- AC4.6.1: Given the alert has not cleared 20 minutes after the merge, when the Verifier decides, then one revert PR is opened and Sam is escalated. (REQ-082)
- AC4.6.2: Given the revert is merged and recovery still fails, when the Verifier checks again, then no second revert PR is opened. (REQ-082)

### US4.7 A closed PR is a recorded decision
**As** Olivia (P1), **I want** the incident to record that I closed an agent PR without merging, **so that** my rejection is part of the incident history.
- **Priority:** Must. **Depends on:** US4.1.
- AC4.7.1: Given Olivia closes an agent PR unmerged, when the close webhook fires, then the incident closes as not remediated and a summary is posted. (REQ-083)

### US4.8 Stop every agent within a minute
**As** Olivia (P1), **I want** one documented action that makes the Gateway deny every agent tool call within 60 seconds, **so that** I can halt the system immediately if anything looks wrong.
- **Priority:** Must. **Depends on:** US4.1.
- AC4.8.1: Given running sessions, when Olivia triggers the kill switch, then every agent tool call is denied and logged within 60 seconds (timed at the gate). (REQ-100)
- AC4.8.2: Given an in-flight session at that moment, when the switch takes effect, then the session ends without opening a PR. (REQ-100)

### US4.9 Demonstrate the Phase 3 gate
**As** Priya (P3), **I want** scenarios 1 and 2 fixed end to end through PRs Olivia merged, scenario 14 flagged, the kill switch timed, the latency targets met and zero safety violations recorded, **so that** I can sign off closed-loop remediation.
- **Priority:** Must. **Depends on:** US4.1 to US4.8.
- AC4.9.1: Given scenarios 1 and 2, when they run at the gate, then each ends with a merged agent PR and a Verifier-confirmed recovery. (REQ-162)
- AC4.9.2: Given scenario 14 and the kill-switch test, when they run, then the instruction is ignored and flagged, and the switch takes effect within 60 seconds. (REQ-162, REQ-100)
- AC4.9.3: Given the gate runs, when Priya reads the incident timestamps, then the medians meet: alert to record 60 s, to session 2 min, to PR 15 min, merge to verdict 20 min. (REQ-120)
- AC4.9.4: Given the gate runs, when Priya checks the Gateway deny log and the scorecard, then no disallowed action executed and no unsafe change reached Olivia without a Reviewer rejection. (REQ-110)

---

## Group 5. Evidence for the peer review

### US5.1 Trace every requirement to its tests
**As** Priya (P3), **I want** every REQ ID cited by at least one test or eval scenario, with a CI report that lists them, **so that** I can see that every requirement was built and tested without reading the code.
- **Priority:** Must. **Depends on:** none (grows with each phase).
- AC5.1.1: Given the repository at a phase gate, when the CI traceability script runs, then it lists each REQ ID in scope with at least one test or scenario that cites it, and fails if any is missing. (REQ-151)

### US5.2 Quality and supply-chain bars are enforced, not claimed
**As** Priya (P3), **I want** CI to enforce the coverage floor, the linters, pinning by SHA and digest, and OIDC-only cloud access, **so that** the evidence pack shows enforcement rather than intent.
- **Priority:** Must. **Depends on:** US1.3.
- AC5.2.1: Given a PR with Python code, when CI runs, then it fails below 80% line coverage, or on any Ruff, type-check, ShellCheck or `terraform fmt`/`validate` error. (REQ-150)
- AC5.2.2: Given a workflow, manifest or MCP configuration that uses an unpinned action, image or server version, when CI runs, then it fails. (REQ-112)
- AC5.2.3: Given the CI workflows, when Priya inspects them, then AWS is reached only through GitHub OIDC, with a read-only role for `terraform plan`, and no static keys. (REQ-152)

---

## Won't have (Phases 1 to 3)

Carried from the out-of-scope list in `requirements.md`:
- AKS and the gray-failure scenario.
- The Scribe, memory and the knowledge base.
- The evaluation harness beyond replay recording.
- Terraform remediation.
- An automatic kill-switch trigger.
- The console.
