# Phase 1 runbook: the walking skeleton

This runbook covers unit u1 of Phase 1: the lab on AWS, a hardened Rancher, and later the alert path and the agent's first read. This version covers the first three feature PRs: `feat/REQ-020-lab-vpc-eks-rancher` (the lab and Rancher), `feat/REQ-023-demo-telemetry-alerts` (the demo, its telemetry and its alert rule, in "PR 2" below) and `feat/REQ-030-intake-ledger` (the alert intake, the incident ledger and the dead-letter notice, in "PR 3" below). The skeleton demo, its verification and the burst test are added with the last u1 PR.

Every step marked **(you)** creates, changes or deletes something. Run it yourself, in your admin terminal with the admin profile (`AWS_PROFILE=sre-lab`), on an up-to-date `main`. Never start Claude Code in that terminal (REQ-014). Claude and CI use read-only roles and apply nothing.

Paste each command block on its own, and check its result before the next. A shell keeps running the lines after one that fails, and a command that asks you to type `yes` reads the next pasted line as your answer, so every block ends where you check a result or answer a question. Blocks hold no `#` comments, because zsh passes a comment's words to the command as arguments unless `setopt interactive_comments` is on.

## Before you start

You need these once.

| What | How | Why |
|---|---|---|
| Your domain, registered in Route 53 | Route 53 console, Registered domains | Its public hosted zone holds `rancher.<your domain>` and the certificate's validation record |
| Four plain String SSM parameters in `us-east-1` | See below | Your personal values reach Terraform from the account, never from Git |
| Terraform 1.17.x, the AWS CLI, the Session Manager plugin, kubectl, uv, the GitHub CLI | `brew install hashicorp/tap/terraform awscli kubectl uv gh`, then `brew install --cask session-manager-plugin` | Each root requires Terraform `~> 1.17.1`, as CI uses 1.17.1. Step 4 opens a shell on the Rancher host through Session Manager. Step 2 stores CI's role with `gh`, signed in with `gh auth login` |
| The coding agent refused the Cognito client secret, before you apply `permanent` | IAM Identity Center, Permission sets, `SreLabReadOnly`, inline policy: add `cognito-idp:DescribeUserPoolClient` to its deny statement, then update the provisioned account | `ReadOnlyAccess` allows `cognito-idp:Describe*`, and `DescribeUserPoolClient` returns the Rancher app client's secret (REQ-013.1) |

The four parameters **(you)**. Keep the values in your shell only; do not save them in a file.

1. Your domain. Paste this line on its own, press Enter, then type the domain and press Enter:

   ```bash
   read -r DOMAIN
   ```

2. The email address for your Rancher sign-in, the same way:

   ```bash
   read -r EMAIL
   ```

3. Look up your public address and your IAM Identity Center user ID, so neither is copied by hand. The ID comes from the name you signed in with. The last line must print `36`:

   ```bash
   MY_IP=$(curl -s https://checkip.amazonaws.com)
   STORE=$(aws sso-admin list-instances --query 'Instances[0].IdentityStoreId' --output text)
   ME=$(aws sts get-caller-identity --query Arn --output text | awk -F/ '{print $NF}')
   IDC_USER_ID=$(aws identitystore get-user-id --identity-store-id "$STORE" --alternate-identifier "{\"UniqueAttribute\":{\"AttributePath\":\"userName\",\"AttributeValue\":\"$ME\"}}" --query UserId --output text)
   echo "${#IDC_USER_ID}"
   ```

4. Store the four values:

   ```bash
   aws ssm put-parameter --type String --name /sre-lab/domain-name --value "$DOMAIN"
   aws ssm put-parameter --type String --name /sre-lab/allowlist-cidrs --value "$MY_IP/32"
   aws ssm put-parameter --type String --name /sre-lab/cognito-user-email --value "$EMAIL"
   aws ssm put-parameter --type String --name /sre-lab/idc-user-id --value "$IDC_USER_ID"
   ```

To change a value later, for example when your public address changes, run its command again with `--overwrite`.

