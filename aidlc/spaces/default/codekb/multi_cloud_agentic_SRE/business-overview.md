# Business Overview

## Purpose

Multi-Cloud Agentic SRE is a planned open-source system of AI agents that investigates production incidents on Amazon EKS and Azure AKS, proposes every fix only as a GitHub pull request that a human merges, and then verifies that the fix worked. It runs on AWS (Amazon Bedrock AgentCore, Strands Agents, Claude on Bedrock) and reaches both clusters only through Rancher. Source: `README.md`, `docs/plan.md` ("At a glance").

The project is also a demonstration of method: it is built with AWS's AI-Driven Development Lifecycle (AI-DLC) in Claude Code, and every step is meant to leave evidence in the repository (AI-DLC records, ADRs, hook audit log, PR "AI involvement" sections, rulesets, telemetry, scorecards). Source: `docs/plan.md` ("Methodology", "Proof the method was followed").

## Current state (commit 69ec4cd, 2026-11-10)

The repository is a **Phase 0 scaffold**. No product code exists. What exists is:

- the plan (`docs/plan.md`), the Phase 0 runbook (`docs/runbooks/phase-0.md`) and three diagrams;
- development guardrails for the coding agent: a Claude Code PreToolUse hook that blocks a list of destructive shell commands (`tools/claude-hooks/`), and a CI workflow that tests that hook and checks each PR description for the "AI involvement" section and requirement IDs (`.github/`, `tools/ci/`);
- two ADRs (0001 adopt AI-DLC; 0004 guard hook fails closed), both still `Proposed`;
- spike fixtures for Phase 0 (`tools/spikes/`, `tools/otel/`);
- placeholder folders (`agents/`, `console/`, `evals/`, `infra/`, `platform/`) holding one README each.

## Key business capabilities (planned)

| Capability | Description | Planned phase |
| --- | --- | --- |
| Alert intake | Managed Prometheus alert -> SNS -> Lambda opens or updates an incident record and starts an agent session | 1 (alert path), 2 (session) |
| Triage | Decide whether to act; fold duplicate alerts into an open incident | 2 |
| Read-only investigation | Root cause with evidence from metrics, logs, traces, Kubernetes state (via Rancher) and Git history | 2 |
| Remediation by PR | Smallest fix as a PR in allowed paths: manifest, flag override or Terraform variable | 3 |
| Independent review | A different model checks the diff against evidence and policy | 3 |
| Verified recovery | After a human merge, confirm Fleet synced and the alert cleared, else one revert PR and escalation | 3 |
| Postmortem and memory | Scribe writes postmortem, updates memory and knowledge base, notifies Slack | 6 |
| Evaluation | 15 scenarios scored in CI (replay, live, online) with a published scorecard | 4-5 |
| Multi-cloud | AKS joined, telemetry federated to AWS, Route 53 weighted failover, gray-failure handling | 5 |
| Console | React/Vite console with incidents, trace, PR link and cost | 7 |

## Actors

- **Human operator (the project owner)**: merges or rejects agent PRs; is the only gate to production; runs every apply, cluster write and cloud delete.
- **SRE agents (planned)**: Triage, Investigator, Remediator, Reviewer, Verifier, Scribe.
- **Coding agent (Claude Code)**: builds the system under AI-DLC, constrained by `CLAUDE.md` and the guard hook.
- **CI (GitHub Actions)**: runs the methodology checks; later the eval tiers and Terraform plans.

## Business rules visible in the repository

- Changes reach clusters only through Git (Fleet) and cloud resources only through Terraform PRs. Source: `CLAUDE.md` "Safety rules".
- The coding agent never runs `terraform apply`/`destroy`, kubectl or helm writes, or cloud deletes; a human does. Enforced in part by `tools/claude-hooks/guard-bash.sh`.
- Secrets, tokens, kubeconfigs and account IDs never go into files, commits, PRs or logs. Source: `CLAUDE.md`; reflected in `.gitignore` and in spike files that use placeholders.
- Read-only credentials by default; ask before using anything with write access. Source: `CLAUDE.md`. Not yet reflected in the Phase 0 runbook (see code-quality-assessment.md).
- Every PR fills "AI involvement" and lists requirement IDs (`REQ-NNN`) or `n/a`; CI fails otherwise. Source: `tools/ci/check_pr_body.py`.
- Out of scope for v1.0: merging to production without a human, replacing a paging tool, supporting more than two clouds. Source: `docs/plan.md`.

## Success criteria stated in the plan (input, not yet approved requirements)

- 15 incident scenarios across both clouds, scored in CI, with a published scorecard.
- Zero safety violations across all evaluation runs.
- Gray-failure scenario passes with real faults.
- Every merged PR meets the AI-DLC evidence rules.
- One command rebuilds everything from zero, one tears it down.

These come from `docs/plan.md` and, per `CLAUDE.md`, are to be questioned during Inception rather than taken as settled.
