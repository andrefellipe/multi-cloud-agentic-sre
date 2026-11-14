#!/bin/bash
# Spike A, A4: start rancher-ai-mcp in stdio mode for an MCP client (Claude Code,
# or tools/spikes/spike-a/mcp_probe.py).
#
# The image is built locally from rancher/rancher-ai-mcp at v1.2.0-alpha.5
# (commit 46f49c7e4e29), the first release with stdio mode. The sre-agent token
# comes from your Keychain and reaches the container only as an environment
# variable: it is never printed or written to a file. The server checks Rancher's
# certificate against Rancher's own CA alone, through SSL_CERT_FILE; that CA and
# Rancher's URL were saved by configure_spike_rancher.py. Extra arguments go to
# `mcp serve`, for example --read-only to register only the read tools.
set -euo pipefail

state="$HOME/.rancher-spike"
image="rancher-ai-mcp:v1.2.0-alpha.5"

RANCHER_URL="$(cat "$state/rancher-url")"
RANCHER_TOKEN="$(/usr/bin/security find-generic-password -s rancher-spike -a sre-agent-token -w)"
export RANCHER_URL RANCHER_TOKEN

exec docker run -i --rm \
  -e RANCHER_URL -e RANCHER_TOKEN -e SSL_CERT_FILE=/certs/rancher-ca.pem \
  -v "$state/rancher-ca.pem:/certs/rancher-ca.pem:ro" \
  "$image" /usr/local/bin/mcp serve --stdio "$@"
