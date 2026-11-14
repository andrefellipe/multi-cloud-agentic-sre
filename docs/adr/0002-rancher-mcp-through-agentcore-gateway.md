# ADR-0002: The agent reads Rancher through rancher-ai-mcp, behind AgentCore Gateway, privately

- Status: Accepted
- Date: 2026-11-14
- Requirements: REQ-050 (REQ-050.1), REQ-102, REQ-103 (REQ-103.1)

## Context

REQ-050 gives the Investigator only read tools, all reached through AgentCore Gateway, and reaches Kubernetes through the Rancher proxy with a token whose role has no write verb and no access to Secrets. REQ-102 forbids any Kubernetes write verb, and REQ-103 keeps the Rancher token in AgentCore Identity or Secrets Manager. Phase 0's Spike A (`docs/runbooks/phase-0.md`, section 6) asked whether that holds with Rancher's own MCP server: can an agent use `rancher-ai-mcp` with a read-only Rancher token, through AgentCore Gateway?

You ran the spike on 2026-11-13 and 2026-11-14 on a temporary instance in the lab account, with single-node Rancher v2.15.3, the version the lab runs. The evidence is in `docs/evidence/spike-a/a4.md` (the server called directly) and `docs/evidence/spike-a/a5.md` (through the gateway).

Two constraints shaped how it ran:

- Every Bedrock model call from the account fails with "Error 002" until AWS Support lifts a block. So the runbook's "minimal Strands agent" in step A5 was replaced by a plain MCP client that signs its calls with SigV4 (AWS's `mcp-proxy-for-aws-cli` 1.8.0). It takes the same path through the gateway that an agent will.
- Claude works with read-only AWS credentials and may not delete cloud resources or handle secrets. Claude wrote the spike's scripts and its read-only checks; you ran every command that created, changed or deleted anything, and the Rancher passwords and token stayed in your Keychain.

## Decision

1. **The server: `rancher-ai-mcp` v1.2.0-alpha.5**, commit `46f49c7e4e296e003b01c05ab97fb918c733cb49`, with its image built from that commit, because no public image is published. It runs with `--read-only`, which registers its 29 read tools and none of its 24 write tools. The pin is exact; Phase 1's rule puts the image in ECR pinned by digest.
2. **The identity in Rancher: the local user `sre-agent`**, with the global role `user-base` and nothing else, and the cluster role `agent-readonly`: get, list and watch on pods, pod logs, events, namespaces, deployments, replica sets, services and nodes, and nothing on Secrets. This is what `tools/lab/configure_rancher.py` already creates (REQ-050.1). Rancher's RBAC refused both the Secrets read and the write the spike tried, and the server's `--read-only` is a second, separate layer.
3. **The path: AgentCore Gateway, protocol MCP, signed in with IAM (`AWS_IAM`).** The server is one MCP target. The gateway reads the Rancher token from an API key credential provider, which keeps it in Secrets Manager, and sends it in the header `R_token`, with no prefix: the header `rancher-ai-mcp` reads in HTTP mode.
4. **The network: private.** The target's managed VPC Lattice endpoint (`privateEndpoint.managedVpcResource`) sits in the VPC and routes to an internal Application Load Balancer, named by `routingDomain`. The target's URL uses a hostname covered by a public ACM certificate on that load balancer, so the gateway trusts it without a custom CA. Only the load balancer may reach the server's port. Nothing is open to the internet.
5. **The gateway's role** may call `bedrock-agentcore:GetWorkloadAccessToken` and `bedrock-agentcore:GetResourceApiKey` on its own workload identity (`workload-identity-directory/default` and `workload-identity-directory/default/workload-identity/<gateway name>-*`), the token vault and the credential provider, and `secretsmanager:GetSecretValue` on that provider's secret alone.
6. **A gateway setup is proven by a real tool call**, never by the target's `READY` status.

## Options considered

- **The public path: the server open to the internet behind a trusted certificate**, for example Let's Encrypt or an internet-facing load balancer. The gateway supports it. But AgentCore calls from no fixed addresses, so the server's port would be open to everyone, guarded only by the token. Claude recommended it for the spike as the quicker route; you chose the private route, which needs no more parts and is the one production will use.
- **The private path with Rancher's self-signed certificate.** On a private endpoint the gateway can trust a custom CA (`certificateConfigurations`, from S3 or Secrets Manager). On the public path it trusts only publicly issued certificates (AWS documentation, not tested). Terraform's provider has no argument for it up to 6.73.0, which the repository pins, and a public ACM certificate on an internal load balancer avoids it.
- **A generic Kubernetes MCP server with a Rancher-generated kubeconfig**, the runbook's fallback. Not needed: `rancher-ai-mcp` passed. It would also lose the Rancher-aware tools that span clusters and Fleet.
- **`rancher-ai-mcp`'s OAuth mode, with Rancher as the authorization server** (`--authz-server-url`, `--jwks-url`, and the gateway's OAuth credential provider). Not tested. It is the option to take if the `R_token` header cannot pass a load balancer, because a token in `Authorization: Bearer` survives the header check described under Consequences.
- **The stable release, v1.1.1.** It has no stdio mode, which step A4 needed to test from Claude Code; both releases have HTTP mode.
- **Temporary write access for Claude, to run the spike itself.** You asked why Claude didn't run it. Claude explained the read-only role, the ban on cloud deletes and keeping secrets out of its transcript, and recommended scripts you run instead; you agreed. Claude's credentials stayed read-only throughout.

