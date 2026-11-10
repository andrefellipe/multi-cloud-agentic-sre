#!/usr/bin/env bash
# Tests for guard-bash.sh. Runs locally and in CI (methodology-checks).
set -u
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
pass=0
fail=0

check() { # expected_exit command [description]
  expected="$1"; cmd="$2"; desc="${3:-run a command}"
  json=$(printf '{"tool_name":"Bash","tool_input":{"command":"%s","description":"%s"}}' "$cmd" "$desc")
  printf '%s' "$json" | CLAUDE_PROJECT_DIR="$tmp" bash "$here/guard-bash.sh" >/dev/null 2>&1
  got=$?
  if [ "$got" -eq "$expected" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    echo "FAIL (expected exit $expected, got $got): $cmd"
  fi
}

# Allowed
check 0 "terraform plan -out tfplan"
check 0 "terraform plan" "Plan before a human runs terraform apply"
check 0 "kubectl get pods -A"
check 0 "kubectl diff -f platform/app.yaml"
check 0 "kubectl apply --dry-run=client -f platform/app.yaml"
check 0 "helm template demo ./chart"
check 0 "git push origin feature/agent-graph"
check 0 "git push -u origin feature/fix-flag"
check 0 "rm -rf build/"
check 0 "aws sts get-caller-identity"
check 0 "az aks list -o table"

# Blocked
check 2 "terraform apply -auto-approve"
check 2 "cd infra/aws && terraform destroy"
check 2 "kubectl delete pod web-1 -n demo"
check 2 "kubectl apply -f platform/app.yaml"
check 2 "kubectl rollout restart deploy/web"
check 2 "helm upgrade --install demo ./chart"
check 2 "git push --force origin main"
check 2 "git push origin main -f"
check 2 "git reset --hard HEAD~1"
check 2 "rm -rf ~"
check 2 "aws ec2 terminate-instances --instance-ids i-0abc"
check 2 "aws s3 rb s3://lab-bucket --force"
check 2 "aws eks delete-cluster --name lab"
check 2 "az group delete -n rg-sre-lab --yes"

# A block must leave an audit line with the rule only
if grep -q '"rule":"terraform apply"' "$tmp/docs/evidence/hook-audit.jsonl" 2>/dev/null &&
   ! grep -q 'auto-approve' "$tmp/docs/evidence/hook-audit.jsonl"; then
  pass=$((pass + 1))
else
  fail=$((fail + 1))
  echo "FAIL: audit log missing or contains command arguments"
fi

echo "guard-bash tests: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
