# Contract Design Questions

These questions pin down the agreements between the seven units. The units and their dependencies are in `inception/units-generation/unit-of-work.md` and `unit-of-work-dependency.md`, and the component shapes are in `inception/domain-design/components.md`. The system exposes no public API in Phases 1 to 3. Its external boundaries are inbound ones it consumes: Prometheus alerts arrive through SNS and GitHub webhooks arrive at the intake. Each question names the trade whose call it is.

## Q1. [Architect] How should the in-process contracts be written down?

Most boundaries are in-process Python calls inside the agent runtime and the intake Lambda: session to agents, callers to the sanitizer, intake to the ledger.

A. Typed Pydantic models in one shared contracts package, versioned with the code, with JSON Schema exported from them for the docs and for CI checks (recommended: one source of truth that type-checks and validates agent output, the "malformed output" corner)
B. JSON Schema files as the source, with code generated from them
C. Plain typed dicts, documented in Markdown only
X. Other (please specify)

[Answer]: A

## Q2. [Architect] What is the versioning and breaking-change policy?

A. Every message carries a `schema_version`. Within a phase, only additive changes are allowed, and consumers ignore unknown fields. A breaking change needs a new major version, both versions accepted for one release, and an ADR (recommended: safe for replays recorded on older versions)
B. Semantic versioning per contract, with no dual-acceptance period
C. No versioning while the project is a lab
X. Other (please specify)

[Answer]: A

## Q3. [Security engineer] How should agent write tools be held back until the kill switch exists?

The units review found that u6 gives agents GitHub write tools, while the kill switch only arrives in u7.

A. The governed tool contract includes a write-enable flag that is off by default. u6 ships with every GitHub write tool denied, and the flag can only be turned on after u7's kill switch is merged and tested; you flip it yourself (recommended: closes the gap without reshaping the units)
B. Move the kill-switch policy into u6
C. Accept the risk and rely on build order
X. Other (please specify)

[Answer]: A

## Q4. [Operations engineer] What timeout and retry defaults should each boundary carry?

A. Per boundary:
   - intake to ledger: 2 s timeout, 3 retries with jittered backoff;
   - intake to session start: asynchronous, with the dead-letter queue after 3 attempts;
   - agent tool calls through the gateway: 30 s timeout; reads retried twice, writes never retried automatically;
   - sanitizer: fail closed, no retry;
   - Slack: 3 retries with backoff, never blocking.

   Recommended: matches the requirements' corner cases and keeps writes from being repeated.
B. A uniform 3 retries everywhere
C. Leave it to NFR design
X. Other (please specify)

[Answer]: A
