# Phase 0 runbook: inception and spikes

**Gate: 2026-11-29.** You can start before November 16.

To pass the gate:

- AI-DLC Inception is approved, and ADR-0001 is accepted.
- Spike A (Rancher MCP behind AgentCore Gateway) and spike B (AKS to AWS identity without keys) pass, or their fallbacks are chosen in an ADR.
- Claude Code telemetry reaches a collector (spike C).

Steps marked **(you)** create, change or delete cloud resources. Run them yourself; the project's guardrail hook blocks Claude from running them.

## 1. Lock down the accounts (about 1 hour)

**AWS** (region `us-east-1`):

1. Root user: turn on MFA, store the credentials safely, and stop using root.
2. Turn on IAM Identity Center. Create your own user with MFA and the `AdministratorAccess` permission set. On your Mac, run `aws configure sso --profile sre-lab`, then `export AWS_PROFILE=sre-lab`.
3. Billing, Budgets: create a monthly cost budget of US$300 with email alerts at 50%, 80% and 100%. Turn on Cost Anomaly Detection.
4. Bedrock console, model catalog: confirm you can use Claude Sonnet and Claude Haiku in `us-east-1`. If Bedrock asks for Anthropic's one-time use-case form, fill it in. Note the model or inference-profile IDs for Phase 2.

**Azure** (region East US):

1. Turn on MFA for your account.
2. Cost Management, Budgets: create a budget of US$50 a month with alerts at 50%, 80% and 100%.
3. Run `az login`, then register the providers you'll need:
   ```bash
   az provider register --namespace Microsoft.ContainerService
   az provider register --namespace Microsoft.Chaos
   ```
4. Check your vCPU quota: `az vm list-usage --location eastus -o table`.

**GitHub:** turn on two-factor authentication if it's off.

## 2. Install the toolchain (about 30 minutes)

```bash
brew tap hashicorp/tap
brew install hashicorp/tap/terraform gh awscli azure-cli kubectl helm jq uv
curl -fsSL https://claude.ai/install.sh | bash
```

The last line is Claude Code's native installer. Install Docker Desktop (`brew install --cask docker-desktop`, or OrbStack) for the local collector spike (spike C), and open it once to finish setup. Rancher runs on an EC2 instance instead (spike A).

## 3. Create the repository (about 20 minutes)

`~/Downloads` is a risky home for a months-long project. If you move the folder (to `~/Projects`, say), do it now, before `git init`.

Put the PR template and the CI workflow, which ship in `tools/github-setup/`, in place, and run the guardrail hook's tests. They must print `26 passed, 0 failed`:

```bash
cd ~/Downloads/multi_cloud_agentic_SRE
mkdir -p .github/workflows
cp tools/github-setup/pull_request_template.md .github/
cp tools/github-setup/methodology-checks.yml .github/workflows/
chmod +x tools/claude-hooks/*.sh
bash tools/claude-hooks/test-guard.sh
```

Only when they pass, create the repository and push it. Use `--private` instead of `--public` if you have GitHub Pro (see below):

```bash
git init -b main
git add .
git commit -m "chore: Phase 0 scaffold" \
  -m "Drafted with Claude from the project plan; see ADR-0001." \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
gh repo create multi-cloud-agentic-sre --public --source . --push
```

**Public or private?** GitHub enforces rulesets on private repositories only with GitHub Pro (about US$4 a month); on GitHub Free they need a public repository. Public from day one also gives you free secret scanning with push protection, and an audit trail that was visible as it happened.

On GitHub, go to Settings, Rules, Rulesets, then New branch ruleset:

- Name `main`, enforcement **Active**, target the default branch, and leave the bypass list **empty**.
- Rules: Restrict deletions; Block force pushes; Require a pull request before merging, with **0 required approvals**. GitHub won't let you approve your own PRs, so your merge is the human gate; the agent's PRs in Phase 3 are the ones you review.
- After your first PR runs the workflow, add the required status check `pr-evidence`.
- In a later PR, save the ruleset as evidence: `gh api repos/{owner}/{repo}/rulesets` shows its ID, then `gh api repos/{owner}/{repo}/rulesets/<ID> > docs/evidence/rulesets/main.json`. Settings, Rules, Insights shows every push and merge checked against it.

