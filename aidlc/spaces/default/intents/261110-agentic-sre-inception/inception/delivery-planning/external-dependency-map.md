# External Dependency Map

These are the things outside the build that a Bolt needs before it can finish. A **Bolt** is one build pass over a piece of the work that ends in something that runs, and the Bolts are listed in `bolt-plan.md`. You confirmed that none of these exist yet (`delivery-planning-questions.md` Q5). Each row says which Bolt it blocks.

| # | Dependency | Owner | Lead time (estimate) | Blocks | If it slips |
|---|---|---|---|---|---|
| D1 | Read-only AWS profile in the shell that runs Claude Code (interim US1.4) | You | Under 1 hour | B1 start | Do not start B1; this is the Q1 safety condition |
| D2 | Slack workspace and an incoming webhook, with its URL stored in AWS Secrets Manager (ADR-006) | You | Under 1 hour | B1 PR 3 (dead-letter notice) | Leave the dead-letter alarm in CloudWatch only; the Slack post follows when it exists |
| D3 | Bedrock model access for Haiku 4.5, Sonnet 4.6 and Opus 4.6 through `us.` profiles. **Done:** you confirmed access on 2026-11-10 | You (AWS console) | Done | B1 PR 4 (session start), B5 | No longer blocking |
| D4 | Phase 0 spike: `rancher-ai-mcp` behind AgentCore Gateway, recorded as ADR-0002, or the generic Kubernetes MCP fallback chosen | You with the coding agent (spike) | About 1 day; Phase 0 gate Nov 29 | B1 PR 4 (`k8s_read` target) | Use the generic Kubernetes MCP server through the Rancher proxy (C9 is tool-agnostic) |
| D5 | The SRE agent's GitHub App: created, installed on this repository, contents and pull-request permissions only, not able to merge under the `main` ruleset; key held in AgentCore Identity | You | Under 1 hour | B6 | B6 builds and tests in replay; live PRs wait |
| D6 | A separate GitHub identity for the coding agent, distinct from yours, so CI can tell your `guardrail-change` label from the agent's (open question on contract C11) | You | Under 1 hour | B2 (label check) | The label check can only verify the label's presence, not who added it; accepted risk until resolved |
| D7 | GitHub webhook secret for merge and close events, stored in Secrets Manager | You | Minutes | B7 | B7 waits |
| D8 | AWS Budget alert email or SNS subscription confirmed | You | Minutes | B3 | Budget exists but alerts are unseen |

D1, D2 and D4 still gate the walking skeleton; D3 is in place. D5 to D8 can wait until their Bolt.
