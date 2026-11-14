# Spike B evidence (2026-11-14)

Question: can a pod in AKS assume an IAM role with its own Kubernetes service-account token, with no AWS keys?

Setup, which you ran from the admin terminal (`docs/runbooks/phase-0.md`, section 7):

- AKS cluster `aks-spike` in the resource group `rg-sre-spike`, East US: free tier, one `Standard_D2s_v6` node, OIDC issuer on, node SSH off (`--ssh-access disabled`).
- An IAM OIDC identity provider for the cluster's issuer, with the client ID `sts.amazonaws.com`.
- Role `aks-spike-otel`, from `tools/spikes/spike-b-trust-policy.json`: `sts:AssumeRoleWithWebIdentity`, with `StringEquals` on `<issuer>:aud` = `sts.amazonaws.com` and `<issuer>:sub` = `system:serviceaccount:spike:otel`. No permission policies.
- Pod `spike/whoami`, from `tools/spikes/spike-b-pod.yaml`: service account `otel`, a projected token with the audience `sts.amazonaws.com` and a 3,600-second lifetime, `AWS_ROLE_ARN` and `AWS_WEB_IDENTITY_TOKEN_FILE`, running `aws sts get-caller-identity`.

| Check | Result |
|---|---|
| First `az aks create`, with the runbook's `Standard_B2s` | Refused: "The VM size of Standard_B2s is not allowed in your subscription in location 'eastus'". Only the empty resource group existed afterwards, and the IAM call refused the empty issuer URL. |
| vCPU quotas in East US, read-only | B-series v2 family 0; Dsv5 family 0; Dsv3 20, with `Standard_D2s_v3` restricted in zones 1 and 2; Dsv6 10; regional total 30 |
| `az aks create` with `Standard_D2s_v6` | Succeeded |
| IAM OIDC provider, read back read-only | URL and ARN keep the issuer's trailing `/`; client ID `sts.amazonaws.com`; IAM recorded one thumbprint itself |
| Role `aks-spike-otel`, read back read-only | Condition keys `<issuer>/:aud` and `<issuer>/:sub`, trailing slash included; no attached or inline policies |
| The test pod's log | `"Arn": "arn:aws:sts::<account>:assumed-role/aks-spike-otel/botocore-session-…"` |

The issuer URL carries tenant and cluster identifiers, so this record leaves it out, and shows the account ID as `<account>`.

Teardown (2026-11-14): you ran the teardown block in runbook section 7. A read-only check afterwards found nothing left. In Azure: no `rg-sre-spike`, no AKS node resource group, no AKS cluster. In AWS: no role `aks-spike-otel` and no IAM OIDC provider for an AKS issuer. Your kubeconfig no longer has the cluster's context, cluster or user.