## Consequences

For u1's PR 4 (plan Step 32), which builds the agent's first read through Rancher:

- **Where the server runs in the lab** is still open: on the Rancher host or in EKS. Outside a cluster, its HTTP mode needs `--insecure`. That serves plain HTTP and skips the check of Rancher's certificate, so the hop to Rancher must stay on the same host, or the server runs in a cluster, where it reads Rancher's CA itself.
- **The lab's load balancers would strip the token.** Both set `drop_invalid_header_fields = true` (`infra/aws/lab/load_balancers.tf`), and `R_token` has an underscore, which that check treats as invalid. The spike showed it: with the check turned on, the same call failed for missing credentials, and it worked again once the check was off. ADR-0005 meant the internal one for "the Kubernetes read server". PR 4 needs a load balancer or listener without that setting, or the server's OAuth mode.
- **Terraform has what it needs** at the pinned 6.73.0:
  - `aws_bedrockagentcore_gateway`, `aws_bedrockagentcore_gateway_target` and `aws_bedrockagentcore_api_key_credential_provider`, from 6.17.0;
  - the target's `private_endpoint`, from 6.50.0;
  - the provider's `api_key_secret_source`, from 6.66.0.

  It has no `certificate_configurations` argument and no action to synchronize a target's tools.
- **Token rotation:** `configure_rancher.py` already issues `sre-agent` a 30-day token into the Secrets Manager secret `sre-lab/rancher-agent-token`. The credential provider can read that secret directly (`apiKeySecretSource` `EXTERNAL`) instead of holding a copy, but it reads one key of a JSON secret (`apiKeySecretConfig`: the secret and a `jsonKey`), and the script writes the token as plain text. One of the two has to change.
- **Zones:** a load balancer sends traffic only to targets in its own zones. The managed endpoint accepts subnets only in the zone IDs use1-az1, az2, az4, az5 and az6, and zone names map to different zone IDs in each account.
- **AWS's documented example policy is incomplete:** without the workload-identity ARNs, every tool call failed with "An internal error occurred" while the target showed `READY`. The target was `READY` because the gateway discovers tools with the caller's credentials and calls them with its role. CloudTrail named the missing resource.
- **Tool annotations:** 52 of the 53 tools carry none, so no client or proxy can tell reads from writes by annotation. `mcp-proxy-for-aws`'s own `--read-only` would hide every tool. The server's `--read-only` and Rancher's RBAC do that job.
- **The server has no delete tool;** its write tools create, patch, scale, update and move resources, each with a "Plan" variant that returns the JSON without changing anything.
- **Responses are larger in HTTP mode,** which returns `uiContext` beside `llm`, and the server reports v1.0.0 whatever its release. It is an alpha, so watch its releases until a stable one has stdio and HTTP mode.
- **Cost:** the gateway charges $0.005 per 1,000 calls and $0.02 per 100 indexed tools a month; Lattice charges for data processed; an internal load balancer costs about $0.02 an hour at lab hours.
- **Still to show:** an agent, not a plain client, calling through the gateway, once Bedrock access is restored. That is PR 4's own verification.

### Security and compliance

- **Exposure:** the server is reachable only from its load balancer, and the load balancer only from inside the VPC. The gateway refused an unsigned request (HTTP 401).
- **The token:** it reached the gateway only through the credential provider and Secrets Manager (REQ-103). The spike never printed it or wrote it to a file; it stayed in your Keychain until then.
- **Least privilege, in three layers:**
  - the gateway's role reads one secret;
  - the server registers only read tools;
  - Rancher's RBAC refuses Secrets and every write verb (REQ-050.1, REQ-102). The spike proved both refusals with HTTP 403.
- **What the spike loosened, and the lab must not:** `--insecure` skips the server's check of Rancher's certificate on the same host, and the hop from the load balancer to the server is plain HTTP inside the VPC. The spike also turned on the gateway's detailed errors to diagnose the role, and the lab keeps them off.

## AI involvement

Claude, outside an AI-DLC stage, as Phase 0 spike work:
- researched the gateway's documentation with two research agents;
- wrote the spike's scripts and their tests (against Rancher fakes, moto and the AWS service models);
- read the results back with read-only credentials, including CloudTrail;
- drafted this ADR and its evidence.

You:
- ran every step;
- chose the private route over Claude's recommendation of the public one;
- approved the write test against Rancher.

Six of Claude's mistakes surfaced during the run. Each was fixed before the next step, and none changed anything it should not have:
- the Rancher setup script took `/ping` as ready while Rancher's other routes still answered 503;
- load balancer zones chosen without the instance's zone;
- an SSH session left silent until the network dropped it;
- an apostrophe in a security group description;
- the gateway role's missing workload-identity resources;
- the teardown script called a helper with an outdated signature, and stopped before it read or deleted anything.

You accepted it unchanged on 2026-11-14.
