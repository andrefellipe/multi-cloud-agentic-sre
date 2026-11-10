# Units Generation Questions

These questions settle how the 16 components in `inception/domain-design/components.md` are grouped into units of work: pieces that can each be built, tested and merged through their own PRs. The ADRs in `inception/domain-design/decisions.md` constrain the grouping, and the stories in `inception/user-stories/stories.md` are assigned to units afterwards.

This stage describes which unit depends on which. The build order, and what ships first, is decided in Delivery Planning.

Your team practice requires a walking skeleton. The first unit is therefore the thinnest slice that runs end to end: an alert reaches the intake, opens an agent session, and the agent makes one read through Rancher.

Each question names the trade whose call it is.

## Q1. [Architect] How fine should the units be?

A. About seven units by capability:
   - walking skeleton;
   - coding-agent guardrails;
   - lab foundation;
   - intake and ledger;
   - output safety;
   - read-only agents;
   - remediation loop.

   Recommended: each is a coherent PR series with its own demo, and they line up with the phase gates.
B. Four coarse units: skeleton, Phase 1, Phase 2 and Phase 3, with the guardrails folded into Phase 1.
C. Fine-grained: about one unit per component (16 units).
X. Other (please specify)

[Answer]: A

## Q2. [Architect] How much goes into the walking-skeleton unit?

Rancher holds admin access to the cluster, so exposing it unprotected even briefly is a risk. The story review asked for a thinner skeleton than the stories marked.

A. The minimal slice:
   - VPC and EKS;
   - Rancher with EKS imported, behind TLS and an IP allow-list from day one;
   - one alert rule to SNS;
   - intake happy path, creating an incident record;
   - session start and one read-only Rancher query through the Gateway.

   SSO with MFA, dead-letter handling, severity filtering, dashboards and rebuild/teardown come in later units. Recommended: proves the plumbing quickly without leaving the admin endpoint open.
B. The same minimal slice, with Rancher fully hardened (SSO with MFA too) before the first run.
C. Everything the stories marked as skeleton (US2.1 to US2.3, US2.6, US3.1) in full.
X. Other (please specify)

[Answer]: C

## Q3. [Security engineer] Where do the coding-agent guardrails sit among the units?

They protect the build itself and do not depend on any lab component.

A. Their own unit with no dependencies, so it can be built alongside the skeleton or before it (recommended: the guardrails are needed before most other code lands, and nothing blocks them)
B. Part of the walking-skeleton unit
C. After Phase 1, once the lab exists
X. Other (please specify)

[Answer]: A

## Q4. [Architect] How should the pieces be deployed?

A. Hybrid:
   - intake, webhook handling and the ledger as AWS Lambda functions with DynamoDB;
   - the five agents and the session in one AgentCore Runtime deployment (one process, as the plan's inter-agent safety control assumes);
   - Terraform and Fleet bundles applied through their own paths;
   - guardrails as repository tooling.

   Recommended: matches the plan's safety assumption that agents talk inside one process.
B. Each agent as its own AgentCore Runtime deployment, talking over A2A
C. Everything, intake included, inside one AgentCore Runtime deployment
X. Other (please specify)

[Answer]: A
