# Spike A scripts

Phase 0's Spike A asked whether an agent can use `rancher-ai-mcp` with a read-only Rancher token through AgentCore Gateway. It can, privately. ADR-0002 records the decision and `docs/evidence/spike-a/` the checks. These are the scripts that ran the spike, kept so it can be repeated. The spike is torn down, and nothing here runs on its own.

## Who runs what

- **You run every write.** Each script that creates, changes or deletes something runs in your admin terminal, with an AWS profile that may write. Claude's AWS credentials stay read-only.
- **Plan before apply.** `setup_gateway.py` and `teardown.py` have a read-only `plan` mode. Run it, read what it lists, then run `apply` in a separate block.
- **Secrets never print.** The Rancher passwords and the agent's token go to your macOS Keychain (service `rancher-spike`), and the SSH key to `~/.ssh/rancher-spike.pem`. Output hides your domain, account ID and the instance's address.

## The steps, in order

| Step | What it does | How |
|---|---|---|
| A1 | Creates a default VPC (us-east-1 had none), the key pair, a security group open only to your address, and a `t3.large` that runs Rancher v2.15.3, pinned by digest | AWS CLI commands in `docs/runbooks/phase-0.md`, section 6, with `user-data.yaml` |
| A2, A3 | Waits until Rancher has finished starting, replaces the bootstrap password, and creates the `agent-readonly` cluster role, the `sre-agent` user with login access only, its binding on `local`, and a 1-day API token | `configure_spike_rancher.py <public IP>` |
| A4 | Runs `rancher-ai-mcp` v1.2.0-alpha.5 in stdio mode in a local container, with the token from the Keychain and Rancher's CA pinned, and calls its tools | `rancher-mcp.sh`, `mcp_probe.py tools` and `call` |
| A5 | Runs the server in HTTP mode on the instance, behind an internal load balancer with a public ACM certificate, and registers it as an AgentCore Gateway target reached through a managed VPC Lattice endpoint, with the token sent in the `R_token` header | `setup_gateway.py plan`, then `apply`; `debug-on` and `debug-off` switch the gateway's detailed errors; `mcp_probe.py --gateway` |
| A6 | Removes everything A1 to A5 created, in dependency order, and the spike's Keychain items and files on your Mac | `teardown.py plan`, then `apply`; `--keep-instance` removes only A5 |

Run each Python script from the repository root with `uv run python tools/spikes/spike-a/<script>`.

## What you need

- macOS, because the scripts use the Keychain through `/usr/bin/security`;
- Docker, for A4;
- `uv` and `uvx`, the AWS CLI and an admin AWS profile;
- a public Route 53 zone for the domain in the SSM parameter `/sre-lab/domain-name`, for A5's certificate.

## Tests

`tests/spikes/` tests the scripts without AWS, Rancher or the instance. It uses moto, botocore's Stubber with the real AgentCore service model, the Rancher fake in `tests/u1/tools_lab/conftest.py`, a local TLS server, and a fake MCP server on stdio.
