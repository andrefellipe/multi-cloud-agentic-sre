# Project-Level Rules

> Project-specific specialisation and corrections. Loaded after `org.md` and
> `team.md` as strict-additive guidance; contradictions with broader policy
> are rejected. Populated by practices-discovery and the self-learning loop.
>
> Use sparingly: most teams don't need a project layer. Reach for it
> only when this specific project needs stable, durable guidance beyond the
> team practice (for example, package-specific release checks or an additional
> regression suite for a legacy component).

## Way of Working

<!-- Project-specific specialisation. Example: -->
<!-- This monorepo requires package-scoped branch names and a package owner -->
<!-- review in addition to the team's normal merge policy. -->

## Walking Skeleton

<!-- Project-specific specialisation. Example: -->
<!-- The walking skeleton must exercise the legacy service adapter as well -->
<!-- as the new service boundary. -->

## Testing Posture

<!-- Project-specific specialisation. -->

## Guard Policy

<!-- Project-specific. Mode: strict, relaxed, or off. Strict here holds for every intent, whatever one person asks in chat; relaxed or off here applies to every intent whose policy came from its scope, unless the person sets another; changing this line changes it. A section under the retired Change Control heading, written by an earlier release, is still read. -->

## Deployment

<!-- Project-specific specialisation. -->

## Code Style

<!-- Project-specific specialisation. -->

## Tech Stack

<!-- Technology choices locked for this project. -->

## Decided

<!-- Decisions made in earlier stages that should not be re-asked. -->
<!-- Format: DECIDED: [decision] (Stage [slug], [date]) -->

## Scope Overrides

<!-- Custom scope rules for this project. -->

## Forbidden

<!-- Populated by practices-discovery affirmation gate. -->
<!-- Format: NEVER [behavior] (affirmed [date]) -->
<!-- Example: NEVER throw exceptions across service layer boundaries (affirmed 2026-05-17) -->

- NEVER run `terraform apply` or `terraform destroy`; the human applies. (CLAUDE.md, Safety rules; enforced by `tools/claude-hooks/guard-bash.sh`) (affirmed 2026-11-10)

- NEVER run kubectl write commands (`apply`, `create`, `delete`, `patch`, `edit`, `scale`). (CLAUDE.md, Safety rules) (affirmed 2026-11-10)

- NEVER run `helm install`, `helm upgrade` or `helm uninstall`. (CLAUDE.md, Safety rules) (affirmed 2026-11-10)

- NEVER run cloud delete commands. (CLAUDE.md, Safety rules) (affirmed 2026-11-10)

- NEVER write secrets, tokens, kubeconfigs or account IDs into files, commits, PRs or logs; use environment variables, AWS Secrets Manager or AgentCore Identity. (CLAUDE.md, Safety rules) (affirmed 2026-11-10)

- NEVER edit or delete AI-DLC records under `aidlc/` by hand. (CLAUDE.md, Method) (affirmed 2026-11-10)

- NEVER push directly to `main` or force-push it; every change reaches `main` through a pull request the human merges. (docs/runbooks/phase-0.md, ruleset "main"; interview Q3) (affirmed 2026-11-10)

## Mandated

<!-- Populated by practices-discovery affirmation gate. -->
<!-- Format: ALWAYS [behavior] (affirmed [date]) -->
<!-- Example: ALWAYS use Result<T,E> for fallible operations in service layer (affirmed 2026-05-17) -->

- ALWAYS deliver changes to clusters through Git (Fleet bundles under `platform/`) and changes to cloud resources through Terraform pull requests. (CLAUDE.md, Safety rules) (affirmed 2026-11-10)

- ALWAYS use read-only credentials by default, and ask the human before using any credential with write access. (CLAUDE.md, Safety rules) (affirmed 2026-11-10)

- ALWAYS verify infrastructure and cluster changes with non-mutating commands only: `terraform plan`, `kubectl diff`, `kustomize build`, `helm template` or `--dry-run`. (CLAUDE.md, Safety rules) (affirmed 2026-11-10)

- ALWAYS leave `terraform apply` to the human, who runs it locally from the merged `main` for Phases 1 to 3. (CLAUDE.md, Safety rules; interview Q4) (affirmed 2026-11-10)

- ALWAYS run `terraform fmt` and `terraform validate` before proposing a Terraform change, and pin provider versions. (CLAUDE.md, Engineering conventions) (affirmed 2026-11-10)

- ALWAYS squash-merge pull requests into `main`, one commit per PR. (interview Q1) (affirmed 2026-11-10)

- ALWAYS pin GitHub Actions by commit SHA and container images by digest from Phase 1 onward. (interview Q6) (affirmed 2026-11-10)

- ALWAYS enforce 80% line coverage on all Python code in CI before merge, without lowering the floor to make a build pass. (interview Q8) (affirmed 2026-11-10)

- ALWAYS run Ruff (lint and format), a Python type checker, ShellCheck, and `terraform fmt`/`validate` in CI as blocking checks. (interview Q9) (affirmed 2026-11-10)

- ALWAYS write acceptance criteria in EARS form ("WHEN ..., THE SYSTEM SHALL ...") with a `REQ-NNN` ID, and cite those IDs in tasks, commits, PRs, tests and eval scenarios. (CLAUDE.md, Method) (affirmed 2026-11-10)

- ALWAYS name a branch `<type>/REQ-NNN-<topic>` when the work has a requirement ID, and `<type>/<topic>` when it has none. (interview Q2, Q11) (affirmed 2026-11-10)

- ALWAYS record each significant decision as an ADR in `docs/adr/` from `0000-template.md`, including AI suggestions the human rejected. (CLAUDE.md, Method) (affirmed 2026-11-10)

- ALWAYS use Conventional Commits, keep the `Co-Authored-By` trailer Claude Code adds, and keep each PR to one task. (CLAUDE.md, Commits and pull requests) (affirmed 2026-11-10)

- ALWAYS fill in the PR template's "AI involvement" section honestly: what the AI generated and what the human changed or rejected. (CLAUDE.md; enforced by `tools/ci/check_pr_body.py`) (affirmed 2026-11-10)

- ALWAYS work through `/aidlc` and pass its approval gates. (CLAUDE.md, Method) (affirmed 2026-11-10)

## Corrections

<!-- Project-specific corrections from human feedback. -->
<!-- Format: NEVER/ALWAYS [behavior] (learned [date]) -->