- `allowlist-cidrs` takes one or more IPv4 CIDRs, comma-separated, each `/16` or narrower. A plan stops on anything else, including `0.0.0.0/0`.
- `idc-user-id` makes you the Grafana admin. With a wrong ID, applying `permanent` stops at `aws_grafana_role_association.admin` with `404: Failed to associate identity`. Set it again with step 3 and `--overwrite`, then plan and apply again.
- All four stay sensitive in every plan, including the plan CI posts on the public pull request.

Fleet reads `platform/` from the public repository over HTTPS, so no deploy key is needed (ADR-0005).

## Before any init: the state bucket is yours

The state bucket's name, `multi-cloud-agentic-sre-tfstate`, is public, so someone could create it first. Before the first `terraform init` on a machine, follow "Before any init" in [infra/aws/bootstrap/README.md](../../infra/aws/bootstrap/README.md): `aws s3api head-bucket --bucket multi-cloud-agentic-sre-tfstate --expected-bucket-owner "$ACCOUNT_ID"`. Never run `init` while that check fails with `403`.

## Apply order

### 1. bootstrap, once (you)

Follow [infra/aws/bootstrap/README.md](../../infra/aws/bootstrap/README.md): apply with local state, then move the state into the bucket with `terraform init -migrate-state`.

### 2. permanent (you)

The certificate for `rancher.<your domain>`, the Cognito user pool and your user, Managed Grafana, the CI plan role, and Transaction Search.

1. Initialize and plan:

   ```bash
   terraform -chdir=infra/aws/permanent init
   terraform -chdir=infra/aws/permanent plan -out=permanent.tfplan
   ```

   Read the plan before you apply it. The first time, it only adds (`0 to change, 0 to destroy`), and your domain, email and Identity Center user ID appear only as `(sensitive value)`.
2. Apply it, and wait for `Apply complete!`. The certificate's DNS validation and Grafana take about 10 minutes:

   ```bash
   terraform -chdir=infra/aws/permanent apply permanent.tfplan
   ```

3. Only after `Apply complete!`, give CI its plan role, and delete the plan file, which holds your personal values in readable form. The ARN carries your account ID, so it goes straight into the repository secret, never onto the screen or into Git:

   ```bash
   terraform -chdir=infra/aws/permanent output -raw ci_plan_role_arn | gh secret set AWS_PLAN_ROLE_ARN
   gh secret list
   rm infra/aws/permanent/permanent.tfplan
   ```

   `gh secret list` shows `AWS_PLAN_ROLE_ARN`, updated today. From the next pull request on, the `terraform` workflow plans `permanent` and `lab` and posts the plans.
4. Cognito emails your user a temporary password from no-reply@verificationemail.com. It is valid for 3 days; keep it for your first sign-in to Rancher (step 6). If it expires, have Cognito send a new one. This prints `FORCE_CHANGE_PASSWORD`:

   ```bash
   aws cognito-idp admin-create-user --user-pool-id "$(terraform -chdir=infra/aws/permanent output -raw cognito_user_pool_id)" --username operator --message-action RESEND --query User.UserStatus --output text
   ```

### 3. lab (you)

The VPC, EKS, the Rancher host, both load balancers and the DNS records.

1. Initialize and plan:

   ```bash
   terraform -chdir=infra/aws/lab init
   terraform -chdir=infra/aws/lab plan -out=lab.tfplan
   ```

   The plan stops if the pinned Kubernetes version has left EKS standard support (`infra/aws/lab/variables.tf`, `kubernetes_version`).
2. Read the plan before you apply it:

   - no `aws_nat_gateway` anywhere (REQ-020, AC2.1.1);
   - `aws_eks_cluster.lab` on version `1.36`, with `upgrade_policy` `STANDARD`;
   - no `*` resource on any write action in a policy (REQ-102.1, until u2 checks this in CI).
3. Apply it, and wait for `Apply complete!`. EKS takes about 15 minutes:

   ```bash
   terraform -chdir=infra/aws/lab apply lab.tfplan
   ```

   Then delete the plan file, which holds your personal values in readable form: `rm infra/aws/lab/lab.tfplan`.

### 4. Wait for the Rancher host

