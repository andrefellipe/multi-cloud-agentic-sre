# ADR-0005: The lab's cost envelope, and how Rancher is reached

- Status: Accepted
- Date: 2026-11-12
- Requirements: REQ-130 (REQ-130.1), REQ-021 (REQ-021.1), REQ-022, REQ-024, REQ-152 (REQ-152.1), REQ-013 (REQ-013.1)

## Context

REQ-130.1 first estimated u1's running cost at about US$60 a month, at about 110 lab hours a month. Your answers in u1's Infrastructure Design (Q1 to Q4) then chose how Rancher is reached and where Grafana runs, and each choice has a price.

The constraints behind those answers:

- Rancher answers only over TLS, only to allow-listed addresses, and only after single sign-on with MFA (REQ-021).
- The lab is rebuilt from zero every night (REQ-025, REQ-131). Let's Encrypt issues at most 5 certificates for one name in 7 days.
- The lab has no NAT gateway (REQ-020). Cluster nodes reach the internet from their own, changing, public addresses, which no allow-list can hold.

Two facts changed after the plan was approved:

- The repository is public now, not from Phase 7. Everything on `main`, every pull request, the plan comment CI posts and every Actions log can be read by anyone. Your domain, email address, addresses, Identity Center user ID and account ID must reach none of them.
- Because the repository is public, Fleet can read `platform/` without credentials.

## Decision

1. **Cost envelope: about US$75 a month** at about 110 lab hours, with the lab layer destroyed after each session:

   | Item | Estimate |
   |---|---|
   | u1 as first estimated (`nfr-requirements/scalability-requirements.md`) | about US$55 |
   | Managed Grafana, one active editor | US$9 |
   | Two load balancers, at lab hours | about US$6 |
   | Domain registration spread monthly, two hosted zones | about US$2 |
   | **Total** | **about US$72, so a target of about US$75** |

   Left running all month, the lab layer would cost about US$250. Until u3 automates teardown, you destroy it by hand (`docs/runbooks/phase-1-skeleton.md`).
2. **TLS from AWS Certificate Manager.** A free certificate for `rancher.<your domain>`, validated through DNS in your domain's Route 53 zone, in the permanent layer. ACM renews it; no rebuild issues a certificate.
3. **Two load balancers, one name.** A public Application Load Balancer, open on 443 only to your allow-list, and an internal one for clients inside the VPC (the cluster agents, later the Kubernetes read server). Both end TLS 1.2 or later with the certificate and re-encrypt to Rancher on 443. `rancher.<your domain>` points at the public one in the public zone, and at the internal one in a private zone tied to the VPC.
4. **Sign-in through Amazon Cognito, with MFA required.** One user pool, MFA with an authenticator app required for every sign-in, holding only your user. Rancher's Cognito provider admits that one identity (access mode `required`) and makes it an admin. The app client is confidential, because Rancher 2.15.3 requires a client secret. The local `admin` account remains for break-glass use only, with its password in Secrets Manager, written there by the Rancher host and never by Terraform.
5. **Amazon Managed Grafana**, signing in through IAM Identity Center, with you as admin.
6. **Your personal values live in four plain String SSM parameters**: `/sre-lab/domain-name`, `/sre-lab/allowlist-cidrs`, `/sre-lab/cognito-user-email` and `/sre-lab/idc-user-id`. Terraform reads them with `value`, which it treats as sensitive, so no plan shows them; it never iterates over them; and it builds `rancher.<your domain>` from the parameter. The account ID and partition always come from data sources, never from a file. CI plans with the same values you apply with, and none of them is in Git.
7. **No deploy key.** Fleet reads the public repository over HTTPS with no credentials. This replaces the deploy key that the infrastructure specification listed as a prerequisite and that plan Step 10 configured.
8. **The state bucket's public name is defended twice.** You confirm the bucket is yours before any `terraform init` (`aws s3api head-bucket --expected-bucket-owner`), and the CI plan role is refused every S3 bucket that another account owns (`s3:ResourceAccount`).

## Options considered

- **Let's Encrypt on the Rancher host** (Q1 A and B, Q4 B). A nightly rebuild hits the limit of 5 certificates in 7 days by the sixth night. Saving and restoring the certificate each night would be one more step the rebuild must get right, and the host would need write access to the DNS zone.
- **Rancher's self-signed certificate** (Q1 C). Every browser visit warns, and every client, the Kubernetes read server included, would have to trust a private CA.
- **A single load balancer.** A public one alone would see the cluster agents arrive from the nodes' changing public addresses, which the allow-list cannot hold; opening it to them would open Rancher to the internet. An internal one alone would need a VPN for you to reach Rancher. The second load balancer costs about US$3 a month at lab hours.
- **A Network Load Balancer passing TLS through to Rancher.** Rancher would then need a publicly trusted certificate of its own, which brings back Let's Encrypt.
- **GitHub sign-in** (Q2 B). MFA would be enforced by your GitHub settings, not by the lab, so the "no MFA, no login" check would test GitHub rather than this system.
- **A public Cognito app client, with no secret.** Rancher's OIDC configuration requires a client secret (Rancher 2.15.3, `pkg/apis/management.cattle.io/v3/authn_types.go`).
- **Grafana in the cluster** (Q3 A). Free, but it disappears with every teardown.
- **A deploy key for Fleet.** For a public repository it protects nothing, and it would be one more secret to store and rotate.
- **Personal values in Terraform variables, a committed tfvars file, or CI variables.** A committed file is public, and CI variables would need a second copy for your own applies; SSM gives both the same single source.

## Consequences

- The estimate holds only while the lab layer is destroyed after each session. Watch Cost Explorer filtered by the `project` tag after the first month; the US$150 budget of REQ-130 arrives with u3.
- Two load balancers and a private zone are more parts to build and tear down, about US$6 a month at lab hours.
- The Cognito app client's secret is in Terraform state, marked sensitive, which the CI plan role can read. Cognito also returns it to any role allowed `cognito-idp:DescribeUserPoolClient`, which `ReadOnlyAccess` grants. The coding agent's permission set denies that call (runbook, "Before you start"); the CI plan role keeps it, because its plan reads the client. This is accepted for Phase 1 (`cicd-pipeline.md`); u2 revisits it.
- The domain renews every year, for about US$14.
- When your public address changes, update `/sre-lab/allowlist-cidrs` and apply the lab layer again; until then, Rancher and the EKS API refuse you.
- The local admin account can sign in without MFA. It is the break-glass path that REQ-021.1 allows, and its password is readable only with your admin profile.
- The agent's Rancher token is issued through Rancher's v3 token API, which Rancher deprecated in 2.14 and still serves in 2.15. `tools/lab/configure_rancher.py` must move to `tokens.ext.cattle.io` before an upgrade removes it.

## AI involvement

Claude, in the developer role of AI-DLC Code Generation for u1's first feature PR, drafted this ADR from the Infrastructure Design answers (Q1 to Q4) and from your decisions since the plan: the repository is public, Fleet needs no deploy key, and the domain is a fourth SSM parameter. Claude checked the versions and Rancher's source for the Cognito client secret. The alternatives above are the options you rejected in Infrastructure Design, plus the deploy key the plan had and you dropped. You accepted it unchanged after pull request #6 merged.
