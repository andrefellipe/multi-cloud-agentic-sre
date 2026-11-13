"""The contracts u1 owns, as Pydantic v2 models (contract design Q1).

- C1, the alert notification: :mod:`agents.contracts.alert`;
- C3, the incident record: :mod:`agents.contracts.incident`;
- C4, the session start, and C5, the agent result envelope: :mod:`agents.contracts.session`;
- C7, the notice: :mod:`agents.contracts.notify`;
- the dead-letter item: :mod:`agents.contracts.dead_letter`;
- the skeleton's settings: :mod:`agents.contracts.settings`.

Every message and record carries ``schema_version`` 1, and unknown fields are
ignored. :mod:`agents.contracts.schema_export` writes them out as JSON Schema.
"""