The host installs K3s and Rancher at first boot, in about ten minutes, and then writes Rancher's generated admin password to the secret `sre-lab/rancher-admin-password`. To follow it **(you)**, open a shell on the host through Session Manager:

```bash
aws ssm start-session --target "$(terraform -chdir=infra/aws/lab output -raw rancher_instance_id)"
```

Then, in that session:

```bash
sudo journalctl -t rancher-bootstrap -f
```

Press Ctrl-C to stop following the log, and type `exit` to close the session. The boot stops, and says why, if a download's SHA-256 does not match its pin.

### 5. Configure Rancher (you)

```bash
uv sync --locked
uv run python tools/lab/configure_rancher.py
```

The script is safe to run again. It waits up to 30 minutes for Rancher, then turns on Cognito sign-in for your user only, creates the `agent-readonly` role and the `sre-agent` user, and registers the EKS cluster. It then prints two commands, and waits. Copy both from its output, and run them in a second admin terminal (`export AWS_PROFILE=sre-lab AWS_REGION=us-east-1` first). They look like this:

```text
aws eks update-kubeconfig --region us-east-1 --name sre-lab-eks
kubectl apply -f https://rancher.<your domain>/v3/import/<token>.yaml
```

The second command carries the cluster's registration token. Treat it like a password: run it, and never paste it into a chat, an issue or a pull request.

The script waits until Rancher reports the cluster Ready. Then it points Fleet at `platform/` on `main`, writes the agent's 30-day token to `sre-lab/rancher-agent-token`, and checks that the stored token signs in. Apart from that registration command, it never prints a password or a token. If you ever need the registration command again, Rancher shows it on the cluster's Registration tab in Cluster Management.

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

## PR 2: the demo, its telemetry and the alert rule

`feat/REQ-023-demo-telemetry-alerts` adds:

- **Three Fleet bundles under `platform/`**, deployed to clusters labelled `cloud=aws`:
  - `sre-lab-demo-flags`: the demo's base feature flags, the ConfigMap `flagd-base-flags` in `otel-demo`, built from `platform/base/flags/demo.flagd.json` through the overlay `platform/overlays/aws`;
  - `sre-lab-otel-demo`: the OpenTelemetry Demo, every image by digest, with the load generator at one user and no browser traffic. flagd reads the base flags straight from that ConfigMap, so a flag merged to `main` reaches the running demo within about a minute;
  - `sre-lab-otel-collector`: the platform Collector in `observability`. It sends request, error and duration metrics per service to Managed Prometheus, 10% of traces to CloudWatch, and logs at warning level and above to the log group `/sre-lab/otel-demo`, all labelled `cluster=sre-lab-eks` and `cloud=aws`.
- **In `permanent`**: the Managed Prometheus workspace and its own log group, the alert rule for the demo's fault (`platform/alerts/demo-fault.yaml`: payment charges failing), the alert manager, the lab topic `sre-lab-alerts` that only the alert manager may publish to, the demo's log group, and a Grafana service account for the dashboards root.
- **In `lab`**: the Collector's IAM role, given to `observability/otel-collector` through EKS Pod Identity.
- **A new root, `infra/aws/dashboards`**: the dashboard from `platform/dashboards/skeleton.json`, and its two data sources. CI only formats and validates it; you apply it with a token that lives 30 minutes.

The demo's flag UI is not deployed: flags live in Git (ADR-0006). To set a flag out of band, for a check or for a demo, you edit the ConfigMap in the cluster, and Fleet shows that bundle as `Modified` until you put the Git value back ("Setting a demo flag out of band", below).

### 7. permanent, with PR 2 (you)

1. Plan:

   ```bash
   terraform -chdir=infra/aws/permanent plan -out=permanent.tfplan
   ```

   The plan adds 9 resources and changes or destroys none: two log groups and a log stream, the workspace, the rule group namespace, the alert manager definition, the topic and its policy, and the Grafana service account.
2. Apply it, and wait for `Apply complete!`:

   ```bash
   terraform -chdir=infra/aws/permanent apply permanent.tfplan
   ```

3. Only after `Apply complete!`, delete the plan file:

   ```bash
   rm infra/aws/permanent/permanent.tfplan
   ```

