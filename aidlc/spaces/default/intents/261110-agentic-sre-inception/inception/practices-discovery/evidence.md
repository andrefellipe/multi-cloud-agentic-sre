# Practices Discovery Evidence

> Lead: aidlc-pipeline-deploy-agent, working alone (collaborators off for scope `classic`; no support contributions). Inspection only: no test, build or deploy was run. HEAD `69ec4cd` on branch `inception/requirements` (same commit as `main` and `origin/main`). Drafted 2026-11-10T10:21:27Z; integrated with the interview answers 2026-11-10T13:28:04Z; follow-up Q11 folded in 2026-11-10T13:31:06Z.

## Sources inspected

| Source | What it showed |
| --- | --- |
| `git log --all`, `git branch -a` | 3 commits on `main`, all by one author on 2026-11-10: `chore: Phase 0 scaffold`, then `chore: ... (#1)` and `chore: ... (#3)`. Local branches `main` and `inception/requirements`; remote `origin/main` only. No tags. |
| `.github/workflows/methodology-checks.yml` | One workflow on `pull_request` (opened/edited/synchronize/reopened/ready_for_review), job `pr-evidence`, `permissions: contents: read`; runs `tools/claude-hooks/test-guard.sh` and `tools/ci/check_pr_body.py`. No push, schedule or deploy workflow. |
| `.github/pull_request_template.md` | Summary, `Requirements:`, `## AI involvement` (`AI wrote:`, `I changed or rejected:`), Evidence checklist (tests, `terraform plan`/`kubectl diff`/`kustomize build`, eval scorecard), Risk and rollback. |
| `tools/ci/check_pr_body.py` | Fails the PR unless AI involvement fields are filled and `Requirements:` holds `REQ-\d{3}` or `n/a`/`none`. |
| `tools/claude-hooks/` | `guard-bash.sh` (PreToolUse denylist, fails closed), `test-guard.sh` (26 assertions), `settings.hooks.json`, README. |
| `CLAUDE.md` | Method (AI-DLC gates, EARS + REQ IDs, ADRs), safety rules (no apply/destroy, no kubectl/helm writes, no cloud deletes, no secrets, Git/Terraform-only change paths, read-only by default), conventions (uv, Python 3.12+, type hints, pytest; Terraform layout, pinning, fmt/validate; Fleet + kustomize overlays; one task per PR), commit/PR rules. |
| `docs/runbooks/phase-0.md` | `git init -b main`; `main` ruleset: Active, no bypass, restrict deletions, block force pushes, require PR with 0 approvals, required check `pr-evidence`; "From here on, every change goes through a pull request"; feature branches `chore/aidlc-setup`, `inception/requirements`. Lab accounts only (AWS `us-east-1`, Azure East US), budgets US$300/US$50. |
| `docs/plan.md` | Merge is the only gate to production; Fleet deploys from one repo by cluster label; Terraform PR, CI plan, human merge, job applies; eval tiers (smoke per PR, full nightly, live weekly/pre-release); "one command rebuilds, one tears down"; scheduled teardown; v1.0 "tagged"; GitHub OIDC for CI; Claude Code GitHub Action review. |
| `docs/adr/` | `0000-template.md`, `0001` and `0004`, both `Proposed`. |
| `aidlc/spaces/default/intents/261110-agentic-sre-inception/aidlc-state.md` | Scope `classic`, depth Standard, test strategy Standard, Construction unit-major, serial; operation stages (3.7, 4.x) skipped. |
| `.claude/scopes/aidlc-classic.md` | `skeleton: off`. |
| `aidlc/spaces/default/memory/team.md`, `project.md` | All practice sections empty: first run. |
| `aidlc/spaces/default/memory/org.md` | Framework defaults (trunk + squash; test-after; 80% floor for `classic`; deploy on merge to staging, manual prod gate; defer to linter config). Used as suggestions only. |

Reverse-engineering artifacts (all six read):

- `aidlc/spaces/default/codekb/multi_cloud_agentic_SRE/code-structure.md`: layout, placeholder folders, Conventional Commits with PR numbers, `REQ-NNN` format, Python script without type hints.
- `aidlc/spaces/default/codekb/multi_cloud_agentic_SRE/technology-stack.md`: Bash 3.2-compatible scripts, unpinned runner Python, `actions/checkout@v5`; uv/pytest/Terraform/Fleet required but absent; planned stack.
- `aidlc/spaces/default/codekb/multi_cloud_agentic_SRE/dependencies.md`: version pins on MCP servers, tag-only action pin, floating images; no lockfiles for dependency review yet.
- `aidlc/spaces/default/codekb/multi_cloud_agentic_SRE/code-quality-assessment.md`: no pytest, no coverage, no linters/formatters configured; no CODEOWNERS; CI gates judged by the PR's own copy (S7).
- `aidlc/spaces/default/codekb/multi_cloud_agentic_SRE/architecture.md`: as-built hook + CI gate; as-planned GitOps (Fleet) and Terraform loops with human merge.
- `aidlc/spaces/default/codekb/multi_cloud_agentic_SRE/business-overview.md`: solo human operator is the only production gate; lab project, Phase 0.

