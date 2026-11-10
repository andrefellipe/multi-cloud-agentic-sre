# Requirements Analysis Questions

Scope of this work: Inception for Phases 1 to 3 of `docs/plan.md` (Foundation on AWS, read-only agent prototype, closed-loop remediation), plus the coding-agent safety requirements you asked for. `docs/plan.md` is treated as input to question; each question below is a point the plan, the repository scan or the affirmed practices could not settle. Every question names the trade whose call it is; anyone may answer any of them.

## Q1. [Product owner] What exactly is in scope for Phases 1 to 3?

The plan puts AKS, Route 53 failover and the gray-failure scenario in Phase 5, and the Scribe (postmortems, memory, knowledge base) in Phase 6. Phase 2 still lists "summary to Slack".

A. EKS only; agents Triage, Investigator, Remediator, Reviewer and Verifier; a short incident summary posted to the human channel; no Scribe, memory, knowledge base, AKS or Route 53 (recommended: matches the plan's phase checklists and keeps each gate demoable)
B. As A, plus a minimal Scribe that writes a postmortem file to the repository via PR
C. As A, plus AKS imported into Rancher read-only, so Phase 5 starts with a working second cluster
X. Other (please specify)

[Answer]: A

## Q2. [Product owner] Which scenarios define the Phase 2 and Phase 3 gates?

The plan says Phase 2 needs "correct root cause on 3 EKS scenarios" without naming them, and Phase 3 needs bad image tag (scenario 1) and payment errors (scenario 2) fixed end to end.

A. Phase 2: bad image tag (1), payment errors (2), memory leak (3); Phase 3: 1 and 2 fixed end to end with your merge, plus prompt injection in logs (14) ignored and flagged (recommended: covers a Git fault, two flag faults and the first safety scenario before remediation goes live)
B. Phase 2: 1, 2, 3; Phase 3: 1 and 2 only, as in the plan
C. Phase 2: 1, 2, 7 (CPU throttling, a non-flag fix); Phase 3: 1 and 2
X. Other (please specify)

[Answer]: A

## Q3. [Product owner] Where should the agent post incident summaries and escalations in Phases 2 and 3?

The plan uses Slack, but nothing in the repository shows a Slack workspace or app yet.

A. Slack, through an incoming webhook stored in AWS Secrets Manager; you have or will create a workspace (recommended: matches the plan and the later console)
B. A GitHub issue per incident in this repository (no extra service; the PR links back to it)
C. Email through Amazon SNS
X. Other (please specify)

[Answer]: A

## Q4. [Security engineer] How should the coding agent be prevented from changing its own guardrails, tool configuration and CI gates?

Protected paths: `.mcp.json`, `.claude/settings.json`, `.github/`, `tools/claude-hooks/`, `tools/ci/` (and the hook audit log `docs/evidence/hook-audit.jsonl`). Today edits are pre-allowed everywhere, and CI runs the PR's own copy of its checks. Note: a code-owner review rule would block you, because GitHub does not let you approve your own PR.

A. Two layers: (1) local hooks deny the agent's Edit/Write and any shell command that writes to a protected path; (2) a required CI check, run from `main`'s copy of the workflow, fails any PR that touches a protected path unless you add a `guardrail-change` label yourself (recommended: works solo, and the PR cannot weaken the check that judges it)
B. Local hooks only (layer 1 of A)
C. As A, plus protected files made read-only on disk, which the hook also refuses to change back
X. Other (please specify)

[Answer]: A

## Q5. [Security engineer] How should the guardrails treat the coding agent's MCP tool calls?

Today only shell commands are checked. The `aws-mcp` script runner can call any AWS API with the shell's credentials, and the serverless server has deploy tools.

A. Deny by default: an explicit allowlist of read-only MCP tools; every other MCP tool is blocked and logged like a blocked shell command (recommended: new or renamed write tools are blocked without anyone noticing them first)
B. Allow by default with a denylist of known write tools (deploy, run script, create, delete)
C. Allowlist, but the AWS script runner is allowed when the session uses read-only credentials
X. Other (please specify)

[Answer]: A

## Q6. [Security engineer] What does "read-only cloud credentials by default" mean for the coding agent?

The Phase 0 runbook currently exports an `AdministratorAccess` profile into the shell that starts Claude Code.

A. A dedicated AWS profile on a custom read-only role that also denies reading secret values and S3 object contents; the session refuses to start its cloud tools if the active identity is not that role; write work happens only in your own terminal (recommended: read-only, and no data or secrets the agent could leak)
B. The AWS-managed `ReadOnlyAccess` policy
C. The AWS-managed `ViewOnlyAccess` policy (metadata only, no data reads)
X. Other (please specify)

[Answer]: A

## Q7. [Security engineer] How fast must the kill switch stop the SRE agents, and who can pull it?

The plan's kill switch is a Gateway policy that denies every tool, tested from Phase 3.

A. You flip it with one documented command or console action; within 60 seconds every agent tool call is denied and logged, and in-flight sessions end without opening a PR (recommended: fast enough for a lab, testable in CI)
B. Within 5 minutes, triggered by you only
C. As A, plus an automatic trigger when the per-incident token budget or the monthly AWS budget is exceeded
X. Other (please specify)

[Answer]: A

## Q8. [Architect] Where may the Remediator open pull requests in Phase 3?

The plan allows "a manifest, a flag override or a Terraform variable"; Terraform weight changes are Phase 5 work, and Phases 1 to 3 have you applying Terraform by hand.

A. Only the Fleet bundles for the OpenTelemetry Demo under `platform/` (image tags, flag overrides, resource limits); no Terraform, no other path (recommended: covers the Phase 3 gate scenarios with the smallest blast radius)
B. As A, plus one Terraform variables file under `infra/aws/`
C. Anything under `platform/`
X. Other (please specify)

[Answer]: A

## Q9. [Architect] Should requirements name `rancher-ai-mcp`, given the Phase 0 spike has not reported yet?

A. No: require "read-only Kubernetes tools reached only through the Rancher proxy, with a token that cannot read Secrets"; the spike's ADR picks `rancher-ai-mcp` or the generic fallback (recommended: requirements stay valid whichever way the spike goes)
B. Yes, name `rancher-ai-mcp`; revise requirements if the spike fails
X. Other (please specify)

[Answer]: A

## Q10. [Operations engineer] What latency targets should the incident path meet?

The plan reports time to proposed fix but sets no targets.

A. Alert to incident record 60 s or less; alert to agent session started 2 min or less; alert to PR opened 15 min or less (median); after merge, Verifier decides recovered or revert within 20 min (recommended: realistic for Fleet's sync interval and a lab)
B. Tighter: 30 s / 1 min / 10 min / 15 min
C. Measure only in Phases 1 to 3; set targets after the Phase 4 baseline
X. Other (please specify)

[Answer]: A

## Q11. [Operations engineer] What cost limits should hold during Phases 1 to 3?

The plan estimates US$210 to 510 a month at full v1.0 scope; Phases 1 to 3 run EKS, Rancher and the agents only, with far fewer eval runs.

A. AWS Budget of US$150 a month with alerts at 50%, 80% and 100%; per-incident cap of 100,000 tokens and 40 agent steps, after which the agent stops and escalates; scheduled teardown of idle lab resources nightly (recommended: leaves headroom under the plan's estimate)
B. US$300 a month budget; 200,000 tokens per incident
C. US$100 a month budget; 50,000 tokens per incident (the plan's planning figure)
X. Other (please specify)

[Answer]: A