### 8. Point the Collector at the workspace, once

The Collector's remote-write address carries the workspace ID, which exists only now. Print it; it is an identifier, not a secret:

```bash
terraform -chdir=infra/aws/permanent output -raw prometheus_workspace_id
```

In `platform/otel-collector/values-aws.yaml`, replace `SET-ME` with that ID (`ws-` and 36 more characters), in a pull request of its own, for example `chore/collector-prometheus-workspace` with `Requirements: REQ-024`. Claude can open it for you. Merge it before you rebuild the lab. The workspace is permanent, so this is needed only once.

### 9. Rebuild the lab (you)

Follow steps 3 to 6 above. In step 3, read the plan for two more things:

- `aws_iam_role.collector` and `aws_eks_pod_identity_association.collector` for `observability/otel-collector`;
- no warning `permanent_layer_has_the_collector_destinations`. That warning means `permanent` was not applied with PR 2, and the Collector's role would get no metrics or logs permission: stop, and do step 7 first.

When the configuration script in step 5 has finished, Fleet deploys the three bundles from `main`. `sre-lab-otel-demo` starts after `sre-lab-demo-flags` is Ready, and is ready itself about five minutes later.

### 10. The dashboard (you)

1. Create a Grafana token that lives 30 minutes, kept only in this shell. The last line prints the token's length, never the token:

   ```bash
   WS_ID=$(terraform -chdir=infra/aws/permanent output -raw grafana_workspace_id)
   SA_ID=$(terraform -chdir=infra/aws/permanent output -raw grafana_dashboards_service_account_id)
   export GRAFANA_AUTH=$(aws grafana create-workspace-service-account-token --workspace-id "$WS_ID" --service-account-id "$SA_ID" --name "dashboards-$(date -u +%Y%m%d%H%M%S)" --seconds-to-live 1800 --query serviceAccountToken.key --output text)
   echo "${#GRAFANA_AUTH}"
   ```

   A number above 0 means the token is set.
2. Initialize and plan. The first plan adds 4 resources: the two data sources, the folder and the dashboard:

   ```bash
   terraform -chdir=infra/aws/dashboards init
   terraform -chdir=infra/aws/dashboards plan -out=dashboards.tfplan
   ```

3. Apply it, and wait for `Apply complete!`:

   ```bash
   terraform -chdir=infra/aws/dashboards apply dashboards.tfplan
   ```

4. Only after `Apply complete!`, drop the token and the plan file:

   ```bash
   unset GRAFANA_AUTH
   rm infra/aws/dashboards/dashboards.tfplan
   ```

5. Print the dashboard's address, and open it; you sign in through IAM Identity Center:

   ```bash
   terraform -chdir=infra/aws/dashboards output -raw dashboard_url
   ```

To change the dashboard later, change `platform/dashboards/skeleton.json` through a pull request, then repeat this step. Grafana does not let you edit it in place.

### Setting a demo flag out of band (you)

flagd reads `flagd-base-flags` in `otel-demo`. These commands use your EKS context from step 5.

1. Turn on a fault, here `paymentFailure` at `100%`:

   ```bash
   kubectl -n otel-demo get configmap flagd-base-flags -o json | jq '.data["demo.flagd.json"] |= (fromjson | .flags.paymentFailure.defaultVariant = "100%" | tojson)' | kubectl replace -f -
   ```

   It prints `configmap/flagd-base-flags replaced`. flagd picks it up within about a minute, and Fleet shows `sre-lab-demo-flags` as `Modified`.
2. Put the value from Git back, and check it with the first command of AC2.3.1 below:

   ```bash
   kubectl -n otel-demo get configmap flagd-base-flags -o json | jq --rawfile flags platform/base/flags/demo.flagd.json '.data["demo.flagd.json"] = $flags' | kubectl replace -f -
   ```

### Checks at the end of PR 2

**AC2.2.2: each bundle is Ready at the `main` commit.** In Rancher, Continuous Delivery, Git Repos, `sre-lab-platform` shows 3 of 3 bundle deployments ready, and its commit. Or, in a Session Manager shell on the Rancher host (step 4):

