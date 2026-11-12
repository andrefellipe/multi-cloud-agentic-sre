# Phase 1 runbook: the walking skeleton

This runbook covers unit u1 of Phase 1: the lab on AWS, a hardened Rancher, and later the alert path and the agent's first read. This version covers the first feature PR, `feat/REQ-020-lab-vpc-eks-rancher`. The demo, the skeleton verification and the burst test are added with the last u1 PR.

Every step marked **(you)** creates, changes or deletes something. Run it yourself, in your admin terminal with the admin profile (`AWS_PROFILE=sre-lab`), on an up-to-date `main`. Never start Claude Code in that terminal (REQ-014). Claude and CI use read-only roles and apply nothing.

## Before you start

You need these once.

| What | How | Why |
|---|---|---|
| Your domain, registered in Route 53 | Route 53 console, Registered domains | Its public hosted zone holds `rancher.<your domain>` and the certificate's validation record |
| Four plain String SSM parameters in `us-east-1` | See below | Your personal values reach Terraform from the account, never from Git |
| Terraform 1.17.x, the AWS CLI, kubectl, uv | `brew install hashicorp/tap/terraform awscli kubectl uv` | Each root requires Terraform `~> 1.17.1`, as CI uses 1.17.1 |
| The coding agent refused the Cognito client secret, before you apply `permanent` | IAM Identity Center, Permission sets, `SreLabReadOnly`, inline policy: add `cognito-idp:DescribeUserPoolClient` to its deny statement, then update the provisioned account | `ReadOnlyAccess` allows `cognito-idp:Describe*`, and `DescribeUserPoolClient` returns the Rancher app client's secret (REQ-013.1) |

The four parameters **(you)**. Type the values in your shell; do not save them in a file. Re-run a command with `--overwrite` to change a value, for example when your public address changes.

```bash
aws ssm put-parameter --type String --name /sre-lab/domain-name --value "$DOMAIN"
aws ssm put-parameter --type String --name /sre-lab/allowlist-cidrs --value "$MY_IP/32"
aws ssm put-parameter --type String --name /sre-lab/cognito-user-email --value "$EMAIL"
aws ssm put-parameter --type String --name /sre-lab/idc-user-id --value "$IDC_USER_ID"
```

- `allowlist-cidrs` takes one or more IPv4 CIDRs, comma-separated, each `/16` or narrower. A plan stops on anything else, including `0.0.0.0/0`.
- `idc-user-id` is your user ID in IAM Identity Center (Users, your user, General information, User ID). It makes you the Grafana admin.
- All four stay sensitive in every plan, including the plan CI posts on the public pull request.

Fleet reads `platform/` from the public repository over HTTPS, so no deploy key is needed (ADR-0005).

## Before any init: the state bucket is yours

The state bucket's name, `multi-cloud-agentic-sre-tfstate`, is public, so someone could create it first. Before the first `terraform init` on a machine, follow "Before any init" in [infra/aws/bootstrap/README.md](../../infra/aws/bootstrap/README.md): `aws s3api head-bucket --bucket multi-cloud-agentic-sre-tfstate --expected-bucket-owner "$ACCOUNT_ID"`. Never run `init` while that check fails with `403`.

## Apply order

### 1. bootstrap, once (you)

Follow [infra/aws/bootstrap/README.md](../../infra/aws/bootstrap/README.md): apply with local state, then move the state into the bucket with `terraform init -migrate-state`.

### 2. permanent (you)

The certificate for `rancher.<your domain>`, the Cognito user pool and your user, Managed Grafana, the CI plan role, and Transaction Search.

```bash
terraform -chdir=infra/aws/permanent init
terraform -chdir=infra/aws/permanent plan -out=permanent.tfplan
terraform -chdir=infra/aws/permanent apply permanent.tfplan
```

Then:

1. Give CI its plan role. The ARN carries your account ID, so it goes straight into the repository secret, never onto the screen or into Git:

   ```bash
   terraform -chdir=infra/aws/permanent output -raw ci_plan_role_arn | gh secret set AWS_PLAN_ROLE_ARN
   ```

   From the next pull request on, the `terraform` workflow plans `permanent` and `lab` and posts the plans.
2. Cognito emails your user a temporary password. Keep it for your first sign-in to Rancher (step 6).

### 3. lab (you)

The VPC, EKS, the Rancher host, both load balancers and the DNS records.

```bash
terraform -chdir=infra/aws/lab init
terraform -chdir=infra/aws/lab plan -out=lab.tfplan
terraform -chdir=infra/aws/lab apply lab.tfplan
```

Read the plan before you apply it:

- no `aws_nat_gateway` anywhere (REQ-020, AC2.1.1);
- `aws_eks_cluster.lab` on version `1.36`, with `upgrade_policy` `STANDARD`;
- no `*` resource on any write action in a policy (REQ-102.1, until u2 checks this in CI).

EKS takes about 15 minutes. The plan stops if the pinned Kubernetes version has left EKS standard support (`infra/aws/lab/variables.tf`, `kubernetes_version`).

### 4. Wait for the Rancher host

The host installs K3s and Rancher at first boot, in about ten minutes, and then writes Rancher's generated admin password to the secret `sre-lab/rancher-admin-password`. To follow it **(you)**:

```bash
aws ssm start-session --target "$(terraform -chdir=infra/aws/lab output -raw rancher_instance_id)"
sudo journalctl -t rancher-bootstrap -f
```

The boot stops, and says why, if a download's SHA-256 does not match its pin.

### 5. Configure Rancher (you)

```bash
uv sync --locked
uv run python tools/lab/configure_rancher.py
```

