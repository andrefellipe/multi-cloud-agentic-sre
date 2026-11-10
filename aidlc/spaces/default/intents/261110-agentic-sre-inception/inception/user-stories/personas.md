# Personas

Three personas, chosen in `user-stories-questions.md` Q1. Their roles and goals come from the approved requirements (`inception/requirements-analysis/requirements.md`), the actors in `aidlc/spaces/default/codekb/multi_cloud_agentic_SRE/business-overview.md` and `docs/plan.md` ("Working solo"). The SRE agents and the coding agent are not personas: their behaviour is told from the side of the person who relies on it.

## P1. Olivia, the lab operator (primary)

- **Role.** Owns the repository and the AWS lab. She is the only person who merges PRs, runs `terraform apply`, labels guardrail changes, pulls the kill switch and signs off phase gates.
- **Goals.**
  - Ship Phases 1 to 3 on schedule, with each gate demoable.
  - Trust that neither the coding agent nor the SRE agents can change anything she has not merged.
  - Keep the lab within budget.
- **Pain points.**
  - Today the coding agent's guardrails cover shell commands only, and its shell runs with admin credentials.
  - Every hour spent on cloud plumbing is an hour not spent on the agents.
  - She works solo, about 15 to 20 hours a week.
- **Context.** Works from a laptop with Claude Code under AI-DLC. A separate human terminal holds write credentials.
- **Tech comfort.** High.
- **Frequency.** Daily while building; per incident while the agents run.

## P2. Sam, the on-call responder

- **Role.** Receives the incident summaries and escalations in Slack. Decides whether to act on an escalation and reads the agent's PR before Olivia merges it. In Phases 1 to 3 Olivia wears this hat herself. The persona exists so that summaries and escalations are written for someone who was not watching the run.
- **Goals.**
  - Understand an incident from one Slack message: what fired, what the agent concluded, how confident it is, and what (if anything) needs a human.
  - Never be paged twice for the same incident.
- **Pain points.**
  - Alert noise.
  - Summaries without evidence links.
  - Agents that "fix" things silently.
- **Context.** Reads Slack on phone or laptop. May not have the lab open.
- **Tech comfort.** Medium to high.
- **Frequency.** Per incident.

## P3. Priya, the phase-gate peer reviewer

- **Role.** An invited peer who spends about 30 minutes at each phase gate checking the evidence pack, as suggested in `docs/plan.md`. She has read access to the repository and the gate records only.
- **Goals.**
  - Confirm, from records rather than claims, that the gate criteria were met.
  - Confirm that every requirement was built and tested, and that no safety rule was broken.
- **Pain points.**
  - Evidence spread across tools.
  - Numbers with no method behind them.
  - No way to tell what the AI wrote and what the human changed.
- **Context.** Remote, async, at the gate dates.
- **Tech comfort.** High.
- **Frequency.** Once per phase gate.

## Relationships and priority

| Persona | Priority | Relationship |
| --- | --- | --- |
| P1 Olivia, lab operator | Primary | Builds and runs everything; acts on P2's escalations; prepares P3's evidence |
| P2 Sam, on-call responder | Secondary | Consumes agent output; hands decisions to P1 |
| P3 Priya, peer reviewer | Secondary | Audits P1's gate evidence |