```bash
sudo k3s kubectl -n fleet-default get gitrepo sre-lab-platform -o jsonpath='{.status.commit}{" "}{.status.display.readyBundleDeployments}{"\n"}'
sudo k3s kubectl -n fleet-default get bundles -l fleet.cattle.io/repo-name=sre-lab-platform -o custom-columns='BUNDLE:.metadata.name,COMMIT:.metadata.labels.fleet\.cattle\.io/commit,READY:.status.display.readyClusters'
```

Type `exit` to close the session. Then, in your terminal:

```bash
git fetch origin
git rev-parse origin/main
```

Passes when the GitRepo shows `3/3`, each of the three bundles shows `1/1`, and every commit shown equals `origin/main`.

**AC2.3.1: the running flags match Git.**

1. The ConfigMap holds the file from Git. This prints `ConfigMap matches Git`:

   ```bash
   diff <(kubectl -n otel-demo get configmap flagd-base-flags -o jsonpath='{.data.demo\.flagd\.json}' | jq -S .) <(jq -S . platform/base/flags/demo.flagd.json) && echo "ConfigMap matches Git"
   ```

2. flagd serves those values. In a second terminal, forward flagd's evaluation port; it runs until you press Ctrl-C:

   ```bash
   kubectl -n otel-demo port-forward svc/flagd 8016:8016
   ```

3. Back in the first terminal, compare every flag's served variant with its default in Git. This prints `running flags match Git`:

   ```bash
   diff <(curl -s -X POST http://localhost:8016/ofrep/v1/evaluate/flags -H 'Content-Type: application/json' -d '{"context":{"targetingKey":"ac-2-3-1"}}' | jq -S '[.flags[] | {key, variant}] | sort_by(.key)') <(jq -S '[.flags | to_entries[] | {key, variant: .value.defaultVariant}] | sort_by(.key)' platform/base/flags/demo.flagd.json) && echo "running flags match Git"
   ```

   Then stop the port forward with Ctrl-C.

**AC2.3.2: labelled series, logs and traces.**

1. Series in Managed Prometheus carry `cluster` and `cloud=aws`. This signs the query with your admin credentials. They are exported only inside the parentheses, so they don't stay in your shell, where they would outlive your next `aws sso login` and fail later commands:

   ```bash
   WS=$(terraform -chdir=infra/aws/permanent output -raw prometheus_workspace_id)
   (eval "$(aws configure export-credentials --format env)" && curl -s --aws-sigv4 "aws:amz:us-east-1:aps" --user "$AWS_ACCESS_KEY_ID:$AWS_SECRET_ACCESS_KEY" -H "x-amz-security-token: $AWS_SESSION_TOKEN" --data-urlencode 'query=count by (cluster, cloud) (traces_span_metrics_calls_total)' "https://aps-workspaces.us-east-1.amazonaws.com/workspaces/$WS/api/v1/query") | jq -c '.data.result[] | {cluster: .metric.cluster, cloud: .metric.cloud, series: .value[1]}'
   ```

   Passes with one line, `"cluster":"sre-lab-eks","cloud":"aws"`, and a series count above 0. The same query with `count({__name__=~".+"})` gives all active series, which must stay under 2,000 (REQ-130.2).
2. The Collector reports no export error. This prints `0`; for any other count, read those lines with the same command without `-c` ("When something fails", below):

   ```bash
   kubectl -n observability logs deploy/otel-collector --since=15m | grep -c -i -E 'error|denied|forbidden'
   ```

3. Traces reach CloudWatch. This prints the number of spans from the cluster in the last 15 minutes, which must be above 0:

   ```bash
   aws logs filter-log-events --log-group-name aws/spans --start-time "$(( ($(date +%s) - 900) * 1000 ))" --filter-pattern '"sre-lab-eks"' --max-items 20 --query 'length(events)'
   ```

4. Logs reach CloudWatch. Only warnings and errors are kept, and a healthy demo may log none for a while, so set `paymentFailure` to `100%` first ("Setting a demo flag out of band"), wait five minutes, then count the last 15 minutes' events, which must be above 0:

   ```bash
   aws logs filter-log-events --log-group-name /sre-lab/otel-demo --start-time "$(( ($(date +%s) - 900) * 1000 ))" --max-items 20 --query 'length(events)'
   ```