From here on, every change goes through a pull request.

## 4. Install AI-DLC and the guardrail hook (about 20 minutes)

```bash
curl -fsSL https://github.com/awslabs/aidlc-workflows/releases/latest/download/install.sh | sh
aidlc config --harness claude
aidlc doctor
git switch -c chore/aidlc-setup
```

`aidlc config` asks for your model provider. Choose your Claude subscription or `amazon-bedrock`; Bedrock settings go in `.claude/settings.local.json`, which isn't committed.

Add the guardrail hook to `.claude/settings.json` in the same terminal, before you start Claude Code. AI-DLC doesn't let Claude Code edit that file, so this step is yours. Build the merged settings and review the change:

```bash
merged="$(mktemp)"
jq --slurpfile add tools/claude-hooks/settings.hooks.json '
  reduce ($add[0].hooks | to_entries[]) as $event (.;
    .hooks[$event.key] = [(.hooks[$event.key] // [])[]
                          | select(tostring | contains("tools/claude-hooks/") | not)]
                         + $event.value)
' .claude/settings.json > "$merged"
diff -u .claude/settings.json "$merged"
```

In the diff, only the `guard-bash.sh` group at the end of `PreToolUse` may change; every AI-DLC hook and permission stays. Then install it and run the hook's tests, which must print `26 passed, 0 failed`:

```bash
cp "$merged" .claude/settings.json && rm "$merged"
bash tools/claude-hooks/test-guard.sh
```

Only when they pass, start Claude Code with `claude`.

In Claude Code, trust the folder. If it asks you to approve the project's hooks, approve them and restart Claude Code. Then test the guardrail: ask Claude to run `terraform apply`. The command must be blocked, and a line must appear in `docs/evidence/hook-audit.jsonl`. Commit, open a PR, fill in the template, and merge.

## 5. Inception with AI-DLC (2 or 3 sessions)

```bash
git switch main && git pull
git switch -c inception/requirements
claude
```

Start the workflow:

```text
/aidlc "Build the Multi-Cloud Agentic SRE system described in docs/plan.md. Run Inception for Phases 1 to 3 only: requirements, non-functional requirements (safety, cost, latency), risks and units of work. Phrase acceptance criteria in EARS and give each an ID (REQ-001). Treat docs/plan.md as input to question, not as settled requirements."
```

Answer the stage questions. Use Request Changes when something is off, and Approve at each gate. Then:

- Set ADR-0001 to Accepted, or amend it.
- Open the PR. In "AI involvement", say what you changed in AI-DLC's drafts.
- Optional: a 30-minute review with a peer before you approve the requirements.

## 6. Spike A: Rancher MCP through AgentCore Gateway (1 or 2 sessions, about US$2)

**Question:** can an agent use `rancher-ai-mcp` with a read-only Rancher token, through AgentCore Gateway?

**Result (2026-11-14): yes, privately.** ADR-0002 records the decision, and `docs/evidence/spike-a/` the checks. The steps below are what ran. The scripts they name ran from the git-ignored `build/spike-a/` and land in a follow-up pull request under `tools/spikes/spike-a/`.

Everything runs on one temporary x86 EC2 instance, plus an internal load balancer and AgentCore resources for A5; A6 removes them all. Claude's AWS credentials stay read-only. You run every step that creates, changes or deletes something, from your admin terminal, and the passwords and the agent's token go only to your Keychain.

**A1. Launch the instance (you, AWS CLI).**

