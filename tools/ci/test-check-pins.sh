#!/usr/bin/env bash
# Tests for check_pins.sh (REQ-112.1). Runs locally and in CI (platform-render).
# Written for macOS bash 3.2 and BSD tools as well as Linux.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
pass=0
fail=0

sha="0123456789abcdef0123456789abcdef01234567"
digest="sha256:$(printf '%064d' 0)"

# run NAME EXPECTED_EXIT [PATH...]: runs the check; expect* and finish judge it.
run() {
  name="$1"
  expected_exit="$2"
  shift 2
  output="$(bash "$here/check_pins.sh" "$@" 2>&1)"
  status=$?
  case_ok=1
  [ "$status" -eq "$expected_exit" ] || note "expected exit $expected_exit, got $status"
}

note() {
  echo "FAIL ($name): $1"
  case_ok=0
}

# expect RULE COUNT: the run reported exactly COUNT findings of RULE.
expect() {
  found="$(printf '%s\n' "$output" | grep -c -- ": $1: ")"
  [ "$found" -eq "$2" ] || note "expected $2 '$1' finding(s), got $found"
}

# expect_total COUNT: the run reported exactly COUNT findings in all.
expect_total() {
  found="$(printf '%s\n' "$output" | grep -c -E '^[^:]+:[0-9]+: [a-z-]+: ')"
  [ "$found" -eq "$1" ] || note "expected $1 finding(s) in all, got $found"
}

finish() {
  if [ "$case_ok" -eq 1 ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf '%s\n' "$output" | while IFS= read -r line; do echo "    $line"; done
  fi
}

# 1. Pinned references pass: SHA-pinned and local actions, digests, exact versions.
mkdir -p "$tmp/pinned/.github/workflows" "$tmp/pinned/platform/demo"
cat > "$tmp/pinned/.github/workflows/ci.yml" <<EOF
name: ci
on: pull_request
jobs:
  build:
    runs-on: ubuntu-24.04
    container:
      image: node@$digest
    steps:
      - uses: actions/checkout@$sha # v5.1.0
      - uses: ./.github/actions/build
      - uses: hashicorp/setup-terraform@$sha
        with:
          terraform_version: "1.17.1"
      # Comments are skipped: runs-on: ubuntu-latest and image: nginx:latest.
      - run: test "\$(wc -l < notes.txt)" -gt 2 2>/dev/null
EOF
cat > "$tmp/pinned/platform/demo/fleet.yaml" <<EOF
defaultNamespace: otel-demo
helm:
  repo: https://open-telemetry.github.io/opentelemetry-helm-charts
  chart: opentelemetry-demo
  version: 0.40.1
EOF
cat > "$tmp/pinned/platform/demo/deployment.yaml" <<EOF
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
        - name: web
          image: ghcr.io/example/web:1.2.3@$digest
          imagePullPolicy: IfNotPresent
EOF
cat > "$tmp/pinned/.mcp.json" <<EOF
{
  "mcpServers": {
    "aws-iac": {
      "command": "uvx",
      "args": [
        "awslabs.aws-iac-mcp-server@1.0.26"
      ]
    },
    "docs": {
      "type": "http",
      "url": "https://mcp.example.com/mcp"
    }
  }
}
EOF
run "pinned references pass" 0 "$tmp/pinned/.github" "$tmp/pinned/platform" "$tmp/pinned/.mcp.json"
expect_total 0
finish

# 2. A latest tag or version is reported.
mkdir -p "$tmp/latest"
cat > "$tmp/latest/values.yaml" <<EOF
image: nginx:latest
sidecar:
  tag: latest
EOF
cat > "$tmp/latest/kustomization.yaml" <<EOF
images:
  - name: collector
    newTag: latest
EOF
cat > "$tmp/latest/ci.yml" <<EOF
jobs:
  build:
    runs-on: ubuntu-latest
EOF
cat > "$tmp/latest/.mcp.json" <<EOF
{
  "mcpServers": {
    "iac": {
      "command": "uvx",
      "args": [
        "awslabs.aws-iac-mcp-server@latest"
      ]
    }
  }
}
EOF
run "latest is reported" 1 "$tmp/latest"
expect latest 5
expect image-no-digest 1
expect_total 6
finish

# 3. A version range or wildcard is reported; exact versions next to them are not.
mkdir -p "$tmp/ranges"
cat > "$tmp/ranges/fleet.yaml" <<EOF
helm:
  chart: opentelemetry-demo
  version: ^0.40.0
EOF
cat > "$tmp/ranges/Chart.yaml" <<EOF
apiVersion: v2
version: 0.1.0
dependencies:
  - name: collector
    version: "~0.110.0"
  - name: gateway
    version: ">=1.2.0"
  - name: agent
    version: 1.x
EOF
cat > "$tmp/ranges/.mcp.json" <<EOF
{
  "mcpServers": {
    "pricing": {
      "command": "uvx",
      "args": [
        "awslabs.aws-pricing-mcp-server>=1.1.0"
      ]
    },
    "docs": {
      "command": "npx",
      "args": [
        "docs-mcp@^2.1.0"
      ]
    }
  }
}
EOF
run "ranges are reported" 1 "$tmp/ranges"
expect range 6
expect_total 6
finish

# 4. An action not pinned by a full commit SHA is reported.
mkdir -p "$tmp/actions"
cat > "$tmp/actions/ci.yml" <<EOF
jobs:
  build:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@main
      - uses: actions/cache
      - uses: actions/checkout@$sha # v5.1.0
      - uses: ./.github/actions/build
EOF
run "unpinned actions are reported" 1 "$tmp/actions"
expect action-not-sha 3
expect_total 3
finish

# 5. An image without a digest, and an MCP server without a version, are reported.
mkdir -p "$tmp/unpinned"
cat > "$tmp/unpinned/deployment.yaml" <<EOF
spec:
  containers:
    - name: web
      image: ghcr.io/example/web:1.2.3
EOF
cat > "$tmp/unpinned/ci.yml" <<EOF
jobs:
  build:
    runs-on: ubuntu-24.04
    container: node:22
    steps:
      - uses: docker://alpine:3.20
EOF
cat > "$tmp/unpinned/.mcp.json" <<EOF
{
  "mcpServers": {
    "pricing": {
      "command": "uvx",
      "args": [
        "awslabs.aws-pricing-mcp-server"
      ]
    }
  }
}
EOF
run "missing digests and versions are reported" 1 "$tmp/unpinned"
expect image-no-digest 3
expect mcp-unversioned 1
expect_total 4
finish

# 6. A usage error exits 2: no path at all, or a path that does not exist.
run "no path is a usage error" 2
expect_total 0
if [ "$case_ok" -eq 1 ]; then
  run "a missing path is a usage error" 2 "$tmp/absent"
  expect_total 0
fi
finish

echo "check_pins tests: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