5. While the fault is on, the alert path works up to the lab topic. `PaymentErrorRatioHigh` fires within about five minutes, and the alert manager publishes it. The first command prints the number of messages published in the last 30 minutes, which must be 1 or more; the second prints `0`, the number of errors the workspace logged:

   ```bash
   aws cloudwatch get-metric-statistics --namespace AWS/SNS --metric-name NumberOfMessagesPublished --dimensions Name=TopicName,Value=sre-lab-alerts --start-time "$(date -u -v-30M +%Y-%m-%dT%H:%M:%SZ)" --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --period 1800 --statistics Sum --query 'sum(Datapoints[].Sum)'
   aws logs filter-log-events --log-group-name /aws/vendedlogs/prometheus/sre-lab --start-time "$(( ($(date +%s) - 1800) * 1000 ))" --query 'length(events)'
   ```

   Nothing subscribes to the topic until PR 3, so the messages go no further. Put the flag back from Git, and check AC2.3.1 again.
6. The dashboard (step 10) shows the demo's request rate, error rate and duration per service, with Cluster `sre-lab-eks` and Cloud `aws`. The pipeline panels stay empty until PR 3.

## PR 3: the alert intake, the incident ledger and the dead-letter notice

`feat/REQ-030-intake-ledger` adds, all in `permanent`, so a lab teardown keeps them:

- **The incident table** `sre-lab-incidents`, with deletion protection and 35 days of point-in-time recovery.
- **Two queues**: `sre-lab-session-starts`, where the intake hands over session starts, and the dead-letter queue `sre-lab-dead-letters`, which keeps for 14 days whatever the intake could not finish.
- **The intake function** `sre-lab-intake`, subscribed to the lab topic: each alert opens, or joins, the incident of its service.
- **The notifier** `sre-lab-notifier`, run by the new operations alarm topic `sre-lab-ops-alarms`. When the dead-letter queue goes from empty to holding items, it posts one fixed notice to Slack, reading the webhook URL from `sre-lab/slack-webhook-url` at that moment.
- **Alarms in CloudWatch**: dead letters waiting, which is the only one that notifies; intake errors; ledger write failures; notice failures; slow record; and throttling of either function.

Nothing reads the session-start queue until the last u1 PR adds the session starter, so no session starts yet: requests wait there for a day, then expire.

### 11. Build the functions' package (you)

Both functions run from one package that you build on your machine. Its name carries the hash of the code it is built from, and `terraform apply` stops when the package of the commit you apply is not there.

```bash
uv sync --locked
make package
```

It prints every file's SHA-256, then three lines. The last one, `package: manifest sha256 ...`, must equal the same line in the `python-quality` run of the merged commit: on GitHub, Actions, python-quality, the run for that commit on `main`, step "Build the packages and print their hashes".

### 12. permanent, with PR 3 (you)

1. Plan:

   ```bash
   terraform -chdir=infra/aws/permanent plan -out=permanent.tfplan
   ```

   Read the plan before you apply it. It adds 29 resources and changes or destroys none. Check that:
   - both `aws_lambda_function` resources have a `filename` ending in the package name from step 11;
   - neither sets `reserved_concurrent_executions`: until your quota increase, the account's limit of 10 Lambda executions is their shared cap (SC-1);
   - no write action has a `*` resource (REQ-102.1). The notifier's `cloudwatch:GetMetricData` on `*` is a read, and CloudWatch grants it on `*` only.
2. Apply it, and wait for `Apply complete!`:

   ```bash
   terraform -chdir=infra/aws/permanent apply permanent.tfplan
   ```

   If it stops with `no such file or directory` for `build/lambda/functions-...zip`, the package of this commit is not built: do step 11, then plan again.
3. Only after `Apply complete!`, delete the plan file:

   ```bash
   rm infra/aws/permanent/permanent.tfplan
   ```

### Checks at the end of PR 3