- us-east-1 had no default VPC, so A1 creates one. The account's only other VPC belongs to another project; don't use it.
- A key pair, `rancher-spike` (ED25519), saved straight to `~/.ssh/rancher-spike.pem` with mode 400.
- A security group, `rancher-spike`, that allows SSH and HTTPS from your current address (`/32`) only. The console's "Allow HTTPS traffic from the internet" box would open 443 to everyone.
- A `t3.large` running Ubuntu Server 24.04 (the SSM parameter `/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id`), with 30 GiB of encrypted gp3 storage, IMDSv2 required, and the tag `Name=rancher-spike`. Its cloud-config user data installs Docker and runs `rancher/rancher:v2.15.3@sha256:3f3a50c6e49c1cf5b4673bef236e0f260f36055de4d073438e38c441dc97aa9b`, the version the lab runs, pinned by digest.

**A2 and A3. Set up Rancher and the agent's identity (you, one script).** `configure_spike_rancher.py <public IP>`:

- waits until Rancher has finished starting. Rancher answers `/ping` minutes before its other routes, so the script waits until `/cacerts` serves Rancher's CA, saves that CA, and from then on trusts only it;
- reads the generated bootstrap password from the container's log over SSH, signs in, and replaces it with a random admin password;
- sets the server URL to `https://<public IP>`, after which Rancher's certificate names that address;
- reuses `tools/lab/configure_rancher.py` to create the `agent-readonly` cluster role, the `sre-agent` user with `user-base` only, and the user's binding on `local`. It then issues `sre-agent` an API token that expires one day after its first use.

The admin password, the `sre-agent` password and the token go to your Keychain (service `rancher-spike`). Nothing secret is printed.

**A4. Test the server directly.** `rancher-ai-mcp` publishes no public image, and only v1.2.0-alpha releases have stdio mode. So build v1.2.0-alpha.5 from commit `46f49c7e4e296e003b01c05ab97fb918c733cb49` with its `package/Dockerfile`. Run it in stdio mode in a container, with the token from your Keychain as an environment variable and `SSL_CERT_FILE` pointing at Rancher's CA, so no `--insecure` is needed. `mcp_probe.py` speaks MCP to it.

Pass: the probe lists namespaces and pods in `local`, and Rancher refuses both a Secrets list and a pod patch with HTTP 403. The server has no delete tool, so the write test patches a pod that doesn't exist: Kubernetes checks the permission first, so a 403 means no right, and nothing can change either way. With `--read-only`, the server offers 29 tools and no write tool.

**A5. Through AgentCore Gateway, privately (you, one script).** Run `setup_gateway.py plan`, then `setup_gateway.py apply`. It sets up:

- the server, built for x86 on the instance and run in HTTP mode with `--insecure --read-only` on port 9092. Outside a cluster, HTTP mode needs `--insecure`;
- an internal load balancer with a public ACM certificate for `mcp-spike.<your domain>`, validated in your public Route 53 zone. It sits in the instance's zone and one more, and has `drop_invalid_header_fields` off, because the token's header, `R_token`, has an underscore. Only the load balancer may reach port 9092;
- an API key credential provider that holds the token, and a gateway role that may read only that secret. For `GetResourceApiKey`, the role needs the gateway's own workload identity as well;
- a gateway with IAM sign-in, and an MCP target at `https://mcp-spike.<your domain>/mcp` that sends the token in `R_token`. A managed VPC Lattice private endpoint carries the target's traffic to the load balancer. It takes subnets only in use1-az1, az2, az4, az5 or az6.

Pass: through AWS's SigV4 proxy (`mcp-proxy-for-aws-cli` 1.8.0), `mcp_probe.py --gateway` lists the 29 tools, prefixed `rancher___`, and a tool call returns the 20 namespaces. An unsigned request gets HTTP 401. A target's `READY` status alone proves nothing: the gateway discovers tools with the caller's credentials but calls them with its own role.

Record the result in ADR-0002. Had the spike failed, the fallback was a generic Kubernetes MCP server with a Rancher-generated kubeconfig, which still goes through the Rancher proxy.

**A6. Tear down (you).** Run `teardown.py plan`, then `teardown.py apply` in a separate block. In order, it removes:

- the gateway target, the gateway and the credential provider;
- the gateway role;
- the listener, the load balancer and the target group;
- the security groups;
- the ACM certificate and its validation record;
- the instance, its security group and its key pair;
- the default VPC, only if it is still the default VPC and holds nothing else;
- the Keychain items and the local files.

The instance and the load balancer together cost about US$0.10 an hour while they run.

## 7. Spike B: AKS to AWS without keys (1 session, under a dollar)

**Question:** can a pod in AKS assume an IAM role with its own service-account token, so the AKS collector needs no AWS keys?

**Result (2026-11-14): yes.** ADR-0003 records the decision, and `docs/evidence/spike-b/` the run. The steps below are what ran.

**(you)** Create a small AKS cluster with an OIDC issuer, and register the issuer in IAM. This subscription doesn't allow `Standard_B2s` in East US, and its B-series v2 and Dsv5 families have no vCPU quota, so the node is a `Standard_D2s_v6`. Check `az vm list-usage --location eastus` before you choose another size. Node SSH stays off, so no SSH key is generated. The cluster takes 5 to 10 minutes:

```bash
export AWS_PROFILE=sre-lab AWS_REGION=us-east-1
cd ~/Downloads/multi_cloud_agentic_SRE
az group create -n rg-sre-spike -l eastus --query properties.provisioningState -o tsv
az aks create -g rg-sre-spike -n aks-spike --tier free --node-count 1 --node-vm-size Standard_D2s_v6 --enable-oidc-issuer --ssh-access disabled --query provisioningState -o tsv
az aks get-credentials -g rg-sre-spike -n aks-spike --overwrite-existing
ISSUER=$(az aks show -g rg-sre-spike -n aks-spike --query oidcIssuerProfile.issuerUrl -o tsv)
aws iam create-open-id-connect-provider --url "$ISSUER" --client-id-list sts.amazonaws.com --tags Key=Name,Value=aks-spike --query 'OpenIDConnectProviderArn' --output text | sed -E 's/[0-9]{12}/<account>/'
```

**(you)** Create the role and run the test pod. The trust policy and the pod are filled in on the fly from `tools/spikes/`, so no account or issuer details reach Git. The role needs no permission policies, because `sts get-caller-identity` requires none:

```bash
export AWS_PROFILE=sre-lab AWS_REGION=us-east-1
cd ~/Downloads/multi_cloud_agentic_SRE
PROVIDER_ARN=$(aws iam list-open-id-connect-providers --query "OpenIDConnectProviderList[?contains(Arn, 'oic.prod-aks.azure.com')].Arn | [0]" --output text)
ISSUER_PATH="${PROVIDER_ARN#*oidc-provider/}"
sed -e "s|OIDC_PROVIDER_ARN|$PROVIDER_ARN|" -e "s|ISSUER_HOST_AND_PATH|$ISSUER_PATH|g" tools/spikes/spike-b-trust-policy.json > /tmp/spike-b-trust.json
aws iam create-role --role-name aks-spike-otel --assume-role-policy-document file:///tmp/spike-b-trust.json --query 'Role.RoleName' --output text
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
sed "s/ACCOUNT_ID/$ACCOUNT_ID/" tools/spikes/spike-b-pod.yaml | kubectl --context aks-spike apply -f -
kubectl --context aks-spike wait -n spike --for=jsonpath='{.status.phase}'=Succeeded pod/whoami --timeout=180s
kubectl --context aks-spike logs -n spike whoami 2>&1 | grep -E '"Arn"|rror' | sed -E 's/[0-9]{12}/<account>/g'
```

Pass: the last line shows the `assumed-role/aks-spike-otel` ARN. IAM keeps the issuer's trailing `/` in the provider's URL and ARN, so the role's condition keys must keep it too, and deriving them from the ARN, as above, does. If you get `InvalidIdentityToken`, compare the token's `iss` claim with the provider URL.

