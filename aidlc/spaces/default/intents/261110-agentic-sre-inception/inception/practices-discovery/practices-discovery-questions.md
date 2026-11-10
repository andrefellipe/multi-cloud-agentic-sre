# Practices Discovery Questions

These cover only what the repository could not settle on its own. The draft practices are in `team-practices.md` and the evidence in `evidence.md` (same folder). Each question names the trade whose call it is; anyone may answer any of them.

## Q1. [Release engineer] How should pull requests merge into `main`?

The history shows one commit per PR with a `(#N)` suffix, which looks like squash merges, but the GitHub merge settings were not inspected.

A. Squash merge only: one commit per PR on `main` (recommended: matches the history and the "one task per PR" rule)
B. Merge commits: keep every branch commit plus a merge commit
C. Rebase merge: linear history, branch commits kept individually
X. Other (please specify)

[Answer]: A

## Q2. [Release engineer] Should branch names follow a convention?

The current branch is `inception/requirements`; nothing enforces a pattern.

A. `<type>/<topic>`, e.g. `feat/alert-intake` (recommended: matches today's branch and Conventional Commit types)
B. `<type>/REQ-NNN-<topic>`, carrying the requirement ID in the branch name
C. No convention
X. Other (please specify)

[Answer]: B

## Q3. [Release engineer] What environments does a change pass through?

The org default is "deploy on merge to staging, production behind a manual approval", but this project has one lab cluster per cloud and no production.

A. One lab per cloud; merging to `main` is the release (Fleet syncs from `main`) and the human merge is the only gate (recommended: matches the plan; no prod exists)
B. A separate dev/eval cluster that `main` deploys to first, then the lab
C. A staging/production split as in the org default
X. Other (please specify)

[Answer]: A

## Q4. [Release engineer] Who runs `terraform apply` after a Terraform PR merges, for Phases 1 to 3?

The sources disagree: `docs/plan.md` says "a job applies it", `CLAUDE.md` says "the human applies".

A. The human applies locally after merge (recommended: matches `CLAUDE.md` and keeps the coding agent and CI free of write credentials for now)
B. A GitHub Actions job behind an approval-gated environment applies it
C. Decide later in an ADR; the human applies until then
X. Other (please specify)

[Answer]: A

## Q5. [Release engineer] How should releases be marked?

A. A Git tag at each phase gate and at v1.0 (recommended: gives the plan's phase gates a fixed point to point at)
B. A v1.0 tag only
C. Semantic versions per component
X. Other (please specify)

[Answer]: A

## Q6. [Release engineer] How strictly should third-party actions and container images be pinned?

Today `actions/checkout@v5` and some `:latest` images are used.

A. Actions pinned by commit SHA and images by digest from Phase 1 (recommended: supply-chain safety for a project whose point is safety)
B. Version tags only (no `:latest`) until Phase 6, then SHA/digest
C. Leave as is for now
X. Other (please specify)

[Answer]: A

## Q7. [Quality engineer] When are tests written relative to the code?

Nothing in the repo shows tests written first. The plan also has eval scenarios (incident replays scored in CI).

A. Test-after: write each layer, then its tests (recommended: the default for this plan, and nothing suggests otherwise)
B. Test-first (TDD) for Python agent and tool code
C. Mixed: write the eval scenario for a requirement first, unit tests after the code
X. Other (please specify)

[Answer]: A

## Q8. [Quality engineer] What coverage floor should CI enforce on Python code?

No pytest or coverage tool is set up yet; this plan's default is 80% line coverage, checked in CI before merge.

A. 80% line coverage on all Python, enforced in CI (recommended: the plan's default, and it cannot be lowered later to make a build pass)
B. 80% only on agent tool and policy code under `agents/`
C. No numeric floor; tests required per requirement instead
X. Other (please specify)

[Answer]: A

## Q9. [Developer] Which linters and formatters should block a PR?

None is configured today.

A. Ruff (lint + format), a type checker (mypy or pyright), ShellCheck, `terraform fmt`/`validate`, all blocking in CI (recommended: covers every language already in the repo)
B. Ruff plus Black only
C. Add each tool when its language first lands
X. Other (please specify)

[Answer]: A

## Q10. [Delivery lead] Build a thin end-to-end slice first? A walking skeleton is a minimal version that runs the whole way through, built first to prove the pieces connect before the real features go in.

Here that slice would be: an alert reaches the intake, opens an agent session, and the agent makes one read through Rancher. This plan's default is to skip it.

A. Yes, build the thin end-to-end slice first (recommended: the riskiest part of this system is the plumbing across AWS, Rancher and two clusters)
B. No, build the pieces in dependency order
X. Other (please specify)

[Answer]: A

## Q11. [Release engineer] How should branches be named for work that has no requirement ID?

Follow-up to Q2 (`<type>/REQ-NNN-<topic>`): housekeeping, docs and phase-level work (like today's `inception/requirements`) have no REQ ID, and PR descriptions already allow `Requirements: n/a`.

A. Drop the ID: `<type>/<topic>`, e.g. `docs/runbook-phase-1` (recommended: mirrors the PR template's `n/a`)
B. Use a literal placeholder: `<type>/NOREQ-<topic>`
C. Every branch must carry a REQ ID; create one if none exists
X. Other (please specify)

[Answer]: A