The duplicate, attach, below-threshold and dead-letter cases (AC2.6.2 to AC2.6.5) are proven by the tests with recorded messages, in `tests/u1/intake/` and `tests/u1/notifier/` (scenarios S2 to S9). The live check is AC2.6.1, with the demo fault, on a running lab:

1. Set `paymentFailure` to `100%` ("Setting a demo flag out of band"). `PaymentErrorRatioHigh` fires within about ten minutes.
2. List the incidents. This prints one line per incident: service, status, severity, `alert_fired` and `record_created`:

   ```bash
   aws dynamodb scan --table-name sre-lab-incidents --filter-expression "item_type = :t" --expression-attribute-values '{":t":{"S":"incident"}}' --query 'Items[].[service.S, status.S, severity.S, timestamps.M.alert_fired.S, timestamps.M.record_created.S]' --output text
   ```

   Passes with a `payment` line, `open` and `critical`, whose `record_created` is 60 seconds or less after its `alert_fired` (AC2.6.1).
3. The dashboard's pipeline row shows the alert received, the incident created, and the alert-to-record time under its 60 s line.
4. Put the flag back from Git, then do the dead-letter check below. Both counts `0` also confirm that the alert manager's real message has the shape the intake reads (assumption A-01): a message it could not read would be there, with reason `invalid_payload`.

## After each demo: the dead-letter check

Alerts that cannot be recorded wait in the dead-letter queue (LC8), which PR 3 adds. A notice reaches Slack only when the queue goes from empty to holding items, and only once (observability-design.md, OD-4), so after each demo run, check it yourself. The queue's URL carries your account ID, so it goes into a variable, not onto the screen:

```bash
DEAD_LETTER_QUEUE_URL=$(terraform -chdir=infra/aws/permanent output -raw dead_letter_queue_url)
aws sqs get-queue-attributes --queue-url "$DEAD_LETTER_QUEUE_URL" --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --query Attributes
```

Both counts must be `0`. If not, find and fix the cause, then replay the items from the repository root:

```bash
uv run python -m tools.lab.replay_dead_letters
```

It prints one line per item: its shape, what it did, and the result, never the item's content. An alert goes back through the intake, where an alert already recorded changes nothing; a session start goes back to the session-start queue, unless its incident is finished or its session started, when it is dropped with that reason. Items it cannot replay stay in the queue, and the last line counts them. Running it again is safe.

## Teardown by hand, after each session (you)

Until u3 adds the teardown command and the nightly job, destroy the lab layer yourself whenever you stop working; left running, it costs about US$250 a month (ADR-0005).

```bash
terraform -chdir=infra/aws/lab destroy
```

- The permanent layer, the state bucket and your SSM parameters stay. So do, from PR 2, the Prometheus workspace and its history, the alert rule, the lab topic, the demo's logs and the dashboard; and, from PR 3, the incident table, the two queues, the intake, the notifier and their alarms, which cost nothing while idle.
- The two Rancher secrets are deleted at once, with no recovery window, so the next rebuild can create them again.
- The Collector's role and its Pod Identity association go with the lab, and come back with the next rebuild.
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
| Terraform in `permanent` or `lab`, the alert rule included | A revert pull request; after it merges, apply the same root again |
| A broken lab | `terraform -chdir=infra/aws/lab destroy`, then rebuild |
| Rancher's settings | Run `tools/lab/configure_rancher.py` again; it corrects the role, the bindings, the sign-in and the Fleet repository |
| A Fleet bundle under `platform/` | A revert pull request; Fleet deploys the reverted `main` by itself |
| A flag set out of band | Put the Git value back ("Setting a demo flag out of band") |
| The dashboard or its data sources | A revert pull request; after it merges, repeat step 10 |
| The intake, the notifier or their alarms (PR 3) | A revert pull request; after it merges, repeat steps 11 and 12. A revert that removes the incident table stops at its deletion protection, on purpose (REQ-140.3) |

## When something fails