**(you)** Tear down, in a block of its own, once the result is recorded. It deletes the resource group with the cluster, the role, the IAM provider and the cluster's entries in your kubeconfig:

```bash
export AWS_PROFILE=sre-lab AWS_REGION=us-east-1
az group delete -n rg-sre-spike --yes
aws iam delete-role --role-name aks-spike-otel
PROVIDER_ARN=$(aws iam list-open-id-connect-providers --query "OpenIDConnectProviderList[?contains(Arn, 'oic.prod-aks.azure.com')].Arn | [0]" --output text)
aws iam delete-open-id-connect-provider --open-id-connect-provider-arn "$PROVIDER_ARN"
kubectl config delete-context aks-spike
kubectl config delete-cluster aks-spike
kubectl config delete-user clusterUser_rg-sre-spike_aks-spike
rm -f /tmp/spike-b-trust.json
```

## 8. Spike C: Claude Code telemetry (30 minutes)

**Result (2026-11-14): passed.** `docs/evidence/telemetry/claude-code-2026-11-14.md` holds the metric names and values.

Start the collector from the repository root. It is pinned by digest, listens only on this Mac, and runs in the background:

```bash
docker run -d --rm --name spike-c-collector -p 127.0.0.1:4317:4317 -p 127.0.0.1:4318:4318 -v "$PWD/tools/otel/collector-local.yaml:/etc/otelcol-contrib/config.yaml:ro" otel/opentelemetry-collector-contrib:0.165.0@sha256:e40d61f10c9a617cca1ffd1be4d7e2b3a4b0f0001798ff07e58cabe82e618cea
```

In a second terminal, start Claude Code outside the repository, so this project's AI-DLC hooks don't record the session. Type one prompt, wait about 15 seconds, then `/exit`:

```bash
cd /tmp
export CLAUDE_CODE_ENABLE_TELEMETRY=1 OTEL_METRICS_EXPORTER=otlp OTEL_EXPORTER_OTLP_PROTOCOL=grpc OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 OTEL_METRIC_EXPORT_INTERVAL=10000
claude
```

Pass: `docker logs spike-c-collector` shows `claude_code.session.count`. The data points also carry your email, your account and organization IDs and the session ID, so save metric names and values only to `docs/evidence/telemetry/`. Then run `docker stop spike-c-collector`. From Phase 1, the same variables point at the collector that writes to Managed Prometheus, and that collector must drop or hash those identifiers first.

## 9. Close Phase 0 (by 2026-11-29)

- [x] Inception approved in AI-DLC; ADR-0001 accepted
- [x] ADR-0002 (Rancher MCP) and ADR-0003 (AKS to AWS identity) recorded, each a pass or a chosen fallback
- [x] Telemetry excerpt in `docs/evidence/telemetry/`
- [x] Ruleset exported to `docs/evidence/rulesets/`
- [x] Spike resources deleted, and both budgets show no surprises

**Closed on 2026-11-14,** ahead of the gate:

- ADR-0001 was accepted on 2026-11-13. ADR-0002 and ADR-0003 record passes, not fallbacks, and you accepted both on 2026-11-14.
- `docs/evidence/` holds the ruleset (`rulesets/`), the telemetry excerpt (`telemetry/`) and the spikes' records (`spike-a/`, `spike-b/`).
- Spikes A and B were torn down, and read-only checks found nothing left in AWS or Azure.
- Budgets, read on 2026-11-14:
  - AWS: `sre-lab-aws` (US$300 a month) stood at US$20.95. Most of it was the domain registration and its tax; all three spikes together cost under US$2.
  - Azure: `sre-lab-azure` (US$50 a month, alerts at 50, 80 and 100%) sits at the billing-account scope, where the portal puts budgets for a Microsoft Customer Agreement, so it covers the subscription.

Phase 1 began before this close-out: u1's pull requests 1 to 3 are merged, and pull request 4, the agent's first read through Rancher, waits for Bedrock access. Continue it with `/aidlc`.