## Inferences

| Practice | Observed | Inferred by the lead | Outcome of the interview |
| --- | --- | --- | --- |
| Branching | Single long-lived branch `main`; short topic branches; PR-only ruleset | Trunk-based (GitHub-flow shape), not GitFlow | Confirmed (Q1, Q3) |
| Merge style | Commit subjects end in `(#1)`, `(#3)` with one commit per PR on `main` | Squash merge | Confirmed: squash only (Q1) |
| Branch naming | `chore/aidlc-setup`, `inception/requirements` | `<type>/<topic>` | Changed: `<type>/REQ-NNN-<topic>` for requirement work (Q2); `<type>/<topic>` when there is no requirement ID (Q11) |
| Deployment cadence | No deploy workflow; no environments; plan says merge is the gate | Merge to `main` = release; Fleet pulls from `main`; human applies Terraform after merge | Confirmed (Q3, Q4) |
| Environment topology | One lab account per cloud, one region each | No staging tier; org default does not fit as written | Confirmed: one lab per cloud (Q3) |
| Testing | Only `test-guard.sh`; written as a separate assertion script | test-after | Confirmed (Q7) |
| Coverage | None | `classic` default 80% would apply once pytest lands | Confirmed: 80% line, all Python, CI-enforced (Q8) |
| Code style | No linter/formatter config; macOS bash 3.2 compatibility | Ruff; ShellCheck for scripts | Confirmed and extended with a type checker and Terraform checks (Q9) |
| Releases | No tags; plan says "v1.0 tagged" | Tags on `main`, no release branches | Confirmed: tag at each phase gate and at v1.0 (Q5) |
| Pinning | Exact versions; `actions/checkout@v5`; some `:latest` images | SHA/digest pinning per the plan's ASI04 control | Confirmed: SHA and digest from Phase 1 (Q6) |
| Walking skeleton | `classic` scope has `skeleton: off`; plan's Phase 1 gate is "first alert" | A thin end-to-end slice first | Confirmed: always for this project (Q10) |

## Interview decisions

Answers recorded in `practices-discovery-questions.md`.

| Q | Topic | Chosen answer |
| --- | --- | --- |
| Q1 | Merge style into `main` | A. Squash merge only: one commit per PR on `main` |
| Q2 | Branch naming | B. `<type>/REQ-NNN-<topic>`, carrying the requirement ID in the branch name (differs from the lead's `<type>/<topic>` draft) |
| Q3 | Environments | A. One lab per cloud; merging to `main` is the release (Fleet syncs from `main`); the human merge is the only gate |
| Q4 | Who runs `terraform apply`, Phases 1-3 | A. The human applies locally after merge. Resolves the `docs/plan.md` ("a job applies it") versus `CLAUDE.md` ("the human applies") conflict in favour of `CLAUDE.md` for Phases 1-3 |
| Q5 | Release marking | A. A Git tag at each phase gate and at v1.0 |
| Q6 | Pinning | A. Actions pinned by commit SHA and images by digest from Phase 1 |
| Q7 | Test methodology | A. Test-after |
| Q8 | Coverage floor | A. 80% line coverage on all Python, enforced in CI before merge |
| Q9 | Blocking linters | A. Ruff (lint + format), a type checker (mypy or pyright), ShellCheck, `terraform fmt`/`validate`, all blocking in CI |
| Q10 | Walking skeleton | A. Yes: build the thin end-to-end slice first (alert reaches intake, opens an agent session, agent makes one read through Rancher) |
| Q11 | Branch naming without a requirement ID (follow-up to Q2) | A. Drop the ID: `<type>/<topic>`, e.g. `docs/runbook-phase-1`, mirroring the PR template's `Requirements: n/a`; requirement work keeps `<type>/REQ-NNN-<topic>` |

## Unresolved uncertainty

- GitHub repository merge settings were not inspected. Q1 affirms squash-only, but nothing yet shows that merge commits and rebase merges are disabled in the repository settings; the human should check and disable them.
- PR #2 is absent from `main` (history jumps from `#1` to `#3`). Presumably closed without merging; not verified.
- S7 (the CI gate scripts are judged by the PR's own copy, so a PR can weaken its own checks) is deferred to the safety requirements; no practice was affirmed for it here.
- Q9 leaves the type checker open (mypy or pyright); to be chosen, ideally by ADR, when the first Python code lands.
- Q4 settles Phases 1-3 only. How Terraform is applied from Phase 4 onward (for example an approval-gated CI job with OIDC, as `docs/plan.md` describes) remains open.
- The eval tiers and the one-command rebuild/teardown in Testing Posture and Deployment come from `docs/plan.md`; the interview did not ask about them separately.
- The `classic` scope declares `skeleton: off`, while Q10 affirms a walking skeleton for this project. The workflow configuration needs to honour the affirmed stance.