- **The script says Rancher did not answer.** Look at the host's boot log (step 4), and at the targets' health: EC2, Target groups, `sre-lab-rancher-public`. The health check calls `/healthz` on port 443.
- **The cluster does not turn active.** On EKS: `kubectl -n cattle-system get pods` and `kubectl -n cattle-system logs deploy/cattle-cluster-agent`. The agents reach Rancher through the internal load balancer, as `rancher.<your domain>` resolves inside the VPC to it.
- **A CI plan fails on `lab` before `permanent` is applied.** Expected: `lab` reads the permanent layer's state and the SSM parameters.
- **The `lab` plan warns `permanent_layer_has_the_collector_destinations`.** `permanent` has not been applied with PR 2 yet. CI shows this warning on PR 2 itself, which is expected; before your own apply of `lab`, apply `permanent` first (step 7).
- **A bundle stays `NotReady`.** Open it in Rancher, Continuous Delivery, Git Repos, `sre-lab-platform`, or look at the pods on EKS: `kubectl -n otel-demo get pods` and `kubectl -n observability get pods`. The demo needs about five minutes after the flags bundle is Ready.
- **The Collector restarts, logging `could not retrieve credential provider`.** It started before the lab's Pod Identity association existed, so it has no AWS credentials. With the lab applied, restart it once: `kubectl -n observability rollout restart deployment otel-collector`.
- **The Collector logs 403 or 404 for `aps-workspaces`.** `platform/otel-collector/values-aws.yaml` still holds `SET-ME`, or another workspace's ID (step 8).
- **The Collector logs 403 for `logs` or `xray`.** Compare its role, `sre-lab-otel-collector`, with `infra/aws/lab/collector.tf`, and check that CloudWatch Transaction Search is on (PR 1, `permanent`).
- **No alert reaches the lab topic.** Look at the workspace's own log group, `/aws/vendedlogs/prometheus/sre-lab`: it records rule errors and failed publishes, a template error included.
- **The alert fired but no incident appears.** Read the intake's log group, `/aws/lambda/sre-lab-intake`: each alert logs `alert applied` with its outcome, or `work dead-lettered` with its reason, and never the alert's content. Then do the dead-letter check.

## Versions pinned in PR 1

| Component | Version | Source |
|---|---|---|
| Terraform AWS provider | 6.73.0, in all roots | Terraform Registry, newest release on 2026-11-11 |
| EKS | 1.36, add-ons at their 1.36 defaults | `eks:DescribeClusterVersions` and `DescribeAddonVersions`, us-east-1, 2026-11-11; Rancher 2.15.3 supports EKS up to 1.36 |
| Rancher | chart and app 2.15.3 | newest 2.15 release (2026-10-29); chart SHA-256 from the stable repository's index |
| K3s | v1.36.6+k3s1 | newest v1.36 release; binary SHA-256 from its `sha256sum-amd64.txt` |
| Ubuntu | 24.04 LTS, current image | Canonical's public SSM parameter, read at each rebuild |
| Managed Grafana | 13.2 | `grafana:ListVersions`, us-east-1, 2026-11-11 |

## Versions pinned in PR 2

Every image is pinned by the digest of its multi-arch index, which holds linux/arm64 for the Graviton nodes. Digests were read from the registries on 2026-11-12, and are in `platform/otel-demo/values.yaml` and `platform/otel-collector/values.yaml`.

| Component | Version | Source |
|---|---|---|
| OpenTelemetry Demo chart | 0.42.6 (app 3.1.0) | The chart repository's index, newest on 2026-11-12 |
| Demo images | 3.1.0, 22 images | `ghcr.io/open-telemetry/demo` |
| flagd | v0.16.0, the chart's own pin | `ghcr.io/open-feature/flagd` |
| PostgreSQL and Valkey | 18.4 and 9.0.4-alpine3.23, the chart's own pins | Docker Hub and `ghcr.io/valkey-io/valkey` |
| busybox, for the init containers | 1.38.0 | Docker Hub; the chart asked for `latest` |
| OpenTelemetry Collector chart | 0.178.3 | The chart repository's index, newest on 2026-11-12 |
| OpenTelemetry Collector | contrib 0.163.2 | Docker Hub `otel/opentelemetry-collector-contrib` |
| Terraform Grafana provider | 4.54.0, in `dashboards` | Terraform Registry, newest release on 2026-11-12 |
