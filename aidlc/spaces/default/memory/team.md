# Team-Level Rules

> This team's affirmed practices and corrections. Loaded after `org.md` as
> strict-additive guidance; contradictions with broader policy are rejected.
> Populated by the practices-discovery affirmation gate. Edit at the gate,
> not directly.

## Way of Working

- We work trunk-based on `main`. Every change, human or agent, reaches `main` only through a pull request; nobody pushes to `main` directly. The `main` ruleset blocks force pushes and deletions, requires a pull request, has no bypass list, and requires the `pr-evidence` check.
- We squash-merge every pull request into `main`: one commit per PR, a Conventional Commit subject carrying the PR number, for example `chore: ... (#3)`. Merge commits and rebase merges are not used.
- Branches are short-lived. `<type>` is a Conventional Commit type (`feat`, `fix`, `docs`, `chore`), and the name takes one of two forms:
  - Requirement work: `<type>/REQ-NNN-<topic>`, for example `feat/REQ-012-alert-intake`, so the requirement ID travels from branch to commit to PR.
  - Work with no requirement ID (housekeeping, docs, phase-level work): `<type>/<topic>`, for example `docs/runbook-phase-1`, matching `Requirements: n/a` in the PR.
- One task per pull request. Commits and PR titles follow Conventional Commits and cite requirement IDs (`REQ-NNN`) when they apply.
- Every PR fills in the template: Summary, `Requirements:` (REQ IDs or `n/a`), `## AI involvement` (`AI wrote:` and `I changed or rejected:`), Evidence, and Risk and rollback. CI fails the PR when AI involvement or requirements are missing.
- The human owner is the only merger. The ruleset requires 0 approvals because GitHub forbids self-approval, so the human merge itself is the gate.
- Each piece of build work gets its own short-lived branch from `main` and lands back on `main` as one squash commit through its own PR.
- Each significant decision, including AI suggestions the human rejected, is recorded as an ADR in `docs/adr/` from `0000-template.md`.

## Walking Skeleton

- Always, for this project: we build a thin end-to-end slice first. The first piece of build work is the smallest integrated path that runs for real: an alert reaches the intake, opens an agent session, and the agent makes one read through Rancher.
- The slice is verified with a command the human has approved, demonstrating that real end-to-end result, and the human signs it off before later features are built on top of it.
- Reason: the riskiest part of this system is the plumbing across AWS, Rancher and two clusters, so we prove it connects before features pile up.

## Testing Posture

- **Methodology**: test-after
- **Methodology evidence**: The team chose test-after in the practices interview (Q7). It matches the history: the only tested code today (`tools/claude-hooks/guard-bash.sh`) has a separate assertion script (`test-guard.sh`, 26 assertions) that CI runs on every PR, and nothing shows tests written first.
- **Ordering**: For each testable layer, we implement the layer first, then write and run its tests before the pull request is opened.
- Coverage: 80% line coverage on all Python code, measured and enforced in CI before merge. The floor is never lowered to make a build pass.
- Python tests use `pytest`, run through `uv`, with type hints on all agent and tool code.
- All tests run in CI on every PR and must pass before merge; `pr-evidence` is already a required check.
- Shell guardrail scripts keep their assertion suite (`test-guard.sh`), extended whenever the guard changes.
- Infrastructure and manifests are verified without applying: `terraform fmt`, `terraform validate` and `terraform plan` for Terraform; `kustomize build` and `kubectl diff` for Fleet bundles.
- Agent behaviour is tested with evaluation scenarios that cite REQ IDs: a smoke tier (5 scenarios, replay) on every agent PR, a full tier nightly when agent code changed, and a live tier weekly and before a release (from `docs/plan.md`).
- Tests never call real cloud write APIs; they use fixtures, recorded replays or read-only credentials.

## Guard Policy

<!-- Affirmed by the team. Mode: strict, relaxed, or off. Strict here holds for every intent, whatever one person asks in chat; relaxed or off here applies to every intent whose policy came from its scope, unless project.md or the person sets another; changing this line changes it. A section under the retired Change Control heading, written by an earlier release, is still read. -->

## Deployment

- One lab environment per cloud (AWS `us-east-1`, Azure East US). There is no staging or production split.
- Merging to `main` is the release. Fleet syncs cluster state from `main`; the human merge is the only gate.
- Cloud changes reach AWS and Azure only through a reviewed Terraform plan in a PR. For Phases 1 to 3 the human runs `terraform apply` locally from the merged `main`; neither the coding agent nor CI holds write credentials for this.
- Nothing deploys from Claude or an agent directly: no `terraform apply`/`destroy`, no kubectl or helm writes, no cloud deletes.
- Every deploy-affecting PR records its rollback in "Risk and rollback"; rollback is a revert PR through the same path.
- Releases are marked with Git tags on `main`: one at each phase gate and one at `v1.0`. There are no release branches.
- The lab can be rebuilt from zero with one command and torn down with one; a scheduled teardown limits spend (from `docs/plan.md`).

## Code Style

- Python 3.12+, managed with `uv`, idiomatic `snake_case`, type hints throughout.
- Ruff for Python linting and formatting, configured in `pyproject.toml`, plus a type checker (mypy or pyright). Both run in CI and block the PR on failure.
- Shell scripts stay compatible with macOS bash 3.2 and BSD tools and are checked with ShellCheck, blocking in CI.
- Terraform: root modules under `infra/aws` and `infra/azure`, provider versions pinned, `terraform fmt -check` and `terraform validate` run before a change is proposed and block in CI.
- Kubernetes: Fleet bundles under `platform/` with kustomize overlays per cloud (`cloud=aws`, `cloud=azure`).
- From Phase 1, GitHub Actions are pinned by commit SHA and container images by digest; MCP servers stay pinned by exact version.
- Markdown docs use sentence-case headings; ADRs follow `docs/adr/0000-template.md`.
## Forbidden

<!-- Team-specific forbidden patterns -->

## Mandated

<!-- Team-specific mandates -->

## Corrections

<!-- Self-learning loop appends here. -->