The script is safe to run again. It waits for Rancher, then turns on Cognito sign-in for your user only, creates the `agent-readonly` role and the `sre-agent` user, and registers the EKS cluster. It prints two commands; run them in a second admin terminal:

```bash
aws eks update-kubeconfig --region us-east-1 --name sre-lab-eks
kubectl apply -f https://rancher.<your domain>/v3/import/<token>.yaml   # as printed
```

The script waits for the cluster to turn active, points Fleet at `platform/` on `main`, and writes the agent's 30-day token to `sre-lab/rancher-agent-token`. It never prints a password or a token.

### 6. Sign in to Rancher

Open the address from `terraform -chdir=infra/aws/lab output -raw rancher_url` and choose Amazon Cognito. The first time, Cognito asks for the temporary password from its email, a new password, and to set up an authenticator app. Your Cognito identity is a Rancher admin.

The local `admin` account is for break-glass use only (REQ-021.1). Its password is in Secrets Manager, readable with your admin profile.

## Checks at the end of PR 1

| Check | How | Passes when |
|---|---|---|
| AC2.1.1 | Your `lab` plan in step 3. CI cannot plan PR 1 itself, since the bucket and the plan role do not exist yet; from the next pull request that changes `infra/aws`, the `terraform` workflow's plan comment shows the same | zero NAT gateways; EKS `1.36` |
| AC2.1.2 | `aws eks describe-cluster --name sre-lab-eks --query cluster.status` | `"ACTIVE"`, after your own apply |
| AC2.2.1, address | From a network outside your allow-list (a phone hotspot): `curl -sS --max-time 10 https://rancher.<your domain>/ping` | the connection times out; from inside the allow-list it prints `pong` |
| AC2.2.1, MFA | `aws cognito-idp get-user-pool-mfa-config --user-pool-id "$(terraform -chdir=infra/aws/permanent output -raw cognito_user_pool_id)"`, then a sign-in in a private window where you enter a wrong authenticator code | `"MfaConfiguration": "ON"`; the wrong code is refused and there is no way past the code prompt |
| REQ-013.1 | With the coding agent's read-only profile: `AWS_PROFILE=sre-lab-ro aws secretsmanager get-secret-value --secret-id sre-lab/rancher-agent-token` | `AccessDeniedException` |
| REQ-050.1 | In Rancher, Users & Authentication, Roles, Cluster, `agent-readonly` | get, list and watch only; no Secrets |

AC2.2.2, Fleet reporting a bundle `Ready` at a `main` commit, is checked at the end of PR 2, when `platform/` holds its first bundles.

## After each demo: the dead-letter check

Alerts that cannot be recorded wait in the dead-letter queue (LC8), which PR 3 adds. A notice reaches Slack only when the queue goes from empty to holding items, and only once (observability-design.md, OD-4), so after each demo run, check it yourself:

```bash
aws sqs get-queue-attributes --queue-url "$DEAD_LETTER_QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible
```

Both counts must be `0`. If not, find and fix the cause, then replay the items with `tools/lab/replay_dead_letters.py` (PR 3).

## Teardown by hand, after each session (you)

Until u3 adds the teardown command and the nightly job, destroy the lab layer yourself whenever you stop working; left running, it costs about US$250 a month (ADR-0005).

```bash
terraform -chdir=infra/aws/lab destroy
```

- The permanent layer, the state bucket and your SSM parameters stay.
- The two Rancher secrets are deleted at once, with no recovery window, so the next rebuild can create them again.
- Check that nothing billable is left:

  ```bash
  aws resourcegroupstaggingapi get-resources --tag-filters Key=teardown-policy,Values=destroy \
    --query 'ResourceTagMappingList[].ResourceARN'
  ```

  The list must be empty. A deleted resource can stay in this list for a few minutes; delete anything still there after that yourself.

To rebuild, repeat steps 3 to 6. Each rebuild takes the newest Ubuntu 24.04 image and issues the agent a new token.

## Rollback

| What changed | How to roll back |
|---|---|
| Terraform in `permanent` or `lab` | A revert pull request; after it merges, apply the same root again |
| A broken lab | `terraform -chdir=infra/aws/lab destroy`, then rebuild |
| Rancher's settings | Run `tools/lab/configure_rancher.py` again; it corrects the role, the bindings, the sign-in and the Fleet repository |

## When something fails

- **The script says Rancher did not answer.** Look at the host's boot log (step 4), and at the targets' health: EC2, Target groups, `sre-lab-rancher-public`. The health check calls `/healthz` on port 443.
- **The cluster does not turn active.** On EKS: `kubectl -n cattle-system get pods` and `kubectl -n cattle-system logs deploy/cattle-cluster-agent`. The agents reach Rancher through the internal load balancer, as `rancher.<your domain>` resolves inside the VPC to it.
- **A CI plan fails on `lab` before `permanent` is applied.** Expected: `lab` reads the permanent layer's state and the SSM parameters.

## Versions pinned in PR 1

| Component | Version | Source |
|---|---|---|
| Terraform AWS provider | 6.73.0, in all roots | Terraform Registry, newest release on 2026-11-11 |
| EKS | 1.36, add-ons at their 1.36 defaults | `eks:DescribeClusterVersions` and `DescribeAddonVersions`, us-east-1, 2026-11-11; Rancher 2.15.3 supports EKS up to 1.36 |
| Rancher | chart and app 2.15.3 | newest 2.15 release (2026-10-29); chart SHA-256 from the stable repository's index |
| K3s | v1.36.6+k3s1 | newest v1.36 release; binary SHA-256 from its `sha256sum-amd64.txt` |
| Ubuntu | 24.04 LTS, current image | Canonical's public SSM parameter, read at each rebuild |
| Managed Grafana | 13.2 | `grafana:ListVersions`, us-east-1, 2026-11-11 |
