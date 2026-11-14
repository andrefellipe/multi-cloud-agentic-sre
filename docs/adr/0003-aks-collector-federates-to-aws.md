# ADR-0003: The AKS collector reaches AWS with its service-account token, through IAM's OIDC federation

- Status: Proposed
- Date: 2026-11-14
- Requirements: REQ-152, REQ-024

## Context

REQ-152 allows no long-lived static cloud keys in code or CI. The plan's OpenTelemetry Collector on AKS sends telemetry to AWS (Managed Prometheus and CloudWatch, REQ-024), so it needs AWS credentials without keys: "AKS workload identity tokens federated to an IAM role; SigV4 signing" (`docs/plan.md`, "Identity without static keys"). Phase 0's Spike B (`docs/runbooks/phase-0.md`, section 7) asked whether that works: can a pod in AKS assume an IAM role with its own Kubernetes service-account token?

You ran it on 2026-11-14 on a throwaway AKS cluster in East US: free tier, one node, with the cluster's OIDC issuer turned on. The evidence is in `docs/evidence/spike-b/result.md`.

## Decision

1. **The AKS collector authenticates to AWS with `sts:AssumeRoleWithWebIdentity`,** using a projected service-account token whose audience is `sts.amazonaws.com`. No AWS key exists in the cluster, in Git or in CI. The AWS SDK's standard variables, `AWS_ROLE_ARN` and `AWS_WEB_IDENTITY_TOKEN_FILE`, carry it.
2. **IAM trusts the cluster's own OIDC issuer** (AKS's `--enable-oidc-issuer`), registered as an IAM OIDC identity provider with the client ID `sts.amazonaws.com`.
3. **The role trusts one service account and one audience:** `StringEquals` on `<issuer>:aud` = `sts.amazonaws.com` and `<issuer>:sub` = `system:serviceaccount:<namespace>:<service account>`, where `<issuer>` comes from the provider's ARN, trailing slash included.
4. **The collector's role gets only what its exporters need,** defined with the AKS unit, for example `aps:RemoteWrite` on the workspace. The spike's role had no permissions at all, because `sts:GetCallerIdentity` needs none.
5. **Terraform manages the cluster's issuer, the IAM provider and the role together,** in the AKS unit, and reads the issuer URL from the cluster, so the URL never appears in Git.

## Options considered

- **An IAM user's access keys in a Kubernetes Secret.** Rejected: REQ-152 forbids it, and the keys would need rotating and could leak.
- **Microsoft Entra Workload ID tokens federated to AWS.** Entra would issue the token instead of the cluster. That adds an Entra app registration and a second identity provider in IAM, while the cluster's own issuer already does the job.
- **IAM Roles Anywhere with X.509 certificates.** It needs a private CA and certificates delivered to the cluster: more to run than federation, for no gain here.
- **Sending AKS telemetry through a relay in AWS** instead of writing from AKS. It changes the telemetry path (ADR-0006) and still needs a credential somewhere.

## Consequences

- **The trailing slash.** AKS's issuer URL ends with `/`, and IAM kept it in the provider's URL, in its ARN and in the role's condition keys (`<issuer>/:aud` and `<issuer>/:sub`). Keys derived from the ARN matched; keys typed without the slash would not.
- **No thumbprint to manage.** The spike passed none, and IAM recorded one itself.
- **The issuer belongs to the cluster.** Recreating the cluster changes its issuer URL, so the IAM provider and the role's conditions must change with it. Terraform has to keep the three together, and every rebuild of the AKS lab recreates them.
- **The issuer URL carries tenant and cluster identifiers.** Treat it like an account ID: read it at run time and never commit it. The spike's evidence leaves it out.
- **VM sizes in this subscription.** AKS refused `Standard_B2s` in East US. The B-series v2 and Dsv5 families have no vCPU quota there, and `Standard_D2s_v3` is restricted in zones 1 and 2. `Standard_D2s_v6` (2 vCPUs, 8 GiB) worked. The lab's AKS Terraform should use it, or request quota for another family first.
- **Node SSH stays off** (`--ssh-access disabled`), so no SSH key is generated or needed.
- **Still to show:** the collector's `sigv4auth` extension signing its writes to Managed Prometheus and CloudWatch with these credentials. It uses the same SDK credential chain, so it should work; the AKS unit verifies it.

### Security and compliance

- No AWS secret exists in the cluster. A stolen projected token is useful only until it expires (3,600 seconds in the spike), only for this role, and only because it names this service account and audience.
- The spike's role had no permissions, and the teardown removes the cluster, the IAM provider and the role.

## AI involvement

Claude:
- wrote the runbook's steps in Phase 0 and corrected them during the run;
- checked the subscription's VM quotas and restrictions read-only, and chose `Standard_D2s_v6`;
- read the IAM provider and the role back with read-only credentials, without printing the issuer's identifiers;
- drafted this ADR and its evidence.

You:
- ran every step that created or changed anything in Azure and AWS;
- ran the test pod and reported its result.

Claude's mistake: the runbook's VM size, `Standard_B2s`, which Claude chose in Phase 0, is not allowed in this subscription, so the first cluster creation failed. That attempt created only an empty resource group, and nothing in AWS.
