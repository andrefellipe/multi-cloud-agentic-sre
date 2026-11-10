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
curl -fsSL https://claude.ai/install.sh | bash    # Claude Code, native installer
```

Install Docker Desktop (`brew install --cask docker-desktop`, or OrbStack) for the local collector spike (spike C), and open it once to finish setup. Rancher runs on an EC2 instance instead (spike A).

## 3. Create the repository (about 20 minutes)

`~/Downloads` is a risky home for a months-long project. If you move the folder (to `~/Projects`, say), do it now, before `git init`.

```bash
cd ~/Downloads/multi_cloud_agentic_SRE
# The PR template and the CI workflow ship in tools/github-setup/; put them in place:
mkdir -p .github/workflows
cp tools/github-setup/pull_request_template.md .github/
cp tools/github-setup/methodology-checks.yml .github/workflows/
chmod +x tools/claude-hooks/*.sh
bash tools/claude-hooks/test-guard.sh        # expect: 26 passed, 0 failed
git init -b main
git add .
git commit -m "chore: Phase 0 scaffold" \
  -m "Drafted with Claude from the project plan; see ADR-0001." \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
gh repo create multi-cloud-agentic-sre --public --source . --push
# or --private, if you have GitHub Pro
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
claude
```

`aidlc config` asks for your model provider. Choose your Claude subscription or `amazon-bedrock`; Bedrock settings go in `.claude/settings.local.json`, which isn't committed.

In Claude Code, trust the folder, then ask:

> Merge the hooks in tools/claude-hooks/settings.hooks.json into .claude/settings.json without removing any existing AI-DLC hooks or permissions. Show me the diff, then run bash tools/claude-hooks/test-guard.sh.

Restart Claude Code, then test the guardrail: ask it to run `terraform apply`. The command must be blocked, and a line must appear in `docs/evidence/hook-audit.jsonl`. Commit, open a PR, fill in the template, and merge.

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

## 6. Spike A: Rancher MCP on an EC2 instance (1 or 2 sessions, about US$1)

**Question:** can an agent use `rancher-ai-mcp` with a read-only Rancher token, through AgentCore Gateway?

Everything runs on one temporary x86 EC2 instance, so nothing depends on your Mac's ARM chip. Keep it running only while you work on the spike.

**A1. Launch the instance (you).** In the EC2 console, region `us-east-1`, choose **Launch instance**:

1. **Name:** `rancher-spike`.
2. **AMI:** Ubuntu Server 24.04 LTS, architecture **64-bit (x86)**.
3. **Instance type:** `t3.large` (2 vCPU, 8 GiB), enough for single-node Rancher.
4. **Key pair:** create one named `rancher-spike` (ED25519, `.pem`), save it to `~/.ssh/`, then run `chmod 400 ~/.ssh/rancher-spike.pem`.
5. **Network settings:** allow SSH and HTTPS from **My IP** only.
6. **Storage:** 30 GiB gp3.
7. **Advanced details, User data:** paste this script, which installs Docker and starts Rancher:
   ```bash
   #!/bin/bash
   apt-get update -y
   apt-get install -y docker.io
   systemctl enable --now docker
   docker run -d --name rancher --restart=unless-stopped -p 80:80 -p 443:443 --privileged rancher/rancher:v2.15.0
   ```
8. **Launch instance**, then copy its **Public IPv4 address**.

**A2. Open Rancher** (about 5 minutes after launch). Get the bootstrap password:

```bash
ssh -i ~/.ssh/rancher-spike.pem ubuntu@<PUBLIC_IP> "sudo docker logs rancher 2>&1 | grep 'Bootstrap Password:'"
```

Open `https://<PUBLIC_IP>`, accept the self-signed certificate warning, paste the bootstrap password, set your admin password, and keep `https://<PUBLIC_IP>` as the server URL.

**A3. Create the agent's read-only identity:**

1. In **Users & Authentication, Role Templates, Cluster**, create a role named `agent-readonly` that can `get`, `list` and `watch` pods, pod logs, events, namespaces, deployments, replica sets, services and nodes. Leave out Secrets.
2. In **Users**, create the user `sre-agent` with the global permission **User-Base**.
3. Add `sre-agent` as a member of the `local` cluster with the `agent-readonly` role.
4. Sign in as `sre-agent` in a private browser window, then go to **Account & API Keys** and create an API key that expires in 1 day. Copy its bearer token.

**A4. Test from Claude Code.** Run `rancher-ai-mcp` following its README, with `RANCHER_URL=https://<PUBLIC_IP>` and `RANCHER_TOKEN` set to the `sre-agent` token, and register it in Claude Code with `claude mcp add`. Rancher's certificate is self-signed, so check the README for how the server should trust it.

Pass: Claude can list namespaces and pods in `local`, and asking it to delete a pod fails with a Rancher permission error, not only with the hook's block.

**A5. Through AgentCore Gateway:**

1. Run `rancher-ai-mcp` on the instance in HTTP mode with TLS. Open its port to the internet only for this test, protected by TLS and the token.
2. Register it as an AgentCore Gateway MCP target, and call one tool from a minimal Strands agent.
3. Find out how the Gateway can pass the Rancher token (an API-key credential provider, OAuth, or neither), and whether it accepts a self-signed certificate. If it doesn't, give the instance a DNS name and a trusted certificate, for example with Rancher's Let's Encrypt option.

Record the result in ADR-0002. If the spike fails, the fallback is a generic Kubernetes MCP server with a Rancher-generated kubeconfig, which still goes through the Rancher proxy.

**A6. Tear down (you):** terminate `rancher-spike`, then delete its security group and key pair. A `t3.large` costs about US$0.08 an hour, so a few hours of spike work cost about a dollar.

## 7. Spike B: AKS to AWS without keys (1 session, cents)

**Question:** can a pod in AKS assume an IAM role with its own service-account token, so the AKS collector needs no AWS keys?

**(you)** Create a small AKS cluster with an OIDC issuer, and register the issuer in IAM:

```bash
az group create -n rg-sre-spike -l eastus
az aks create -g rg-sre-spike -n aks-spike --tier free --node-count 1 \
  --node-vm-size Standard_B2s --enable-oidc-issuer --generate-ssh-keys
az aks get-credentials -g rg-sre-spike -n aks-spike
ISSUER=$(az aks show -g rg-sre-spike -n aks-spike --query oidcIssuerProfile.issuerUrl -o tsv)
aws iam create-open-id-connect-provider --url "$ISSUER" --client-id-list sts.amazonaws.com
aws iam list-open-id-connect-providers
```

**(you)** Create the role:

1. Fill in the trust policy in a temporary copy, so no account details reach Git:
   ```bash
   PROVIDER_ARN="<the ARN that list-open-id-connect-providers printed>"
   ISSUER_PATH="${PROVIDER_ARN#*oidc-provider/}"
   sed -e "s|OIDC_PROVIDER_ARN|$PROVIDER_ARN|" -e "s|ISSUER_HOST_AND_PATH|$ISSUER_PATH|g" \
     tools/spikes/spike-b-trust-policy.json > /tmp/spike-b-trust.json
   ```
2. Run `aws iam create-role --role-name aks-spike-otel --assume-role-policy-document file:///tmp/spike-b-trust.json`. It needs no permission policies, because `sts get-caller-identity` requires none.

**(you)** Run the test pod, filling in your account ID on the fly so the tracked file stays unchanged:

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
sed "s/ACCOUNT_ID/$ACCOUNT_ID/" tools/spikes/spike-b-pod.yaml | kubectl apply -f -
kubectl logs -n spike whoami
```

Pass: the log shows the `assumed-role/aks-spike-otel` ARN. If you get `InvalidIdentityToken`, compare the token's `iss` claim with the provider URL, including any trailing slash.

**(you)** Clean up with `az group delete -n rg-sre-spike --yes`, then delete the IAM role and the OIDC provider. Record the result in ADR-0003.

## 8. Spike C: Claude Code telemetry (30 minutes)

```bash
docker run --rm -p 4317:4317 -p 4318:4318 \
  -v "$PWD/tools/otel/collector-local.yaml:/etc/otelcol-contrib/config.yaml" \
  otel/opentelemetry-collector-contrib:latest
```

In a second terminal:

```bash
export CLAUDE_CODE_ENABLE_TELEMETRY=1 OTEL_METRICS_EXPORTER=otlp \
  OTEL_EXPORTER_OTLP_PROTOCOL=grpc OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
claude
```

Pass: within about a minute (the default export interval), the collector prints `claude_code.session.count`. Save a short excerpt with metric names and values only to `docs/evidence/telemetry/`. Pin the collector image to a version once it works. From Phase 1, the same variables point at the collector that writes to Managed Prometheus.

## 9. Close Phase 0 (by 2026-11-29)

- [ ] Inception approved in AI-DLC; ADR-0001 accepted
- [ ] ADR-0002 (Rancher MCP) and ADR-0003 (AKS to AWS identity) recorded, each a pass or a chosen fallback
- [ ] Telemetry excerpt in `docs/evidence/telemetry/`
- [ ] Ruleset exported to `docs/evidence/rulesets/`
- [ ] Spike resources deleted, and both budgets show no surprises

Then start Phase 1 with `/aidlc` on the first Construction unit.
